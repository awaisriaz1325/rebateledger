"""Month-end accrual journal export (v1.1 Phase 15, ADR 0017 §2). A file, never GL posting.

Method: reversing. For a month-end closing date D the journal books, per agreement period,
the rebate receivable still outstanding at D:

    outstanding = earned to D − credits received (allocated, credit date ≤ D)

- Closed periods (full period ended on or before D): earned = the latest successful
  calculation run's expected amount.
- The open period containing D: earned = the engine's earned-to-date over [period start, D]
  at the tier reached so far (an ESTIMATE), recalculated here, not taken from a run.
- Periods that need review, have no amount, or whose result is stale are left out and listed.

Each line is Dr rebate receivable / Cr offset (rebate income or cost of goods). A negative
outstanding (overpaid) swaps the sides. Every entry is reversed on D + 1 (the first day of
the next month). This keeps the receivable right only if supplier credits are booked to the
offset account when received; the export screen states that requirement.
"""

from __future__ import annotations

import calendar
import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.csv_safe import csv_string
from app.core.errors import AppError
from app.db.models.business import (
    AccrualExport,
    Agreement,
    AgreementVersion,
    Supplier,
    VersionStatus,
)
from app.db.models.identity import Tenant
from app.engine.calculate import calculate
from app.engine.models import CalcOptions, Period
from app.engine.periods import clip, periods_overlapping
from app.services import agreements as agreement_svc
from app.services import runs as run_svc
from app.services.agreement_terms import snapshot_for
from app.services.audit import record

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
FORMATS = ("generic", "qbo")
LOOK_BACK_MONTHS = 24


@dataclass(frozen=True)
class AccrualLine:
    agreement_id: uuid.UUID
    agreement_name: str
    supplier_name: str
    period_start: date
    period_end: date
    period_label: str
    basis: str  # "closed" | "open_estimate"
    earned: Decimal
    received: Decimal

    @property
    def outstanding(self) -> Decimal:
        return self.earned - self.received

    @property
    def key(self) -> str:
        return f"{self.agreement_id}:{self.period_start}:{self.period_end}"


@dataclass(frozen=True)
class Excluded:
    agreement_name: str
    supplier_name: str
    period_start: date
    period_end: date
    reason: str


@dataclass
class Journal:
    closing_date: date
    reversal_date: date
    lines: list[AccrualLine] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    not_calculated: list[Excluded] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((ln.outstanding for ln in self.lines), ZERO)


def _check_closing(d: date) -> None:
    if d.day != calendar.monthrange(d.year, d.month)[1]:
        raise AppError(
            422,
            "CLOSING_DATE_NOT_MONTH_END",
            "Choose a month end",
            "The closing date must be the last day of a month.",
        )


def _received(
    db: Session, tenant_id: uuid.UUID, agreement_ids: list[uuid.UUID], closing: date
) -> dict[tuple[uuid.UUID, date, date], Decimal]:
    allocs = run_svc.active_allocations(db, tenant_id, agreement_ids)
    dates = run_svc._credit_dates(db, tenant_id, {a.credit_id for a in allocs})
    out: dict[tuple[uuid.UUID, date, date], Decimal] = defaultdict(lambda: ZERO)
    for a in allocs:
        credit_date = dates.get(str(a.credit_id))
        if credit_date is not None and credit_date <= closing:
            out[(a.agreement_id, a.period_start, a.period_end)] += a.amount
    return out


def build(db: Session, tenant: Tenant, closing: date) -> Journal:
    _check_closing(closing)
    journal = Journal(closing, closing + timedelta(days=1))
    agreements = {
        a.id: a
        for a in db.execute(select(Agreement).where(Agreement.tenant_id == tenant.id)).scalars()
    }
    suppliers = {
        s.id: s.name
        for s in db.execute(select(Supplier).where(Supplier.tenant_id == tenant.id)).scalars()
    }
    received = _received(db, tenant.id, list(agreements), closing)

    # Closed periods: latest successful run.
    calculated: set[tuple[uuid.UUID, date, date]] = set()
    for r in db.execute(run_svc.latest_results_query(tenant.id)).scalars():
        if r.full_period_end > closing:
            continue
        calculated.add((r.agreement_id, r.full_period_start, r.full_period_end))
        a = agreements[r.agreement_id]
        sup = suppliers.get(r.supplier_id, "")
        reason = None
        if r.expected is None or "NEEDS_REVIEW" in r.statuses:
            reason = "Needs review in the calculation run"
        elif r.stale_at is not None:
            reason = "Data changed since the last run: run the calculation again"
        if reason:
            journal.excluded.append(Excluded(a.name, sup, r.period_start, r.period_end, reason))
            continue
        assert r.expected is not None
        line = AccrualLine(
            a.id,
            a.name,
            sup,
            r.period_start,
            r.period_end,
            r.period_label,
            "closed",
            r.expected.quantize(CENT),
            received[(a.id, r.period_start, r.period_end)].quantize(CENT),
        )
        if line.outstanding != 0:
            journal.lines.append(line)

    # The open period containing the closing date, and closed periods never calculated.
    versions = db.execute(
        select(AgreementVersion, Agreement)
        .join(Agreement, Agreement.id == AgreementVersion.agreement_id)
        .where(
            Agreement.tenant_id == tenant.id,
            Agreement.status == "active",
            AgreementVersion.status == VersionStatus.ACTIVE.value,
        )
    ).all()
    earliest = date(closing.year - LOOK_BACK_MONTHS // 12, closing.month, 1)
    for version, a in versions:
        snap = snapshot_for(db, version, a)
        eff = snap.effective_period
        sup = suppliers.get(a.supplier_id, "")
        range_start, range_end = max(eff.start, earliest), min(eff.end, closing)
        if range_end < range_start:
            continue  # the agreement starts after the closing date
        for full in periods_overlapping(
            snap.period_type,
            snap.fiscal_year_start_month,
            range_start,
            range_end,
            snap.custom_periods,
        ):
            if full.end <= closing:
                if (a.id, full.start, full.end) not in calculated:
                    journal.not_calculated.append(
                        Excluded(a.name, sup, full.start, full.end, "No calculation run yet")
                    )
                continue
            window = clip(full, eff.start, min(eff.end, closing))
            if window is None:
                continue
            full_period = Period(full.start, full.end, full.label)
            lines = agreement_svc.purchase_lines(
                db,
                tenant.id,
                a.supplier_id,
                agreement_svc.lines_needed_from(snap, full_period),
                closing,
            )
            res = calculate(
                snap,
                window,
                lines,
                agreement_svc.baselines(db, tenant.id, a.id),
                CalcOptions(
                    data_coverage_start=agreement_svc.data_coverage_start(
                        db, tenant.id, a.supplier_id
                    ),
                    full_period=full_period,
                ),
            )
            if res.expected is None or res.needs_review:
                journal.excluded.append(
                    Excluded(a.name, sup, window.start, window.end, "Needs review (estimate)")
                )
                continue
            got = sum(
                (v for (aid, ps, _pe), v in received.items() if aid == a.id and ps == window.start),
                ZERO,
            )
            line = AccrualLine(
                a.id,
                a.name,
                sup,
                window.start,
                full.end,
                full.label,
                "open_estimate",
                res.expected.quantize(CENT),
                got.quantize(CENT),
            )
            if line.outstanding != 0:
                journal.lines.append(line)

    journal.lines.sort(key=lambda ln: (ln.supplier_name, ln.agreement_name, ln.period_start))
    return journal


# --------------------------------------------------------------------------- rendering


def _rows(
    journal: Journal, receivable: str, offset: str
) -> list[tuple[str, date, str, Decimal, Decimal, AccrualLine]]:
    ref = f"ACC-{journal.closing_date:%Y%m}"
    rows = []
    for jno, when, sign in (
        (ref, journal.closing_date, 1),
        (f"{ref}-R", journal.reversal_date, -1),
    ):
        for ln in journal.lines:
            amount = ln.outstanding * sign
            dr_acct, cr_acct = (receivable, offset) if amount > 0 else (offset, receivable)
            value = abs(amount)
            rows.append((jno, when, dr_acct, value, ZERO, ln))
            rows.append((jno, when, cr_acct, ZERO, value, ln))
    debits = sum((r[3] for r in rows), ZERO)
    credits = sum((r[4] for r in rows), ZERO)
    if debits != credits:  # pragma: no cover - impossible by construction; never ship unbalanced
        raise AppError(500, "JOURNAL_UNBALANCED", "Journal does not balance", "Contact support.")
    return rows


def _description(ln: AccrualLine, reversal: bool) -> str:
    kind = "Reverse rebate accrual" if reversal else "Rebate accrual"
    est = " (estimate to date)" if ln.basis == "open_estimate" else ""
    return f"{kind}: {ln.supplier_name} — {ln.agreement_name} {ln.period_label or ln.period_start}{est}"


def render(journal: Journal, fmt: str, receivable: str, offset: str) -> str:
    rows = _rows(journal, receivable, offset)
    if fmt == "generic":
        return csv_string(
            [
                "Journal",
                "Date",
                "Account",
                "Debit",
                "Credit",
                "Description",
                "Supplier",
                "Agreement",
                "Period start",
                "Period end",
            ],
            (
                [
                    jno,
                    when.isoformat(),
                    acct,
                    f"{dr:.2f}" if dr else "",
                    f"{cr:.2f}" if cr else "",
                    _description(ln, jno.endswith("-R")),
                    ln.supplier_name,
                    ln.agreement_name,
                    ln.period_start.isoformat(),
                    ln.period_end.isoformat(),
                ]
                for jno, when, acct, dr, cr, ln in rows
            ),
        )
    # UNVERIFIED: QuickBooks Online journal-entry import column names, from memory of its
    # import template; confirm against a real QBO import before relying on it.
    return csv_string(
        ["JournalNo", "JournalDate", "AccountName", "Debits", "Credits", "Description", "Name"],
        (
            [
                jno,
                f"{when:%m/%d/%Y}",
                acct,
                f"{dr:.2f}" if dr else "",
                f"{cr:.2f}" if cr else "",
                _description(ln, jno.endswith("-R")),
                ln.supplier_name,
            ]
            for jno, when, acct, dr, cr, ln in rows
        ),
    )


# --------------------------------------------------------------------------- export


def _snapshot(journal: Journal) -> list[dict[str, Any]]:
    return [
        {
            "key": ln.key,
            "agreement": ln.agreement_name,
            "supplier": ln.supplier_name,
            "period_start": ln.period_start.isoformat(),
            "amount": str(ln.outstanding),
        }
        for ln in journal.lines
    ]


def previous(db: Session, tenant_id: uuid.UUID, closing: date) -> AccrualExport | None:
    return (
        db.execute(
            select(AccrualExport)
            .where(AccrualExport.tenant_id == tenant_id, AccrualExport.closing_date == closing)
            .order_by(AccrualExport.created_at.desc())
        )
        .scalars()
        .first()
    )


def changes(prev: AccrualExport | None, journal: Journal) -> list[dict[str, Any]]:
    """What differs from the last export for the same closing date."""
    if prev is None:
        return []
    before = {x["key"]: x for x in prev.lines}
    now = {x["key"]: x for x in _snapshot(journal)}
    out = []
    for key in sorted(before.keys() | now.keys()):
        b, n = before.get(key), now.get(key)
        if b and n and b["amount"] == n["amount"]:
            continue
        ref = n or b
        assert ref is not None
        out.append(
            {
                "agreement": ref["agreement"],
                "supplier": ref["supplier"],
                "period_start": ref["period_start"],
                "before": b["amount"] if b else None,
                "after": n["amount"] if n else None,
            }
        )
    return out


def export(db: Session, ctx: Any, closing: date, fmt: str) -> tuple[AccrualExport, str]:
    tenant: Tenant = ctx.tenant
    if not tenant.gl_receivable_account or not tenant.gl_offset_account:
        raise AppError(
            422,
            "GL_ACCOUNTS_MISSING",
            "Set your GL accounts first",
            "Add the rebate receivable and offset account codes under Settings → Accounting.",
        )
    if fmt not in FORMATS:
        raise AppError(422, "FORMAT_INVALID", "Unknown format", "Use generic or qbo.")
    journal = build(db, tenant, closing)
    if not journal.lines:
        raise AppError(
            422, "NOTHING_TO_ACCRUE", "Nothing to export", "No outstanding rebate at this date."
        )
    body = render(journal, fmt, tenant.gl_receivable_account, tenant.gl_offset_account)
    digest = hashlib.sha256(body.encode()).hexdigest()
    row = AccrualExport(
        tenant_id=tenant.id,
        closing_date=closing,
        format=fmt,
        total=journal.total,
        line_count=len(journal.lines),
        file_hash=digest,
        lines=_snapshot(journal),
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    record(
        db,
        tenant_id=tenant.id,
        actor=ctx.actor,
        action="accrual.exported",
        object_type="accrual_export",
        object_id=row.id,
        summary={
            "closing_date": closing.isoformat(),
            "format": fmt,
            "total": str(journal.total),
            "lines": len(journal.lines),
            "sha256": digest,
        },
    )
    return row, body
