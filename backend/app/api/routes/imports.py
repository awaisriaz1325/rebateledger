"""Import pipeline endpoints (SPEC §4.5). Long work returns 202 + a job resource."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field
from sqlalchemy import select

from app.api.deps import Ctx, Requires, idempotency_key
from app.api.schemas.common import In, Ok, Out, Page
from app.api.schemas.views import ErrorPageOut, ImportPreviewOut, ValidatePreviewOut
from app.core.csv_safe import csv_string
from app.core.errors import not_found
from app.core.permissions import Permission
from app.db.models.business import ImportBatch, ImportMapping, ImportType
from app.services import idempotency
from app.services import imports as svc

router = APIRouter(prefix="/api/v1", tags=["imports"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Manage = Annotated[Ctx, Depends(Requires(Permission.MANAGE_IMPORTS, write=True))]
IdemKey = Annotated[str | None, Depends(idempotency_key)]
HeaderName = Annotated[str, Field(min_length=1, max_length=200)]


class BatchOut(Out):
    id: uuid.UUID
    import_type: str
    status: str
    filename: str
    file_format: str
    size_bytes: int
    config: dict[str, Any]
    stats: dict[str, Any]
    commit_mode: str | None
    duplicate_of_batch_id: uuid.UUID | None
    created_at: datetime
    validated_at: datetime | None
    committed_at: datetime | None
    voided_at: datetime | None
    void_reason: str
    job_id: uuid.UUID | None


class ConfigIn(In):
    encoding: Literal["utf-8", "utf-8-sig", "utf-16", "cp1252"] | None = None
    delimiter: Literal[",", ";", "\t", "|"] | None = None
    sheet: Annotated[str | None, Field(max_length=100)] = None
    header_row: Annotated[int | None, Field(ge=1, le=100)] = None
    columns: dict[Annotated[str, Field(max_length=40)], HeaderName] | None = None
    flags: (
        dict[Annotated[str, Field(max_length=40, pattern=r"^[a-z][a-z0-9_]*$")], HeaderName] | None
    ) = None
    date_format: (
        Literal[
            "YYYY-MM-DD",
            "MM/DD/YYYY",
            "DD/MM/YYYY",
            "M/D/YY",
            "D/M/YY",
            "DD.MM.YYYY",
            "YYYYMMDD",
            "DD-MMM-YYYY",
            "MM-DD-YYYY",
        ]
        | None
    ) = None
    decimal_separator: Literal[".", ","] | None = None
    thousands_separator: Literal["", ",", ".", " ", "'"] | None = None
    negative_style: Literal["minus", "parentheses", "trailing_minus"] | None = None
    currency_symbols: Annotated[
        list[Annotated[str, Field(max_length=3)]] | None, Field(max_length=5)
    ] = None
    credit_sign: Literal["positive", "negative"] | None = None
    true_values: Annotated[
        list[Annotated[str, Field(max_length=10)]] | None, Field(max_length=10)
    ] = None
    false_values: Annotated[
        list[Annotated[str, Field(max_length=10)]] | None, Field(max_length=10)
    ] = None


class CommitIn(In):
    mode: Literal["all_or_nothing", "skip_invalid"] = "all_or_nothing"


class JobAccepted(Out):
    job_id: uuid.UUID
    batch_id: uuid.UUID


class ResolveAction(In):
    action: Literal["create", "map"]
    name: Annotated[str | None, Field(max_length=200)] = None
    supplier_id: uuid.UUID | None = None


class ResolveIn(In):
    codes: Annotated[
        dict[Annotated[str, Field(max_length=100)], ResolveAction], Field(max_length=500)
    ]


class VoidIn(In):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class TemplateIn(In):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    import_type: ImportType
    batch_id: uuid.UUID
    supplier_id: uuid.UUID | None = None
    is_default: bool = False


class TemplateOut(Out):
    id: uuid.UUID
    name: str
    import_type: str
    version: int
    supplier_id: uuid.UUID | None
    is_default: bool
    config: dict[str, Any]
    created_at: datetime


class TemplatePatch(In):
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    is_default: bool | None = None
    archived: bool | None = None


def _accepted(job_id: uuid.UUID, batch_id: uuid.UUID) -> JSONResponse:
    return JSONResponse(
        {"job_id": str(job_id), "batch_id": str(batch_id)},
        status_code=202,
        headers={"Location": f"/api/v1/jobs/{job_id}"},
    )


@router.get("/imports", response_model=Page[BatchOut])
def list_imports(
    ctx: View,
    import_type: ImportType | None = None,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[BatchOut]:
    q = select(ImportBatch).where(ImportBatch.tenant_id == ctx.tenant_uuid)
    if import_type:
        q = q.where(ImportBatch.import_type == import_type.value)
    if cursor:
        q = q.where(ImportBatch.id < cursor)
    rows = list(ctx.db.execute(q.order_by(ImportBatch.id.desc()).limit(limit + 1)).scalars())
    nxt = str(rows[limit - 1].id) if len(rows) > limit else None
    return Page[BatchOut](items=[BatchOut.model_validate(b) for b in rows[:limit]], next_cursor=nxt)


@router.post("/imports", response_model=BatchOut, status_code=201)
def upload_import(
    ctx: Manage,
    key: IdemKey,
    file: Annotated[UploadFile, File()],
    import_type: Annotated[ImportType, Form()],
    confirm_duplicate: Annotated[bool, Form()] = False,
) -> Any:
    payload = {
        "type": import_type.value,
        "filename": file.filename,
        "size": file.size,
        "confirm": confirm_duplicate,
    }
    replay = idempotency.begin(ctx.db, ctx, "POST /imports", key, payload)
    if replay:
        return JSONResponse(replay.body, status_code=replay.status)
    batch = svc.upload(
        ctx.db,
        ctx,
        import_type=import_type,
        filename=file.filename or "upload.csv",
        stream=file.file,
        confirm_duplicate=confirm_duplicate,
    )
    out = BatchOut.model_validate(batch)
    idempotency.finish(ctx.db, ctx, "POST /imports", key, 201, out.model_dump(mode="json"))
    return out


@router.get("/imports/{batch_id}", response_model=BatchOut)
def get_import(batch_id: uuid.UUID, ctx: View) -> BatchOut:
    return BatchOut.model_validate(svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id))


@router.get("/imports/{batch_id}/preview", response_model=ImportPreviewOut)
def preview_import(
    batch_id: uuid.UUID, ctx: Annotated[Ctx, Depends(Requires(Permission.MANAGE_IMPORTS))]
) -> ImportPreviewOut:
    return ImportPreviewOut.model_validate(
        svc.preview(ctx.db, ctx, svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id))
    )


@router.put("/imports/{batch_id}/config", response_model=BatchOut)
def configure_import(batch_id: uuid.UUID, body: ConfigIn, ctx: Manage) -> BatchOut:
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id, lock=True)
    return BatchOut.model_validate(
        svc.set_config(ctx.db, ctx, batch, body.model_dump(exclude_none=True))
    )


@router.post("/imports/{batch_id}/validate-preview", response_model=ValidatePreviewOut)
def validate_preview(
    batch_id: uuid.UUID, ctx: Annotated[Ctx, Depends(Requires(Permission.MANAGE_IMPORTS))]
) -> ValidatePreviewOut:
    return ValidatePreviewOut.model_validate(
        svc.validate_preview(ctx.db, ctx, svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id))
    )


@router.post("/imports/{batch_id}/validate", status_code=202, response_model=JobAccepted)
def validate_import(batch_id: uuid.UUID, ctx: Manage) -> JSONResponse:
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id, lock=True)
    return _accepted(svc.start(ctx.db, ctx, batch, commit=False), batch.id)


@router.post("/imports/{batch_id}/commit", status_code=202, response_model=JobAccepted)
def commit_import(batch_id: uuid.UUID, body: CommitIn, ctx: Manage, key: IdemKey) -> JSONResponse:
    route = f"POST /imports/{batch_id}/commit"
    replay = idempotency.begin(ctx.db, ctx, route, key, body.model_dump())
    if replay:
        return JSONResponse(
            replay.body,
            status_code=replay.status,
            headers={"Location": f"/api/v1/jobs/{replay.body['job_id']}"},
        )
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id, lock=True)
    job_id = svc.start(ctx.db, ctx, batch, commit=True, mode=body.mode)
    idempotency.finish(
        ctx.db, ctx, route, key, 202, {"job_id": str(job_id), "batch_id": str(batch.id)}
    )
    return _accepted(job_id, batch.id)


@router.post("/imports/{batch_id}/resolve-suppliers", response_model=Ok)
def resolve_suppliers(batch_id: uuid.UUID, body: ResolveIn, ctx: Manage) -> Ok:
    """Manage-imports roles (Owner/Admin/Analyst) also hold edit-suppliers."""
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id, lock=True)
    svc.resolve_suppliers(
        ctx.db, ctx, batch, {code: a.model_dump() for code, a in body.codes.items()}
    )
    return Ok()


@router.post("/imports/{batch_id}/void", response_model=BatchOut)
def void_import(batch_id: uuid.UUID, body: VoidIn, ctx: Manage) -> BatchOut:
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id, lock=True)
    return BatchOut.model_validate(svc.void(ctx.db, ctx, batch, body.reason))


@router.get("/imports/{batch_id}/errors.csv")
def error_report(batch_id: uuid.UUID, ctx: View) -> StreamingResponse:
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id)
    body = csv_string(
        ["row", "column", "value", "severity", "code", "message"],
        (
            [e.row_number, e.column_name, e.value, e.severity, e.code, e.message]
            for e in svc.error_rows(ctx.db, batch)
        ),
    )
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import-{batch.id}-errors.csv"'},
    )


@router.get("/imports/{batch_id}/errors", response_model=ErrorPageOut)
def error_page(
    batch_id: uuid.UUID, ctx: View, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> ErrorPageOut:
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, batch_id)
    items = []
    for i, e in enumerate(svc.error_rows(ctx.db, batch)):
        if i >= limit:
            break
        items.append(
            {
                "row": e.row_number,
                "column": e.column_name,
                "value": e.value,
                "severity": e.severity,
                "code": e.code,
                "message": e.message,
            }
        )
    return ErrorPageOut.model_validate({"items": items, "total": svc.error_count(ctx.db, batch)})


# --------------------------------------------------------------------------- templates


@router.get("/import-templates", response_model=list[TemplateOut])
def list_templates(ctx: View, import_type: ImportType | None = None) -> list[TemplateOut]:
    q = select(ImportMapping).where(
        ImportMapping.tenant_id == ctx.tenant_uuid, ImportMapping.archived.is_(False)
    )
    if import_type:
        q = q.where(ImportMapping.import_type == import_type.value)
    return [
        TemplateOut.model_validate(m)
        for m in ctx.db.execute(
            q.order_by(ImportMapping.name, ImportMapping.version.desc())
        ).scalars()
    ]


@router.post("/import-templates", response_model=TemplateOut, status_code=201)
def save_template(body: TemplateIn, ctx: Manage) -> TemplateOut:
    batch = svc.get_batch(ctx.db, ctx.tenant_uuid, body.batch_id)
    if body.supplier_id:
        from app.services.suppliers import get as get_supplier

        get_supplier(ctx.db, ctx.tenant_uuid, body.supplier_id)
    m = svc.save_template(
        ctx.db,
        ctx,
        name=body.name,
        import_type=body.import_type,
        config=batch.config,
        supplier_id=body.supplier_id,
        is_default=body.is_default,
    )
    return TemplateOut.model_validate(m)


@router.patch("/import-templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: uuid.UUID, body: TemplatePatch, response: Response, ctx: Manage
) -> TemplateOut:
    m = ctx.db.execute(
        select(ImportMapping).where(
            ImportMapping.id == template_id, ImportMapping.tenant_id == ctx.tenant_uuid
        )
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Template")
    if body.is_default:
        from sqlalchemy import update

        ctx.db.execute(
            update(ImportMapping)
            .where(
                ImportMapping.tenant_id == ctx.tenant_uuid,
                ImportMapping.import_type == m.import_type,
            )
            .values(is_default=False)
        )
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    return TemplateOut.model_validate(m)
