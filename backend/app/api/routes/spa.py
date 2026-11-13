"""Ship-and-debit / SPA claims (v1.1 Phase 17)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field
from sqlalchemy import select

from app.api.deps import Ctx, Requires, idempotency_key, if_match
from app.api.etag import check_if_match, etag
from app.api.schemas.common import DecimalStr, In, Out
from app.core.permissions import Permission
from app.db.models.business import Spa, SpaClaim
from app.services import idempotency
from app.services import spa as svc
from app.workers.jobs import enqueue

router = APIRouter(prefix="/api/v1", tags=["spa"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
EditSpa = Annotated[Ctx, Depends(Requires(Permission.EDIT_AGREEMENTS, write=True))]
EditClaims = Annotated[Ctx, Depends(Requires(Permission.EDIT_CLAIMS, write=True))]
Rerun = Annotated[Ctx, Depends(Requires(Permission.RUN_RECONCILIATION, write=True))]
Export = Annotated[Ctx, Depends(Requires(Permission.EXPORT))]
IdemKey = Annotated[str | None, Depends(idempotency_key)]
Party = Annotated[str | None, Field(max_length=200)]


class SpaItemIn(In):
    sku: Annotated[str, Field(min_length=1, max_length=100)]
    book_cost: DecimalStr
    spa_cost: DecimalStr
    quantity_cap: DecimalStr | None = None


class SpaIn(In):
    supplier_id: uuid.UUID
    spa_number: Annotated[str, Field(min_length=1, max_length=100)]
    customer: Party = None
    job: Party = None
    valid_from: date
    valid_to: date
    claim_deadline_days: Annotated[int, Field(ge=1, le=730)]
    status: Literal["active", "inactive"] = "active"
    notes: Annotated[str, Field(max_length=5000)] = ""
    items: Annotated[list[SpaItemIn], Field(min_length=1, max_length=2000)]


class SpaUpdateIn(In):
    customer: Party = None
    job: Party = None
    valid_from: date
    valid_to: date
    claim_deadline_days: Annotated[int, Field(ge=1, le=730)]
    status: Literal["active", "inactive"]
    notes: Annotated[str, Field(max_length=5000)] = ""
    items: Annotated[list[SpaItemIn], Field(min_length=1, max_length=2000)]


class SpaItemOut(Out):
    sku: str
    book_cost: DecimalStr
    spa_cost: DecimalStr
    quantity_cap: DecimalStr | None


class SpaOut(Out):
    id: uuid.UUID
    supplier_id: uuid.UUID
    spa_number: str
    customer: str | None
    job: str | None
    valid_from: date
    valid_to: date
    claim_deadline_days: int
    status: str
    notes: str
    row_version: int
    items: list[SpaItemOut]


class SpaReasonOut(Out):
    code: str
    message: str


class SpaMatchOut(Out):
    sale_line_id: int
    supplier_id: uuid.UUID
    invoice_number: str
    line_number: str | None
    invoice_date: date
    customer: str | None
    job: str | None
    sku: str
    quantity: DecimalStr
    unit_cost: DecimalStr | None
    spa_id: uuid.UUID | None
    spa_number: str | None
    status: str
    reasons: list[SpaReasonOut]
    claimable_quantity: DecimalStr
    claimable_amount: DecimalStr
    unit_difference: DecimalStr | None
    deadline: date | None
    claim_id: uuid.UUID | None


class SpaSummaryOut(Out):
    supplier_id: uuid.UUID
    supplier_name: str
    unclaimed_amount: DecimalStr
    unclaimed_lines: int
    needs_review_lines: int
    expiring_soon_lines: int
    past_deadline_lines: int


class SpaClaimIn(In):
    supplier_id: uuid.UUID
    through_date: date


class SpaClaimOut(Out):
    id: uuid.UUID
    number: int
    supplier_id: uuid.UUID
    status: str
    total: DecimalStr
    line_count: int
    paid_amount: DecimalStr | None
    credit_reference: str
    submitted_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    row_version: int


class SpaTransitionIn(In):
    to: Literal["submitted", "paid", "rejected"]
    paid_amount: DecimalStr | None = None
    credit_reference: Annotated[str, Field(max_length=100)] = ""


def _spa_out(db: Any, ctx: Ctx, s: Spa) -> SpaOut:
    return SpaOut.model_validate(
        {
            **{c: getattr(s, c) for c in SpaOut.model_fields if c != "items"},
            "items": [SpaItemOut.model_validate(i) for i in svc.items(db, ctx.tenant_uuid, s.id)],
        }
    )


@router.get("/spas", response_model=list[SpaOut])
def list_spas(ctx: View, supplier_id: uuid.UUID | None = None) -> list[SpaOut]:
    q = select(Spa).where(Spa.tenant_id == ctx.tenant_uuid)
    if supplier_id:
        q = q.where(Spa.supplier_id == supplier_id)
    return [_spa_out(ctx.db, ctx, s) for s in ctx.db.execute(q.order_by(Spa.spa_number)).scalars()]


@router.post("/spas", response_model=SpaOut, status_code=201)
def create_spa(body: SpaIn, ctx: EditSpa) -> SpaOut:
    data = body.model_dump()
    return _spa_out(ctx.db, ctx, svc.create(ctx.db, ctx, data))


@router.get("/spas/{spa_id}", response_model=SpaOut)
def get_spa(spa_id: uuid.UUID, response: Response, ctx: View) -> SpaOut:
    s = svc.get(ctx.db, ctx.tenant_uuid, spa_id)
    response.headers["ETag"] = etag(s.row_version)
    return _spa_out(ctx.db, ctx, s)


@router.put("/spas/{spa_id}", response_model=SpaOut)
def update_spa(
    spa_id: uuid.UUID,
    body: SpaUpdateIn,
    response: Response,
    ctx: EditSpa,
    match: Annotated[str | None, Depends(if_match)],
) -> SpaOut:
    s = svc.get(ctx.db, ctx.tenant_uuid, spa_id)
    check_if_match(match, s.row_version)
    svc.update_spa(ctx.db, ctx, s, body.model_dump())
    ctx.db.flush()
    response.headers["ETag"] = etag(s.row_version)
    return _spa_out(ctx.db, ctx, s)


@router.post("/spa/recalculate", status_code=202)
def recalculate(ctx: Rerun) -> JSONResponse:
    """Match every unclaimed sale line again (background job)."""
    job = enqueue(
        ctx.db, tenant_id=ctx.tenant_uuid, job_type="spa_match", payload={}, created_by=ctx.user.id
    )
    return JSONResponse(
        {"job_id": str(job.id)}, status_code=202, headers={"Location": f"/api/v1/jobs/{job.id}"}
    )


@router.get("/spa/summary", response_model=list[SpaSummaryOut])
def spa_summary(ctx: View) -> list[SpaSummaryOut]:
    assert ctx.tenant is not None
    return [SpaSummaryOut.model_validate(r) for r in svc.summary(ctx.db, ctx.tenant)]


@router.get("/spa/matches", response_model=list[SpaMatchOut])
def spa_matches(
    ctx: View,
    supplier_id: uuid.UUID | None = None,
    status: Literal["ok", "needs_review", "not_claimable"] | None = None,
    unclaimed: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[SpaMatchOut]:
    rows = svc.match_rows(
        ctx.db,
        ctx.tenant_uuid,
        supplier_id=supplier_id,
        status=status,
        unclaimed=unclaimed,
        limit=limit,
    )
    return [SpaMatchOut.model_validate(r) for r in rows]


@router.get("/spa-claims", response_model=list[SpaClaimOut])
def list_claims(ctx: View, supplier_id: uuid.UUID | None = None) -> list[SpaClaimOut]:
    q = select(SpaClaim).where(SpaClaim.tenant_id == ctx.tenant_uuid)
    if supplier_id:
        q = q.where(SpaClaim.supplier_id == supplier_id)
    return [
        SpaClaimOut.model_validate(c)
        for c in ctx.db.execute(q.order_by(SpaClaim.number.desc())).scalars()
    ]


@router.post("/spa-claims", response_model=SpaClaimOut, status_code=201)
def create_claim(body: SpaClaimIn, ctx: EditClaims, key: IdemKey) -> Any:
    """A draft claim with every unclaimed OK line up to the date. Accepts Idempotency-Key."""
    replay = idempotency.begin(ctx.db, ctx, "POST /spa-claims", key, body.model_dump(mode="json"))
    if replay:
        return JSONResponse(replay.body, status_code=replay.status)
    c = svc.create_claim(ctx.db, ctx, body.supplier_id, body.through_date)
    ctx.db.flush()
    out = SpaClaimOut.model_validate(c)
    idempotency.finish(ctx.db, ctx, "POST /spa-claims", key, 201, out.model_dump(mode="json"))
    return out


@router.get("/spa-claims/{claim_id}", response_model=SpaClaimOut)
def get_claim(claim_id: uuid.UUID, response: Response, ctx: View) -> SpaClaimOut:
    c = svc.get_claim(ctx.db, ctx.tenant_uuid, claim_id)
    response.headers["ETag"] = etag(c.row_version)
    return SpaClaimOut.model_validate(c)


@router.get("/spa-claims/{claim_id}/lines", response_model=list[SpaMatchOut])
def claim_lines(claim_id: uuid.UUID, ctx: View) -> list[SpaMatchOut]:
    c = svc.get_claim(ctx.db, ctx.tenant_uuid, claim_id)
    return [
        SpaMatchOut.model_validate(r)
        for r in svc.match_rows(ctx.db, ctx.tenant_uuid, claim_id=c.id, limit=2000)
    ]


@router.post("/spa-claims/{claim_id}/transition", response_model=SpaClaimOut)
def transition_claim(
    claim_id: uuid.UUID,
    body: SpaTransitionIn,
    response: Response,
    ctx: EditClaims,
    match: Annotated[str | None, Depends(if_match)],
) -> SpaClaimOut:
    c = svc.get_claim(ctx.db, ctx.tenant_uuid, claim_id)
    check_if_match(match, c.row_version)
    svc.transition(ctx.db, ctx, c, body.to, body.paid_amount, body.credit_reference)
    ctx.db.flush()
    response.headers["ETag"] = etag(c.row_version)
    return SpaClaimOut.model_validate(c)


@router.get("/spa-claims/{claim_id}/evidence.csv")
def claim_evidence(claim_id: uuid.UUID, ctx: Export) -> StreamingResponse:
    c = svc.get_claim(ctx.db, ctx.tenant_uuid, claim_id)
    return StreamingResponse(
        iter([svc.evidence_csv(ctx.db, ctx.tenant_uuid, c)]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="spa-claim-{c.number:04d}.csv"'},
    )
