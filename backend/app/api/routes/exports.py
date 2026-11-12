"""Reports, exports, evidence packs and full data export (SPEC §4.10, §4.8).

Exports stay available to suspended tenants (SPEC §9 case 46), so none of these
routes use ``write=True``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from app.api.deps import Ctx, Requires, idempotency_key
from app.api.schemas.common import In, Out
from app.core.permissions import Permission
from app.exports import reports
from app.exports import service as svc
from app.exports.writers import text_value
from app.services import idempotency
from app.services.auth import require_recent_step_up

router = APIRouter(prefix="/api/v1", tags=["reports"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Exporter = Annotated[Ctx, Depends(Requires(Permission.EXPORT))]
Owner = Annotated[Ctx, Depends(Requires(Permission.FULL_EXPORT))]
PREVIEW_ROWS = 1000

ReportKey = Literal[
    "reconciliation_summary",
    "supplier_statement",
    "claims_register",
    "recovery_report",
    "agreement_register",
    "import_history",
]


class ReportInfo(Out):
    key: str
    title: str
    description: str
    formats: list[str]
    filters: list[str]
    requires_supplier: bool


class ReportColumn(Out):
    key: str
    label: str
    kind: str


class ReportPreviewOut(Out):
    key: str
    title: str
    subtitle: str
    columns: list[ReportColumn]
    rows: list[dict[str, str]]
    totals: dict[str, str]
    row_count: int
    truncated: bool


class ExportOut(Out):
    id: uuid.UUID
    kind: str
    report: str
    format: str
    params: dict[str, Any]
    status: str
    filename: str
    size_bytes: int | None
    row_count: int | None
    job_id: uuid.UUID | None
    requested_by: uuid.UUID
    error: str
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None


class ReportFilters(In):
    supplier_id: uuid.UUID | None = None
    period_from: date | None = None
    period_to: date | None = None
    status: Annotated[str | None, Field(max_length=200)] = None


class ExportIn(In):
    report: ReportKey
    format: Literal["csv", "xlsx", "pdf"]
    params: ReportFilters = Field(default_factory=ReportFilters)


class LinkOut(Out):
    url: str
    expires_at: datetime


@router.get("/reports", response_model=list[ReportInfo])
def list_reports(ctx: View) -> list[ReportInfo]:
    return [
        ReportInfo(
            key=d.key,
            title=d.title,
            description=d.description,
            formats=["csv", "xlsx", *(["pdf"] if d.pdf else [])],
            filters=list(d.filters),
            requires_supplier=d.requires_supplier,
        )
        for d in reports.REPORTS.values()
    ]


@router.get("/reports/preview", response_model=ReportPreviewOut)
def preview_report(
    ctx: View,
    report: ReportKey,
    supplier_id: uuid.UUID | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    status: Annotated[str | None, Query(max_length=200)] = None,
) -> ReportPreviewOut:
    assert ctx.tenant is not None
    filters = ReportFilters(
        supplier_id=supplier_id, period_from=period_from, period_to=period_to, status=status
    )
    table = reports.build(
        ctx.db, ctx.tenant, report, filters.model_dump(mode="json", exclude_none=True)
    )
    return ReportPreviewOut(
        key=report,
        title=table.title,
        subtitle=table.subtitle,
        columns=[ReportColumn(key=c.key, label=c.label, kind=c.kind) for c in table.columns],
        rows=[
            {c.key: text_value(r.get(c.key), c.kind) for c in table.columns}
            for r in table.rows[:PREVIEW_ROWS]
        ],
        totals={k: text_value(v, "money") for k, v in table.totals.items()},
        row_count=len(table.rows),
        truncated=len(table.rows) > PREVIEW_ROWS,
    )


def _accepted(
    ctx: Ctx, scope: str, key: str | None, body: dict[str, Any], make: Any
) -> JSONResponse:
    replay = idempotency.begin(ctx.db, ctx, scope, key, body)
    if replay:
        return JSONResponse(replay.body, status_code=replay.status)
    out = ExportOut.model_validate(make()).model_dump(mode="json")
    idempotency.finish(ctx.db, ctx, scope, key, 202, out)
    return JSONResponse(out, status_code=202, headers={"Location": f"/api/v1/exports/{out['id']}"})


@router.post("/exports", status_code=202, response_model=ExportOut)
def create_export(
    body: ExportIn, ctx: Exporter, key: Annotated[str | None, Depends(idempotency_key)]
) -> JSONResponse:
    params = body.params.model_dump(mode="json", exclude_none=True)
    return _accepted(
        ctx,
        "POST /exports",
        key,
        body.model_dump(mode="json"),
        lambda: svc.request_report(ctx.db, ctx, body.report, body.format, params),
    )


@router.post("/claims/{claim_id}/evidence-pack", status_code=202, response_model=ExportOut)
def create_evidence_pack(
    claim_id: uuid.UUID, ctx: Exporter, key: Annotated[str | None, Depends(idempotency_key)]
) -> JSONResponse:
    return _accepted(
        ctx,
        "POST /claims/evidence-pack",
        key,
        {"claim_id": str(claim_id)},
        lambda: svc.request_evidence_pack(ctx.db, ctx, claim_id),
    )


@router.post("/org/data-export", status_code=202, response_model=ExportOut)
def create_full_export(
    ctx: Owner, key: Annotated[str | None, Depends(idempotency_key)]
) -> JSONResponse:
    assert ctx.session is not None
    require_recent_step_up(ctx.session)
    return _accepted(
        ctx, "POST /org/data-export", key, {}, lambda: svc.request_full_export(ctx.db, ctx)
    )


@router.get("/exports", response_model=list[ExportOut])
def list_exports(ctx: Exporter) -> list[ExportOut]:
    """Your own exports; people with full-export rights see everyone's."""
    rows = svc.history(
        ctx.db, ctx.tenant_uuid, ctx.user.id, include_all=ctx.can(Permission.FULL_EXPORT)
    )
    return [ExportOut.model_validate(e) for e in rows]


@router.get("/exports/download")
def download_export(
    ctx: Exporter, token: Annotated[str, Query(min_length=10, max_length=600)]
) -> StreamingResponse:
    export, stream = svc.open_download(ctx.db, ctx, token)

    def chunks() -> Any:
        with stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        chunks(),
        media_type=svc.CONTENT_TYPES[export.format],
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/exports/{export_id}", response_model=ExportOut)
def get_export(export_id: uuid.UUID, ctx: Exporter) -> ExportOut:
    export = svc.get(ctx.db, ctx.tenant_uuid, export_id)
    svc.check_visible(export, ctx)
    return ExportOut.model_validate(export)


@router.post("/exports/{export_id}/link", response_model=LinkOut)
def export_link(export_id: uuid.UUID, ctx: Exporter) -> LinkOut:
    url, expires = svc.issue_link(ctx.db, ctx, export_id)
    return LinkOut(url=url, expires_at=expires)
