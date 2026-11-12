"""Live reconciliation, credit allocation and unmatched credits (SPEC §4.7.1–4.7.2).

Statuses are computed from the latest run's (frozen) results + current allocations
+ today in the tenant timezone, so PENDING becomes MISSING/SHORT_PAID the day after
the due date without a re-run. Tolerances come from the run's snapshot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import today_in, utcnow
from app.core.errors import AppError, conflict, not_found
from app.db.models.business import Agreement, CreditLineRow, Supplier
from app.db.models.identity import Tenant
from app.db.models.runs import CalculationRun, CreditAllocation, PeriodResultRow
from app.engine.models import EngineInputError, Period
from app.engine.reconcile import (
    Outstanding,
    ReconItem,
    ReconStatus,
    Suggestion,
    Tolerance,
    allocation_remainder,
    reconcile_item,
    suggest,
)
from app.services import runs as run_svc
from app.services.audit import record
from app.services.staleness import mark_stale_for_period


@dataclass(frozen=True)
class LiveItem:
    result: PeriodResultRow
    item: ReconItem
    agreement_name: str
    supplier_name: str
    run_number: int


def _tolerance(run: CalculationRun, tenant: Tenant) -> Tolerance:
    snap = run.snapshot.get("tolerance")
    if snap:
        return Tolerance(Decimal(snap["abs"]), Decimal(snap["pct"]))
    return run_svc.tolerance_for(tenant)


def live_items(
    db: Session,
    tenant: Tenant,
    *,
    supplier_id: uuid.UUID | None = None,
    agreement_id: uuid.UUID | None = None,
    today: date | None = None,
) -> list[LiveItem]:
    q = run_svc.latest_results_query(tenant.id)
    if supplier_id:
        q = q.where(PeriodResultRow.supplier_id == supplier_id)
    if agreement_id:
        q = q.where(PeriodResultRow.agreement_id == agreement_id)
    results = list(db.execute(q).scalars())
    if not results:
        return []
    runs = {
        r.id: r
        for r in db.execute(
            select(CalculationRun).where(CalculationRun.id.in_({r.run_id for r in results}))
        ).scalars()
    }
    agreements = {
        a.id: a
        for a in db.execute(
            select(Agreement).where(
                Agreement.tenant_id == tenant.id,
                Agreement.id.in_({r.agreement_id for r in results}),
            )
        ).scalars()
    }
    suppliers = {
        s.id: s
        for s in db.execute(
            select(Supplier).where(
                Supplier.tenant_id == tenant.id, Supplier.id.in_({r.supplier_id for r in results})
            )
        ).scalars()
    }
    allocs = [
        run_svc.to_alloc(a) for a in run_svc.active_allocations(db, tenant.id, list(agreements))
    ]
    credit_dates = run_svc._credit_dates(db, tenant.id, {uuid.UUID(a.credit_id) for a in allocs})
    as_of = today or today_in(tenant.timezone)
    out = []
    for r in results:
        run = runs[r.run_id]
        item = reconcile_item(
            agreement_id=str(r.agreement_id),
            period=Period(r.period_start, r.period_end),
            expected=None if r.expected is None else r.expected.quantize(Decimal("0.01")),
            engine_needs_review="NEEDS_REVIEW" in r.statuses,
            allocations=allocs,
            credit_dates=credit_dates,
            payment_terms_days=r.payment_terms_days,
            today=as_of,
            tolerance=_tolerance(run, tenant),
        )
        out.append(
            LiveItem(
                r, item, agreements[r.agreement_id].name, suppliers[r.supplier_id].name, run.number
            )
        )
    out.sort(key=lambda li: (li.supplier_name, li.agreement_name, li.result.period_start))
    return out


DISCREPANCY = {ReconStatus.SHORT_PAID, ReconStatus.MISSING, ReconStatus.OVERPAID}


# --------------------------------------------------------------------------- credits


def get_credit(db: Session, tenant_id: uuid.UUID, credit_id: uuid.UUID) -> CreditLineRow:
    c = db.execute(
        select(CreditLineRow).where(
            CreditLineRow.id == credit_id, CreditLineRow.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if c is None:
        raise not_found("Credit")
    return c


def credit_allocations(
    db: Session, tenant_id: uuid.UUID, credit_id: uuid.UUID
) -> list[CreditAllocation]:
    return list(
        db.execute(
            select(CreditAllocation).where(
                CreditAllocation.tenant_id == tenant_id,
                CreditAllocation.credit_id == credit_id,
                CreditAllocation.reversed_at.is_(None),
            )
        ).scalars()
    )


def remainder(db: Session, credit: CreditLineRow) -> Decimal:
    allocs = [run_svc.to_alloc(a) for a in credit_allocations(db, credit.tenant_id, credit.id)]
    return allocation_remainder(run_svc.to_credit(credit), allocs)


def _target_exists(
    db: Session, tenant_id: uuid.UUID, agreement_id: uuid.UUID, start: date, end: date
) -> bool:
    q = run_svc.latest_results_query(tenant_id).where(
        PeriodResultRow.agreement_id == agreement_id,
        PeriodResultRow.period_start == start,
        PeriodResultRow.period_end == end,
    )
    return db.execute(q.limit(1)).first() is not None


def allocate(
    db: Session,
    ctx: Any,
    credit_id: uuid.UUID,
    parts: list[dict[str, Any]],
    *,
    method: str = "manual",
) -> list[CreditAllocation]:
    """Split one credit across agreement-periods; the sum may not exceed the credit (SPEC §4.7.1 rule 3)."""
    credit = get_credit(db, ctx.tenant_uuid, credit_id)
    if credit.voided:
        raise conflict("CREDIT_VOIDED", "This credit was voided with its import.")
    db.execute(select(CreditLineRow.id).where(CreditLineRow.id == credit.id).with_for_update())
    existing = [run_svc.to_alloc(a) for a in credit_allocations(db, ctx.tenant_uuid, credit.id)]
    new: list[CreditAllocation] = []
    proposed = list(existing)
    from app.engine.reconcile import Allocation

    for part in parts:
        agreement = db.execute(
            select(Agreement).where(
                Agreement.id == part["agreement_id"], Agreement.tenant_id == ctx.tenant_uuid
            )
        ).scalar_one_or_none()
        if agreement is None:
            raise not_found("Agreement")
        if agreement.supplier_id != credit.supplier_id:
            raise AppError(
                422,
                "SUPPLIER_MISMATCH",
                "Different supplier",
                "A credit can only be allocated to agreements of the same supplier.",
            )
        if not _target_exists(
            db, ctx.tenant_uuid, agreement.id, part["period_start"], part["period_end"]
        ):
            raise AppError(
                422,
                "PERIOD_NOT_CALCULATED",
                "Unknown period",
                "Allocate to a period that appears in the latest run of this agreement.",
            )
        proposed.append(
            Allocation(
                str(credit.id),
                str(agreement.id),
                part["period_start"],
                part["period_end"],
                part["amount"],
                method,
            )
        )
    try:
        allocation_remainder(run_svc.to_credit(credit), proposed)
    except EngineInputError as exc:
        raise AppError(
            422, "ALLOCATION_EXCEEDS_CREDIT", "Allocation not possible", str(exc).capitalize() + "."
        ) from None
    for part in parts:
        row = CreditAllocation(
            tenant_id=ctx.tenant_uuid,
            credit_id=credit.id,
            agreement_id=part["agreement_id"],
            period_start=part["period_start"],
            period_end=part["period_end"],
            amount=part["amount"],
            method=method,
            created_by=ctx.user.id,
        )
        db.add(row)
        new.append(row)
        mark_stale_for_period(
            db,
            ctx.tenant_uuid,
            part["agreement_id"],
            part["period_start"],
            part["period_end"],
            "credit allocation changed",
        )
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="allocation.created",
        object_type="credit",
        object_id=credit.id,
        summary={
            "parts": [
                {
                    "agreement_id": str(p["agreement_id"]),
                    "period_start": p["period_start"].isoformat(),
                    "amount": format(p["amount"], "f"),
                }
                for p in parts
            ],
            "method": method,
        },
    )
    return new


def reverse(db: Session, ctx: Any, allocation_id: uuid.UUID) -> CreditAllocation:
    a = db.execute(
        select(CreditAllocation).where(
            CreditAllocation.id == allocation_id, CreditAllocation.tenant_id == ctx.tenant_uuid
        )
    ).scalar_one_or_none()
    if a is None or a.reversed_at is not None:
        raise not_found("Allocation")
    if a.method == "recovery":
        raise conflict(
            "ALLOCATION_LINKED_TO_CLAIM",
            "This allocation records a claim recovery. Remove the recovery from the claim instead.",
        )
    a.reversed_at, a.reversed_by = utcnow(), ctx.user.id
    mark_stale_for_period(
        db,
        ctx.tenant_uuid,
        a.agreement_id,
        a.period_start,
        a.period_end,
        "credit allocation changed",
    )
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="allocation.reversed",
        object_type="credit",
        object_id=a.credit_id,
        summary={"allocation_id": str(a.id), "amount": format(a.amount, "f")},
    )
    return a


@dataclass(frozen=True)
class UnmatchedCredit:
    credit: CreditLineRow
    remainder: Decimal
    suggestions: tuple[Suggestion, ...]


def unmatched(
    db: Session, tenant: Tenant, supplier_id: uuid.UUID | None = None, limit: int = 500
) -> list[UnmatchedCredit]:
    """Credits with an unallocated remainder, newest first, at most ``limit``.

    Allocations are loaded in one query (not one per credit) and only credits whose
    active allocations do not already cover them are considered."""
    allocated = (
        select(CreditAllocation.credit_id, func.sum(CreditAllocation.amount).label("total"))
        .where(CreditAllocation.tenant_id == tenant.id, CreditAllocation.reversed_at.is_(None))
        .group_by(CreditAllocation.credit_id)
        .subquery()
    )
    q = (
        select(CreditLineRow)
        .outerjoin(allocated, allocated.c.credit_id == CreditLineRow.id)
        .where(
            CreditLineRow.tenant_id == tenant.id,
            CreditLineRow.voided.is_(False),
            func.coalesce(allocated.c.total, 0) != CreditLineRow.amount,
        )
    )
    if supplier_id:
        q = q.where(CreditLineRow.supplier_id == supplier_id)
    credits = list(
        db.execute(
            q.order_by(CreditLineRow.credit_date.desc(), CreditLineRow.id).limit(limit)
        ).scalars()
    )
    if not credits:
        return []
    by_credit: dict[uuid.UUID, list[CreditAllocation]] = {}
    for a in db.execute(
        select(CreditAllocation).where(
            CreditAllocation.tenant_id == tenant.id,
            CreditAllocation.reversed_at.is_(None),
            CreditAllocation.credit_id.in_([c.id for c in credits]),
        )
    ).scalars():
        by_credit.setdefault(a.credit_id, []).append(a)
    items = live_items(db, tenant, supplier_id=supplier_id)
    outstanding = [
        Outstanding(
            str(li.result.agreement_id),
            str(li.result.supplier_id),
            Period(li.result.period_start, li.result.period_end),
            li.item.expected - li.item.received,
            li.result.payment_terms_days,
        )
        for li in items
        if li.item.expected is not None
    ]
    tol = run_svc.tolerance_for(tenant)
    out = []
    for c in credits:
        rem = allocation_remainder(
            run_svc.to_credit(c), [run_svc.to_alloc(a) for a in by_credit.get(c.id, [])]
        )
        if rem != 0:
            out.append(
                UnmatchedCredit(c, rem, tuple(suggest(run_svc.to_credit(c), outstanding, tol)))
            )
    return out


def create_manual_credit(
    db: Session,
    ctx: Any,
    *,
    supplier_id: uuid.UUID,
    reference: str,
    credit_date: date,
    amount: Decimal,
    memo: str,
) -> CreditLineRow:
    """A credit entered by hand (with reference and date) — e.g. to record a recovery."""
    from app.services.suppliers import get as get_supplier

    get_supplier(db, ctx.tenant_uuid, supplier_id)
    dup = db.execute(
        select(CreditLineRow.id).where(
            CreditLineRow.tenant_id == ctx.tenant_uuid,
            CreditLineRow.supplier_id == supplier_id,
            CreditLineRow.credit_reference == reference,
            CreditLineRow.voided.is_(False),
        )
    ).first()
    if dup:
        raise conflict(
            "CREDIT_REFERENCE_EXISTS",
            "A credit with this reference already exists for the supplier. Link that credit instead.",
        )
    c = CreditLineRow(
        tenant_id=ctx.tenant_uuid,
        supplier_id=supplier_id,
        credit_reference=reference,
        credit_date=credit_date,
        amount=amount,
        memo=memo,
        entered_by=ctx.user.id,
    )
    db.add(c)
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="credit.entered",
        object_type="credit",
        object_id=c.id,
        summary={"amount": format(amount, "f")},
    )
    return c


def reverse_for_voided_credits(db: Session, ctx: Any, batch_id: uuid.UUID) -> int:
    """Voiding a credits import reverses allocations of its credits (marks periods stale)."""
    ids = select(CreditLineRow.id).where(
        CreditLineRow.tenant_id == ctx.tenant_uuid, CreditLineRow.batch_id == batch_id
    )
    allocs = list(
        db.execute(
            select(CreditAllocation).where(
                CreditAllocation.tenant_id == ctx.tenant_uuid,
                CreditAllocation.credit_id.in_(ids),
                CreditAllocation.reversed_at.is_(None),
            )
        ).scalars()
    )
    for a in allocs:
        a.reversed_at, a.reversed_by = utcnow(), ctx.user.id
        mark_stale_for_period(
            db,
            ctx.tenant_uuid,
            a.agreement_id,
            a.period_start,
            a.period_end,
            "a credit import was voided",
        )
    return len(allocs)
