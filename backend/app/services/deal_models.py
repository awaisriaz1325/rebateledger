"""Deal modelling: compare proposed terms against real past purchases (v1.1 Phase 13).

Stateless and read-only. Each option's terms are run through the same pure engine as a
real calculation, period by period, over a historical window of the supplier's imported
purchase lines. Nothing is saved; results are labelled estimates in the UI.

Sensitivity ("what if spend in the window had been x% higher") scales the quantity and
amount of the lines whose basis date falls inside the window, then recalculates. Lines
before the window (prior-period baselines for growth rebates) are never scaled, so growth
is measured against the real baseline.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.engine.calculate import PeriodResult, calculate
from app.engine.models import CalcOptions, PeriodType, PurchaseLine, Status, VersionSnapshot
from app.engine.periods import periods_overlapping
from app.services import agreements, suppliers
from app.services.agreement_terms import VersionTermsIn, summarize, to_snapshot

MAX_OPTIONS = 4
MAX_WINDOW_DAYS = 731  # 24 months
SENSITIVITY = (Decimal("0.8"), Decimal("0.9"), Decimal("1.1"), Decimal("1.2"))
RATE_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class OptionResult:
    label: str
    summary: str
    periods: list[PeriodResult]
    total_expected: Decimal
    total_spend: Decimal
    complete: bool
    effective_rate: Decimal | None
    sensitivity: list[tuple[Decimal, Decimal, bool]]


def _check_window(start: date, end: date) -> None:
    if end < start:
        raise AppError(422, "WINDOW_INVALID", "Invalid window", "The window ends before it starts.")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise AppError(
            422, "WINDOW_INVALID", "Window too long", "Model at most 24 months of history."
        )


def _snapshot(
    terms: VersionTermsIn, start: date, end: date, ctx: Any, supplier_id: str
) -> VersionSnapshot:
    if terms.period_type is PeriodType.CUSTOM:
        raise AppError(
            422,
            "CUSTOM_PERIODS_NOT_SUPPORTED",
            "Custom periods cannot be modelled",
            "Use monthly, quarterly, half-yearly or annual periods to model a deal.",
        )
    # The proposal's own dates are in the future; for modelling it is "effective" across
    # the historical window.
    modelled = terms.model_copy(update={"effective_from": start, "effective_to": end})
    assert ctx.tenant is not None
    ids = suppliers.line_supplier_ids(ctx.db, ctx.tenant_uuid, uuid.UUID(supplier_id))
    members = frozenset(str(i) for i in ids) if ids != [uuid.UUID(supplier_id)] else frozenset()
    return to_snapshot(
        modelled,
        member_supplier_ids=members,
        agreement_id="model",
        version_id="model",
        version_no=1,
        supplier_id=supplier_id,
        fiscal_start=ctx.tenant.fiscal_year_start_month,
    )


def _whole_periods(snap: VersionSnapshot, start: date, end: date) -> list[Any]:
    periods = [
        p
        for p in periods_overlapping(snap.period_type, snap.fiscal_year_start_month, start, end)
        if p.start >= start and p.end <= end
    ]
    if not periods:
        raise AppError(
            422,
            "WINDOW_TOO_SHORT",
            "No whole period in the window",
            "The window must contain at least one whole period of every option.",
        )
    return periods


def _scaled(
    lines: list[PurchaseLine], snap: VersionSnapshot, start: date, end: date, f: Decimal
) -> list[PurchaseLine]:
    basis = snap.date_basis.value
    out = []
    for line in lines:
        d: date | None = getattr(line, basis)
        if d is not None and start <= d <= end:
            line = dataclasses.replace(line, quantity=line.quantity * f, amount=line.amount * f)
        out.append(line)
    return out


def _run(
    snap: VersionSnapshot, periods: list[Any], lines: list[PurchaseLine], coverage: date | None
) -> list[PeriodResult]:
    return [
        calculate(snap, p, lines, [], CalcOptions(data_coverage_start=coverage, full_period=p))
        for p in periods
    ]


def _total(results: list[PeriodResult]) -> tuple[Decimal, bool]:
    total = sum((r.expected for r in results if r.expected is not None), Decimal("0"))
    complete = all(
        r.expected is not None and Status.NEEDS_REVIEW not in r.statuses for r in results
    )
    return total, complete


def evaluate(
    db: Session,
    ctx: Any,
    *,
    supplier_id: uuid.UUID,
    start: date,
    end: date,
    options: list[tuple[str, VersionTermsIn]],
) -> list[OptionResult]:
    suppliers.get(db, ctx.tenant_uuid, supplier_id)  # 404 for other tenants
    _check_window(start, end)
    if not 1 <= len(options) <= MAX_OPTIONS:
        raise AppError(422, "OPTIONS_INVALID", "Invalid options", "Compare one to four options.")

    prepared = []
    for label, terms in options:
        snap = _snapshot(terms, start, end, ctx, str(supplier_id))
        prepared.append((label, snap, _whole_periods(snap, start, end)))

    look_back = min(agreements.lines_needed_from(s, ps[0]) for _, s, ps in prepared)
    lines = agreements.purchase_lines(db, ctx.tenant_uuid, supplier_id, look_back, end)
    coverage = agreements.data_coverage_start(db, ctx.tenant_uuid, supplier_id)

    out = []
    for label, snap, periods in prepared:
        results = _run(snap, periods, lines, coverage)
        total, complete = _total(results)
        spend = sum((r.spend for r in results), Decimal("0"))
        rate = (total / spend).quantize(RATE_PLACES, ROUND_HALF_UP) if spend > 0 else None
        sens = []
        for f in SENSITIVITY:
            t, c = _total(_run(snap, periods, _scaled(lines, snap, start, end, f), coverage))
            sens.append((f, t, c))
        out.append(
            OptionResult(
                label=label,
                summary=summarize(snap),
                periods=results,
                total_expected=total,
                total_spend=spend,
                complete=complete,
                effective_rate=rate,
                sensitivity=sens,
            )
        )
    return out
