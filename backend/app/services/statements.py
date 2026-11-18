"""Supplier statement compare (v1.2 Phase 22).

Each statement line says what the supplier calculated for one agreement-period. It is compared
with our latest calculated result for the same agreement and the same *full* period (all windows
of a split period are summed). We never guess: a line whose agreement is only suggested, or whose
period has no result, is shown as such and not compared.

Difference = ours − theirs. Positive means the supplier's statement is short.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.csv_safe import csv_string
from app.core.errors import AppError, not_found
from app.db.models.business import Agreement, StatementLineRow, Supplier
from app.db.models.identity import Tenant
from app.db.models.runs import PeriodResultRow
from app.services import group_payouts as groups
from app.services import runs as run_svc
from app.services.audit import record

CENT = Decimal("0.01")

AGREES = "agrees"
PURCHASES_DIFFER = "purchases_differ"
RATE_OR_TIER_DIFFERS = "rate_or_tier_differs"
NOT_CALCULATED = "not_calculated"
NEEDS_REVIEW = "needs_review"
UNCONFIRMED = "unconfirmed"
UNMATCHED = "unmatched"

REASONS = {
    AGREES: "Agrees within your tolerance.",
    PURCHASES_DIFFER: "The supplier counted different purchases than we did.",
    RATE_OR_TIER_DIFFERS: "Same purchases (or none stated), different rebate: check the rate or tier applied.",
    NOT_CALCULATED: "No calculated result for this agreement and period. Run a calculation, or check the period dates.",
    NEEDS_REVIEW: "Our calculation needs review, so it is not compared.",
    UNCONFIRMED: "Agreement suggested because it is the supplier's only one. Confirm it to compare.",
    UNMATCHED: "No agreement assigned. Choose the agreement this line belongs to.",
}


@dataclass(frozen=True)
class Comparison:
    line: StatementLineRow
    supplier_name: str
    agreement_name: str | None
    status: str
    ours: Decimal | None
    our_measure: Decimal | None
    theirs: Decimal
    difference: Decimal | None
    result_ids: tuple[uuid.UUID, ...]

    @property
    def reason(self) -> str:
        return REASONS[self.status]


def _results_by_period(
    db: Session, tenant_id: uuid.UUID, agreement_ids: set[uuid.UUID]
) -> dict[tuple[uuid.UUID, date, date], list[PeriodResultRow]]:
    out: dict[tuple[uuid.UUID, date, date], list[PeriodResultRow]] = {}
    if not agreement_ids:
        return out
    q = run_svc.latest_results_query(tenant_id).where(
        PeriodResultRow.agreement_id.in_(agreement_ids)
    )
    for r in db.execute(q).scalars():
        out.setdefault((r.agreement_id, r.full_period_start, r.full_period_end), []).append(r)
    return out


def compare_line(
    line: StatementLineRow,
    results: list[PeriodResultRow],
    tolerance: Any,
    group_fee: Decimal | None = None,
) -> tuple[str, Decimal | None, Decimal | None, Decimal | None]:
    """Pure decision for one line: (status, ours, our measure, difference).

    ``group_fee`` is set when the statement comes from the buying group that pays the program:
    ours is then what the group owes, net of its fee (as in reconciliation)."""
    if line.agreement_id is None or line.match_status == "unmatched":
        return UNMATCHED, None, None, None
    if line.match_status == "suggested":
        return UNCONFIRMED, None, None, None
    if not results:
        return NOT_CALCULATED, None, None, None
    if any(r.expected is None or "NEEDS_REVIEW" in r.statuses for r in results):
        return NEEDS_REVIEW, None, None, None
    gross = sum((r.expected or Decimal(0) for r in results), Decimal(0)).quantize(CENT)
    ours = groups.net_expected(gross, group_fee)
    assert ours is not None
    measure = sum((r.measure for r in results), Decimal(0)).quantize(CENT)
    theirs = line.supplier_rebate.quantize(CENT)
    diff = ours - theirs
    if abs(diff) <= tolerance.for_expected(ours):
        return AGREES, ours, measure, diff
    if line.supplier_measure is not None and line.supplier_measure.quantize(CENT) != measure:
        return PURCHASES_DIFFER, ours, measure, diff
    return RATE_OR_TIER_DIFFERS, ours, measure, diff


def compare(
    db: Session,
    tenant: Tenant,
    *,
    supplier_id: uuid.UUID | None = None,
    agreement_id: uuid.UUID | None = None,
    period: tuple[date, date] | None = None,
) -> list[Comparison]:
    q = select(StatementLineRow).where(
        StatementLineRow.tenant_id == tenant.id, StatementLineRow.voided.is_(False)
    )
    if supplier_id:
        q = q.where(StatementLineRow.supplier_id == supplier_id)
    if agreement_id:
        q = q.where(StatementLineRow.agreement_id == agreement_id)
    if period:
        q = q.where(
            StatementLineRow.period_start == period[0], StatementLineRow.period_end == period[1]
        )
    lines = list(db.execute(q).scalars())
    if not lines:
        return []
    agreement_ids = {ln.agreement_id for ln in lines if ln.agreement_id}
    results = _results_by_period(db, tenant.id, agreement_ids)
    agreement_rows = {
        a.id: a
        for a in db.execute(
            select(Agreement).where(
                Agreement.tenant_id == tenant.id, Agreement.id.in_(agreement_ids)
            )
        ).scalars()
    }
    names = {aid: a.name for aid, a in agreement_rows.items()}
    group_fees = groups.fees(db, tenant.id)
    supplier_names = {
        s.id: s.name
        for s in db.execute(
            select(Supplier).where(
                Supplier.tenant_id == tenant.id,
                Supplier.id.in_({ln.supplier_id for ln in lines}),
            )
        ).scalars()
    }
    tolerance = run_svc.tolerance_for(tenant)
    out = []
    for ln in lines:
        rs = (
            results.get((ln.agreement_id, ln.period_start, ln.period_end), [])
            if ln.agreement_id
            else []
        )
        a = agreement_rows.get(ln.agreement_id) if ln.agreement_id else None
        fee = (
            groups.fee_for(a, group_fees)
            if a is not None and a.paid_via_group_id == ln.supplier_id
            else None
        )
        status, ours, measure, diff = compare_line(ln, rs, tolerance, fee)
        out.append(
            Comparison(
                line=ln,
                supplier_name=supplier_names.get(ln.supplier_id, ""),
                agreement_name=names.get(ln.agreement_id) if ln.agreement_id else None,
                status=status,
                ours=ours,
                our_measure=measure,
                theirs=ln.supplier_rebate.quantize(CENT),
                difference=diff,
                result_ids=tuple(r.id for r in rs),
            )
        )
    out.sort(key=lambda c: (c.supplier_name, c.agreement_name or "", c.line.period_start))
    return out


def assign(
    db: Session, ctx: Any, line_id: uuid.UUID, agreement_id: uuid.UUID | None
) -> StatementLineRow:
    """Confirm or choose the agreement for a line, or clear it (back to unmatched)."""
    line = db.execute(
        select(StatementLineRow).where(
            StatementLineRow.id == line_id,
            StatementLineRow.tenant_id == ctx.tenant_uuid,
            StatementLineRow.voided.is_(False),
        )
    ).scalar_one_or_none()
    if line is None:
        raise not_found("Statement line")
    if agreement_id is not None:
        a = db.execute(
            select(Agreement).where(
                Agreement.id == agreement_id, Agreement.tenant_id == ctx.tenant_uuid
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Agreement")
        if line.supplier_id not in (a.supplier_id, a.paid_via_group_id):
            raise AppError(
                422,
                "AGREEMENT_SUPPLIER_MISMATCH",
                "Different supplier",
                "Choose an agreement of the supplier that sent the statement, or one it pays through.",
            )
        line.agreement_id, line.match_status = a.id, "confirmed"
    else:
        line.agreement_id, line.match_status = None, "unmatched"
    line.matched_by = ctx.user.id
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="statement_line.assigned",
        object_type="statement_line",
        object_id=line.id,
        summary={"agreement_id": str(agreement_id) if agreement_id else None},
    )
    return line


def to_csv(rows: list[Comparison]) -> str:
    """Differences to send to the supplier (formula-safe via csv_string)."""
    return csv_string(
        [
            "Supplier",
            "Agreement",
            "Statement reference",
            "Period start",
            "Period end",
            "Their purchases",
            "Our purchases",
            "Their rebate",
            "Our rebate",
            "Difference (ours - theirs)",
            "Status",
        ],
        (
            [
                c.supplier_name,
                c.agreement_name or "",
                c.line.statement_reference or "",
                c.line.period_start.isoformat(),
                c.line.period_end.isoformat(),
                "" if c.line.supplier_measure is None else f"{c.line.supplier_measure:.2f}",
                "" if c.our_measure is None else f"{c.our_measure:.2f}",
                f"{c.theirs:.2f}",
                "" if c.ours is None else f"{c.ours:.2f}",
                "" if c.difference is None else f"{c.difference:.2f}",
                c.reason,
            ]
            for c in rows
        ),
    )
