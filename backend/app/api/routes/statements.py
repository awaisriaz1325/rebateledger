"""Supplier statement compare (v1.2 Phase 22)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import Ctx, Requires
from app.api.schemas.common import DecimalStr, In, Out
from app.core import ratelimit
from app.core.permissions import Permission
from app.services import statements as svc

router = APIRouter(prefix="/api/v1/statements", tags=["statements"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Export = Annotated[Ctx, Depends(Requires(Permission.EXPORT))]
Assign = Annotated[Ctx, Depends(Requires(Permission.RUN_RECONCILIATION, write=True))]

Status = Literal[
    "agrees",
    "purchases_differ",
    "rate_or_tier_differs",
    "not_calculated",
    "needs_review",
    "unconfirmed",
    "unmatched",
]


class StatementRowOut(Out):
    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str
    agreement_id: uuid.UUID | None
    agreement_name: str | None
    match_status: str
    statement_reference: str | None
    agreement_reference: str | None
    period_start: date
    period_end: date
    their_measure: DecimalStr | None
    our_measure: DecimalStr | None
    theirs: DecimalStr
    ours: DecimalStr | None
    difference: DecimalStr | None
    status: Status
    reason: str
    result_ids: list[uuid.UUID]
    batch_id: uuid.UUID
    source_row: int


class AssignIn(In):
    agreement_id: uuid.UUID | None


def _out(c: svc.Comparison) -> StatementRowOut:
    ln = c.line
    return StatementRowOut(
        id=ln.id,
        supplier_id=ln.supplier_id,
        supplier_name=c.supplier_name,
        agreement_id=ln.agreement_id,
        agreement_name=c.agreement_name,
        match_status=ln.match_status,
        statement_reference=ln.statement_reference,
        agreement_reference=ln.agreement_reference,
        period_start=ln.period_start,
        period_end=ln.period_end,
        their_measure=None
        if ln.supplier_measure is None
        else ln.supplier_measure.quantize(svc.CENT),
        our_measure=c.our_measure,
        theirs=c.theirs,
        ours=c.ours,
        difference=c.difference,
        status=c.status,
        reason=c.reason,
        result_ids=list(c.result_ids),
        batch_id=ln.batch_id,
        source_row=ln.source_row,
    )


def _rows(ctx: Ctx, supplier_id: uuid.UUID | None, status: Status | None) -> list[svc.Comparison]:
    assert ctx.tenant is not None
    ratelimit.heavy(ctx.user.id)
    rows = svc.compare(ctx.db, ctx.tenant, supplier_id=supplier_id)
    return [r for r in rows if status is None or r.status == status]


@router.get("", response_model=list[StatementRowOut])
def list_statements(
    ctx: View, supplier_id: uuid.UUID | None = None, status: Status | None = None
) -> list[StatementRowOut]:
    return [_out(c) for c in _rows(ctx, supplier_id, status)]


@router.get("/export", response_class=Response)
def export_statements(
    ctx: Export, supplier_id: uuid.UUID | None = None, status: Status | None = None
) -> Response:
    return Response(
        svc.to_csv(_rows(ctx, supplier_id, status)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="statement-compare.csv"'},
    )


@router.put("/{line_id}/agreement", response_model=StatementRowOut)
def assign_agreement(line_id: uuid.UUID, body: AssignIn, ctx: Assign) -> StatementRowOut:
    """Confirm the suggested agreement, choose another of the same supplier, or clear it."""
    assert ctx.tenant is not None
    line = svc.assign(ctx.db, ctx, line_id, body.agreement_id)
    [row] = [
        c
        for c in svc.compare(ctx.db, ctx.tenant, supplier_id=line.supplier_id)
        if c.line.id == line.id
    ]
    return _out(row)
