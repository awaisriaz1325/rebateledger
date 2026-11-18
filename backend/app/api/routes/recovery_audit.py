"""Look-back recovery audit (v1.2 Phase 20). Calculation uses the normal runs endpoint."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from app.api.deps import Ctx, Requires, idempotency_key
from app.api.schemas.common import DecimalStr, In, Out
from app.core import ratelimit
from app.core.permissions import Permission
from app.exports import reports
from app.services import idempotency
from app.services import recovery_audit as svc

router = APIRouter(prefix="/api/v1/recovery-audit", tags=["recovery-audit"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Claims = Annotated[Ctx, Depends(Requires(Permission.EDIT_CLAIMS, write=True))]


class RecoveryGapOut(Out):
    start: date
    end: date


class RecoveryCoverageOut(Out):
    supplier_id: uuid.UUID
    name: str
    agreements: int
    gaps: list[RecoveryGapOut]
    data_from: date | None
    history_starts_late: bool


class RecoveryAuditRowOut(Out):
    result_id: uuid.UUID
    supplier: str
    agreement: str
    period: str
    period_start: date
    period_end: date
    expected: DecimalStr | None
    received: DecimalStr
    shortfall: DecimalStr | None
    status: str
    due_date: date
    age: str
    deadline: str
    claim: str


class RecoveryAuditOut(Out):
    note: str
    total_shortfall: DecimalStr
    rows: list[RecoveryAuditRowOut]


class RecoveryAuditClaimsIn(In):
    result_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=500)]


class RecoveryAuditClaimsOut(Out):
    claim_ids: list[uuid.UUID]


@router.get("/coverage", response_model=list[RecoveryCoverageOut])
def coverage(
    ctx: View, period_from: date, period_to: date, supplier_id: uuid.UUID | None = None
) -> list[RecoveryCoverageOut]:
    assert ctx.tenant is not None
    ratelimit.heavy(ctx.user.id)
    return [
        RecoveryCoverageOut(
            supplier_id=c.supplier_id,
            name=c.name,
            agreements=c.agreements,
            gaps=[RecoveryGapOut(start=a, end=b) for a, b in c.gaps],
            data_from=c.data_from,
            history_starts_late=c.history_starts_late,
        )
        for c in svc.coverage(ctx.db, ctx.tenant, period_from, period_to, supplier_id)
    ]


@router.get("", response_model=RecoveryAuditOut)
def audit(
    ctx: View, period_from: date, period_to: date, supplier_id: uuid.UUID | None = None
) -> RecoveryAuditOut:
    assert ctx.tenant is not None
    ratelimit.heavy(ctx.user.id)
    table = reports.recovery_audit(
        ctx.db,
        ctx.tenant,
        reports.ReportParams(supplier_id=supplier_id, period_from=period_from, period_to=period_to),
    )
    return RecoveryAuditOut(
        note=table.page_note,
        total_shortfall=table.totals["shortfall"],
        rows=[RecoveryAuditRowOut.model_validate(r) for r in table.rows],
    )


@router.post("/claims", response_model=RecoveryAuditClaimsOut, status_code=201)
def create_claims(
    body: RecoveryAuditClaimsIn, ctx: Claims, key: Annotated[str | None, Depends(idempotency_key)]
) -> Any:
    """One claim per supplier for the selected shortfalls; nothing is created if any fails."""
    payload = body.model_dump(mode="json")
    replay = idempotency.begin(ctx.db, ctx, "POST /recovery-audit/claims", key, payload)
    if replay:
        return JSONResponse(replay.body, status_code=replay.status)
    out = RecoveryAuditClaimsOut(claim_ids=svc.create_claims(ctx.db, ctx, body.result_ids))
    idempotency.finish(
        ctx.db, ctx, "POST /recovery-audit/claims", key, 201, out.model_dump(mode="json")
    )
    return out
