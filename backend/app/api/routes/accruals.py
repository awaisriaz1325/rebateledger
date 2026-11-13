"""Month-end accrual journal (v1.1 Phase 15): preview, export as a file, export history."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import Ctx, Requires
from app.api.schemas.common import DecimalStr, In, Out
from app.core.permissions import Permission
from app.db.models.business import AccrualExport
from app.services import accruals as svc

router = APIRouter(prefix="/api/v1", tags=["accruals"])
View = Annotated[Ctx, Depends(Requires(Permission.EXPORT))]
# The exported file goes into the books: owners and admins (approvers) sign it off.
SignOff = Annotated[Ctx, Depends(Requires(Permission.APPROVE, write=True))]


class AccrualLineOut(Out):
    agreement_id: uuid.UUID
    agreement_name: str
    supplier_name: str
    period_start: date
    period_end: date
    period_label: str
    basis: str
    earned: DecimalStr
    received: DecimalStr
    outstanding: DecimalStr


class AccrualExcludedOut(Out):
    agreement_name: str
    supplier_name: str
    period_start: date
    period_end: date
    reason: str


class AccrualChangeOut(Out):
    agreement: str
    supplier: str
    period_start: date
    before: DecimalStr | None
    after: DecimalStr | None


class AccrualExportOut(Out):
    id: uuid.UUID
    closing_date: date
    format: str
    total: DecimalStr
    line_count: int
    file_hash: str
    created_by: uuid.UUID
    created_at: datetime


class AccrualJournalOut(Out):
    closing_date: date
    reversal_date: date
    total: DecimalStr
    accounts_configured: bool
    lines: list[AccrualLineOut]
    excluded: list[AccrualExcludedOut]
    not_calculated: list[AccrualExcludedOut]
    last_export: AccrualExportOut | None
    changes_since_last_export: list[AccrualChangeOut]


class AccrualExportIn(In):
    closing_date: date
    format: Literal["generic", "qbo"]
    reviewed: Literal[True]
    """The signer confirms they reviewed the preview, estimates and exclusions."""


@router.get("/accruals/journal", response_model=AccrualJournalOut)
def preview(ctx: View, closing_date: Annotated[date, Query()]) -> AccrualJournalOut:
    """What the journal for this month end would contain. Estimates are labelled."""
    assert ctx.tenant is not None
    journal = svc.build(ctx.db, ctx.tenant, closing_date)
    prev = svc.previous(ctx.db, ctx.tenant_uuid, closing_date)
    return AccrualJournalOut(
        closing_date=journal.closing_date,
        reversal_date=journal.reversal_date,
        total=journal.total,
        accounts_configured=bool(ctx.tenant.gl_receivable_account and ctx.tenant.gl_offset_account),
        lines=[
            AccrualLineOut.model_validate({**ln.__dict__, "outstanding": ln.outstanding})
            for ln in journal.lines
        ],
        excluded=[AccrualExcludedOut.model_validate(x.__dict__) for x in journal.excluded],
        not_calculated=[
            AccrualExcludedOut.model_validate(x.__dict__) for x in journal.not_calculated
        ],
        last_export=AccrualExportOut.model_validate(prev) if prev else None,
        changes_since_last_export=[
            AccrualChangeOut.model_validate(c) for c in svc.changes(prev, journal)
        ],
    )


@router.post("/accruals/journal/export")
def export_journal(body: AccrualExportIn, ctx: SignOff) -> StreamingResponse:
    """Download the reversing journal as CSV. Recorded (who, when, file hash) and audited."""
    row, csv_body = svc.export(ctx.db, ctx, body.closing_date, body.format)
    name = f"rebate-accrual-{row.closing_date:%Y-%m}-{body.format}.csv"
    return StreamingResponse(
        iter([csv_body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Export-Id": str(row.id),
        },
    )


@router.get("/accruals/exports", response_model=list[AccrualExportOut])
def export_history(
    ctx: View, limit: Annotated[int, Query(ge=1, le=100)] = 24
) -> list[AccrualExportOut]:
    rows = ctx.db.execute(
        select(AccrualExport)
        .where(AccrualExport.tenant_id == ctx.tenant_uuid)
        .order_by(AccrualExport.created_at.desc())
        .limit(limit)
    ).scalars()
    return [AccrualExportOut.model_validate(r) for r in rows]
