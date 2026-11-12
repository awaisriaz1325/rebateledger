"""Reconciliation views, discrepancy queue, credits and allocations (SPEC §4.7.1–4.8)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select

from app.api.deps import Ctx, Requires
from app.api.schemas.common import DecimalStr, In, MoneyIn, Ok, Out, Page
from app.core.errors import AppError
from app.core.permissions import Permission
from app.db.models.business import CreditLineRow
from app.db.models.runs import TERMINAL_CLAIM, Claim, ClaimItem
from app.engine.reconcile import ReconStatus
from app.services import reconciliation as svc

router = APIRouter(prefix="/api/v1", tags=["reconciliation"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Allocate = Annotated[Ctx, Depends(Requires(Permission.RUN_RECONCILIATION, write=True))]


class ReconRow(Out):
    result_id: uuid.UUID
    run_number: int
    agreement_id: uuid.UUID
    agreement_name: str
    supplier_id: uuid.UUID
    supplier_name: str
    version_no: int
    period_start: date
    period_end: date
    period_label: str
    expected: DecimalStr | None
    received: DecimalStr
    variance: DecimalStr | None
    tolerance: DecimalStr | None
    status: str
    flags: list[str]
    engine_statuses: list[str]
    due_date: date
    days_past_due: int
    stale: bool
    stale_reason: str | None
    claim_id: uuid.UUID | None = None
    claim_number: int | None = None
    claim_assignee_id: uuid.UUID | None = None


def _rows(
    ctx: Ctx, supplier_id: uuid.UUID | None = None, agreement_id: uuid.UUID | None = None
) -> list[ReconRow]:
    assert ctx.tenant is not None
    from app.core.clock import today_in

    today = today_in(ctx.tenant.timezone)
    claims = {
        (a, p): (cid, num, assignee)
        for a, p, cid, num, assignee in ctx.db.execute(
            select(
                ClaimItem.agreement_id,
                ClaimItem.period_start,
                Claim.id,
                Claim.number,
                Claim.assignee_id,
            )
            .join(Claim, Claim.id == ClaimItem.claim_id)
            .where(
                Claim.tenant_id == ctx.tenant_uuid,
                Claim.status.not_in([s.value for s in TERMINAL_CLAIM]),
            )
        ).all()
    }
    out = []
    for li in svc.live_items(
        ctx.db, ctx.tenant, supplier_id=supplier_id, agreement_id=agreement_id, today=today
    ):
        r, it = li.result, li.item
        claim = claims.get((r.agreement_id, r.period_start))
        out.append(
            ReconRow(
                result_id=r.id,
                run_number=li.run_number,
                agreement_id=r.agreement_id,
                agreement_name=li.agreement_name,
                supplier_id=r.supplier_id,
                supplier_name=li.supplier_name,
                version_no=r.version_no,
                period_start=r.period_start,
                period_end=r.period_end,
                period_label=r.period_label,
                expected=it.expected,
                received=it.received,
                variance=it.variance,
                tolerance=it.tolerance,
                status=it.status.value,
                flags=[f.value for f in it.flags],
                engine_statuses=r.statuses,
                due_date=it.due_date,
                days_past_due=max((today - it.due_date).days, 0),
                stale=r.stale_at is not None,
                stale_reason=r.stale_reason,
                claim_id=claim[0] if claim else None,
                claim_number=claim[1] if claim else None,
                claim_assignee_id=claim[2] if claim else None,
            )
        )
    return out


StatusFilter = Annotated[str | None, Query(max_length=200, description="Comma-separated statuses")]


@router.get("/reconciliation", response_model=list[ReconRow])
def reconciliation(
    ctx: View,
    supplier_id: uuid.UUID | None = None,
    agreement_id: uuid.UUID | None = None,
    status: StatusFilter = None,
    stale: bool | None = None,
) -> list[ReconRow]:
    rows = _rows(ctx, supplier_id, agreement_id)
    if status:
        wanted = {s.strip().upper() for s in status.split(",") if s.strip()}
        rows = [r for r in rows if r.status in wanted or (wanted & set(r.engine_statuses))]
    if stale is not None:
        rows = [r for r in rows if r.stale == stale]
    return rows


@router.get("/discrepancies", response_model=list[ReconRow])
def discrepancies(
    ctx: View,
    supplier_id: uuid.UUID | None = None,
    status: StatusFilter = None,
    period_from: date | None = None,
    period_to: date | None = None,
    min_amount: Annotated[str | None, Query(max_length=30)] = None,
    min_age_days: Annotated[int | None, Query(ge=0)] = None,
    assignee_id: uuid.UUID | None = None,
    unclaimed: bool | None = None,
) -> list[ReconRow]:
    """Every SHORT_PAID / MISSING / OVERPAID item with filters (SPEC §4.8)."""
    allowed = {ReconStatus.SHORT_PAID.value, ReconStatus.MISSING.value, ReconStatus.OVERPAID.value}
    wanted = {s.strip().upper() for s in status.split(",")} & allowed if status else allowed
    rows = [r for r in _rows(ctx, supplier_id) if r.status in wanted]
    if period_from:
        rows = [r for r in rows if r.period_end >= period_from]
    if period_to:
        rows = [r for r in rows if r.period_start <= period_to]
    if min_amount:
        try:
            threshold = Decimal(min_amount)
        except ArithmeticError:
            raise AppError(
                422, "AMOUNT_INVALID", "Invalid amount", "min_amount must be a number."
            ) from None
        rows = [r for r in rows if r.variance is not None and abs(r.variance) >= threshold]
    if min_age_days is not None:
        rows = [r for r in rows if r.days_past_due >= min_age_days]
    if assignee_id:
        rows = [r for r in rows if r.claim_assignee_id == assignee_id]
    if unclaimed is not None:
        rows = [r for r in rows if (r.claim_id is None) == unclaimed]
    rows.sort(key=lambda r: abs(r.variance or Decimal(0)), reverse=True)
    return rows


# --------------------------------------------------------------------------- credits


class CreditOut(Out):
    id: uuid.UUID
    supplier_id: uuid.UUID
    credit_reference: str
    credit_date: date
    amount: DecimalStr
    memo: str
    agreement_reference: str | None
    period_start: date | None
    period_end: date | None
    period_label: str | None
    possible_duplicate: bool
    batch_id: uuid.UUID | None
    created_at: datetime


class AllocationOut(Out):
    id: uuid.UUID
    credit_id: uuid.UUID
    agreement_id: uuid.UUID
    period_start: date
    period_end: date
    amount: DecimalStr
    method: str
    created_at: datetime


class CreditDetail(CreditOut):
    allocations: list[AllocationOut]
    unallocated: DecimalStr


class SuggestionOut(Out):
    agreement_id: str
    period_start: date
    period_end: date
    amount_difference: DecimalStr
    explanation: str


class UnmatchedOut(CreditOut):
    unallocated: DecimalStr
    suggestions: list[SuggestionOut]


class AllocationPart(In):
    agreement_id: uuid.UUID
    period_start: date
    period_end: date
    amount: MoneyIn


class AllocateIn(In):
    parts: Annotated[list[AllocationPart], Field(min_length=1, max_length=50)]


class ManualCreditIn(In):
    supplier_id: uuid.UUID
    reference: Annotated[str, Field(min_length=1, max_length=100)]
    credit_date: date
    amount: MoneyIn
    memo: Annotated[str, Field(max_length=500)] = ""


@router.get("/credits", response_model=Page[CreditOut])
def list_credits(
    ctx: View,
    supplier_id: uuid.UUID | None = None,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> Page[CreditOut]:
    q = select(CreditLineRow).where(
        CreditLineRow.tenant_id == ctx.tenant_uuid, CreditLineRow.voided.is_(False)
    )
    if supplier_id:
        q = q.where(CreditLineRow.supplier_id == supplier_id)
    if cursor:
        q = q.where(CreditLineRow.id < cursor)
    rows = list(ctx.db.execute(q.order_by(CreditLineRow.id.desc()).limit(limit + 1)).scalars())
    nxt = str(rows[limit - 1].id) if len(rows) > limit else None
    return Page[CreditOut](
        items=[CreditOut.model_validate(c) for c in rows[:limit]], next_cursor=nxt
    )


@router.get("/credits/unmatched", response_model=list[UnmatchedOut])
def unmatched_credits(
    ctx: View,
    supplier_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[UnmatchedOut]:
    """Newest credits that still need allocating (at most ``limit``)."""
    assert ctx.tenant is not None
    return [
        UnmatchedOut(
            **CreditOut.model_validate(u.credit).model_dump(),
            unallocated=u.remainder,
            suggestions=[
                SuggestionOut(
                    agreement_id=s.agreement_id,
                    period_start=s.period_start,
                    period_end=s.period_end,
                    amount_difference=s.amount_difference,
                    explanation=s.explanation,
                )
                for s in u.suggestions
            ],
        )
        for u in svc.unmatched(ctx.db, ctx.tenant, supplier_id, limit)
    ]


@router.post("/credits", response_model=CreditOut, status_code=201)
def enter_credit(body: ManualCreditIn, ctx: Allocate) -> CreditOut:
    c = svc.create_manual_credit(
        ctx.db,
        ctx,
        supplier_id=body.supplier_id,
        reference=body.reference,
        credit_date=body.credit_date,
        amount=body.amount,
        memo=body.memo,
    )
    return CreditOut.model_validate(c)


def _detail(ctx: Ctx, c: CreditLineRow) -> CreditDetail:
    return CreditDetail(
        **CreditOut.model_validate(c).model_dump(),
        allocations=[
            AllocationOut.model_validate(a)
            for a in svc.credit_allocations(ctx.db, ctx.tenant_uuid, c.id)
        ],
        unallocated=svc.remainder(ctx.db, c),
    )


@router.get("/credits/{credit_id}", response_model=CreditDetail)
def get_credit(credit_id: uuid.UUID, ctx: View) -> CreditDetail:
    return _detail(ctx, svc.get_credit(ctx.db, ctx.tenant_uuid, credit_id))


@router.post("/credits/{credit_id}/allocations", response_model=CreditDetail, status_code=201)
def allocate(credit_id: uuid.UUID, body: AllocateIn, ctx: Allocate) -> CreditDetail:
    svc.allocate(ctx.db, ctx, credit_id, [p.model_dump() for p in body.parts])
    return _detail(ctx, svc.get_credit(ctx.db, ctx.tenant_uuid, credit_id))


@router.delete("/allocations/{allocation_id}", response_model=Ok)
def reverse_allocation(allocation_id: uuid.UUID, ctx: Allocate) -> Ok:
    svc.reverse(ctx.db, ctx, allocation_id)
    return Ok()
