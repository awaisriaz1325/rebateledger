"""Credit matching and reconciliation status (SPEC §4.7.1, §4.7.2). Pure functions.

"Today" is always an argument (already converted to the tenant timezone by the
caller); the engine never reads the clock.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum

from app.engine.calculate import ZERO, engine_context
from app.engine.models import EngineInputError, Period

DEFAULT_ABS_TOLERANCE = Decimal("1.00")
DEFAULT_PCT_TOLERANCE = Decimal("0.005")
DEFAULT_SUGGESTION_WINDOW_DAYS = 60


class ReconStatus(StrEnum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_EARNED = "NOT_EARNED"
    MATCHED = "MATCHED"
    OVERPAID = "OVERPAID"
    PENDING = "PENDING"
    SHORT_PAID = "SHORT_PAID"
    MISSING = "MISSING"


class ReconFlag(StrEnum):
    EARLY_CREDIT = "EARLY_CREDIT"
    """A credit dated before the period ended (prepayment) — allowed, shown."""
    REVERSAL = "REVERSAL"
    """A negative credit (reversal) reduced C."""


@dataclass(frozen=True, slots=True)
class Tolerance:
    abs_amount: Decimal = DEFAULT_ABS_TOLERANCE
    pct: Decimal = DEFAULT_PCT_TOLERANCE

    def __post_init__(self) -> None:
        if self.abs_amount < 0 or self.pct < 0:
            raise EngineInputError("tolerances must be >= 0")

    def for_expected(self, expected: Decimal) -> Decimal:
        return max(self.abs_amount, self.pct * expected)


@dataclass(frozen=True, slots=True)
class Credit:
    credit_id: str
    supplier_id: str
    credit_date: date
    amount: Decimal
    reference: str
    agreement_reference: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    period_label: str | None = None


@dataclass(frozen=True, slots=True)
class Allocation:
    credit_id: str
    agreement_id: str
    period_start: date
    period_end: date
    amount: Decimal
    method: str = "manual"
    """auto | manual"""


@dataclass(frozen=True, slots=True)
class MatchTarget:
    """One agreement-period that credits can be allocated to."""

    agreement_id: str
    supplier_id: str
    external_reference: str | None
    period: Period


@dataclass(frozen=True, slots=True)
class ReconItem:
    agreement_id: str
    period_start: date
    period_end: date
    expected: Decimal | None
    received: Decimal
    variance: Decimal | None
    tolerance: Decimal | None
    status: ReconStatus
    due_date: date
    flags: tuple[ReconFlag, ...]


def reconcile_item(
    *,
    agreement_id: str,
    period: Period,
    expected: Decimal | None,
    engine_needs_review: bool,
    allocations: Sequence[Allocation],
    credit_dates: dict[str, date],
    payment_terms_days: int,
    today: date,
    tolerance: Tolerance,
) -> ReconItem:
    """Status per SPEC §4.7.2 table, evaluated top to bottom."""
    with localcontext(engine_context()):
        mine = [
            a
            for a in allocations
            if a.agreement_id == agreement_id
            and a.period_start == period.start
            and a.period_end == period.end
        ]
        received = sum((a.amount for a in mine), Decimal("0.00"))
        flags: set[ReconFlag] = set()
        if any(a.amount < 0 for a in mine):
            flags.add(ReconFlag.REVERSAL)
        if any(credit_dates.get(a.credit_id, period.end) < period.end for a in mine):
            flags.add(ReconFlag.EARLY_CREDIT)
        due = period.end + timedelta(days=payment_terms_days)
        ordered_flags = tuple(sorted(flags))
        if engine_needs_review or expected is None:
            return ReconItem(
                agreement_id,
                period.start,
                period.end,
                None,
                received,
                None,
                None,
                ReconStatus.NEEDS_REVIEW,
                due,
                ordered_flags,
            )
        variance = received - expected
        tol = tolerance.for_expected(expected)
        status = _status(expected, received, variance, tol, today, due)
        return ReconItem(
            agreement_id,
            period.start,
            period.end,
            expected,
            received,
            variance,
            tol,
            status,
            due,
            ordered_flags,
        )


def _status(e: Decimal, c: Decimal, v: Decimal, t: Decimal, today: date, due: date) -> ReconStatus:
    if e == 0 and c == 0:
        return ReconStatus.NOT_EARNED
    if abs(v) <= t:
        return ReconStatus.MATCHED
    if v > t:
        return ReconStatus.OVERPAID
    # v < -t
    if today <= due:
        return ReconStatus.PENDING
    if c == 0:
        return ReconStatus.MISSING
    # c > 0, or c < 0 after reversals: money was received and is short (ADR 0010).
    return ReconStatus.SHORT_PAID


# --------------------------------------------------------------------------- matching

_SEP = re.compile(r"[\s\-_/.]+")


def _norm(text: str) -> str:
    return _SEP.sub("", text.strip().upper())


def _label_variants(label: str) -> set[str]:
    """'2026-Q1' → {'2026Q1', 'Q12026'}; same for H halves; months/years unchanged."""
    base = _norm(label)
    out = {base}
    m = re.fullmatch(r"(FY)?(\d{4})([QH]\d)", base)
    if m:
        fy, year, part = m.group(1) or "", m.group(2), m.group(3)
        out.add(f"{part}{fy}{year}")
    return out


def _ref_norm(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip().casefold()
    return cleaned or None


def auto_match(
    credits: Sequence[Credit], targets: Sequence[MatchTarget]
) -> tuple[list[Allocation], list[Credit]]:
    """Deterministic auto-match: agreement reference AND an unambiguous period.

    Returns (allocations, credits left unmatched). Each matched credit is
    allocated in full to exactly one agreement-period.
    """
    allocations: list[Allocation] = []
    unmatched: list[Credit] = []
    for credit in sorted(credits, key=lambda c: c.credit_id):
        ref = _ref_norm(credit.agreement_reference)
        candidates = [
            t
            for t in targets
            if ref is not None
            and t.supplier_id == credit.supplier_id
            and _ref_norm(t.external_reference) == ref
        ]
        hits: list[MatchTarget] = []
        if credit.period_start is not None and credit.period_end is not None:
            hits = [
                t
                for t in candidates
                if t.period.start == credit.period_start and t.period.end == credit.period_end
            ]
        elif credit.period_label:
            wanted = _norm(credit.period_label)
            hits = [
                t
                for t in candidates
                if t.period.label and wanted in _label_variants(t.period.label)
            ]
        unique = {(t.agreement_id, t.period.start, t.period.end) for t in hits}
        if len(unique) == 1:
            t = hits[0]
            allocations.append(
                Allocation(
                    credit.credit_id,
                    t.agreement_id,
                    t.period.start,
                    t.period.end,
                    credit.amount,
                    "auto",
                )
            )
        else:
            unmatched.append(credit)
    return allocations, unmatched


@dataclass(frozen=True, slots=True)
class Outstanding:
    agreement_id: str
    supplier_id: str
    period: Period
    outstanding: Decimal
    """E − C for the agreement-period (positive means money still expected)."""
    payment_terms_days: int


@dataclass(frozen=True, slots=True)
class Suggestion:
    credit_id: str
    agreement_id: str
    period_start: date
    period_end: date
    amount_difference: Decimal
    explanation: str


def suggest(
    credit: Credit,
    outstanding: Sequence[Outstanding],
    tolerance: Tolerance,
    window_days: int = DEFAULT_SUGGESTION_WINDOW_DAYS,
) -> list[Suggestion]:
    """Suggestions are never auto-applied (SPEC §4.7.1 rule 2)."""
    out: list[Suggestion] = []
    with localcontext(engine_context()):
        for o in outstanding:
            if o.supplier_id != credit.supplier_id or o.outstanding <= 0:
                continue
            latest = o.period.end + timedelta(days=o.payment_terms_days + window_days)
            if not o.period.end <= credit.credit_date <= latest:
                continue
            diff = credit.amount - o.outstanding
            tol = tolerance.for_expected(o.outstanding)
            if abs(diff) > tol:
                continue
            explanation = (
                f"Same supplier; credit {credit.amount} is within {tol} of the {o.outstanding} "
                f"still expected (difference {diff}); credit date {credit.credit_date} is between "
                f"period end {o.period.end} and {latest} (payment terms "
                f"{o.payment_terms_days} days + {window_days} days)."
            )
            out.append(
                Suggestion(
                    credit.credit_id,
                    o.agreement_id,
                    o.period.start,
                    o.period.end,
                    diff,
                    explanation,
                )
            )
    out.sort(key=lambda s: (abs(s.amount_difference), s.period_start, s.agreement_id))
    return out


def allocation_remainder(credit: Credit, allocations: Sequence[Allocation]) -> Decimal:
    """Validates a manual split and returns the unallocated remainder.

    Positive credits: each allocation > 0 and the sum ≤ credit amount.
    Negative credits (reversals): each allocation < 0 and the sum ≥ credit amount.
    """
    with localcontext(engine_context()):
        mine = [a for a in allocations if a.credit_id == credit.credit_id]
        total = sum((a.amount for a in mine), ZERO)
        if credit.amount >= 0:
            if any(a.amount <= 0 for a in mine):
                raise EngineInputError("allocations of a positive credit must be positive")
            if total > credit.amount:
                raise EngineInputError("allocations exceed the credit amount")
        else:
            if any(a.amount >= 0 for a in mine):
                raise EngineInputError("allocations of a reversal must be negative")
            if total < credit.amount:
                raise EngineInputError("allocations exceed the reversal amount")
        return credit.amount - total
