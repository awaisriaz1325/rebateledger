"""Agreements, versions, approvals, preview, attachments (SPEC §4.4)."""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select

from app.api.deps import Ctx, Requires, if_match
from app.api.etag import check_if_match, etag
from app.api.schemas.common import DecimalStr, In, Name, Ok, Out, Page
from app.api.schemas.views import ReasonOut, TraceStepOut
from app.core.errors import AppError, not_found
from app.core.permissions import Permission
from app.core.storage import get_storage, new_key
from app.db.models.business import Agreement, AgreementAttachment, AgreementVersion
from app.engine.calculate import PeriodResult
from app.services import agreements as svc
from app.services import subscriptions
from app.services.agreement_terms import AgreementCreateIn, VersionTermsIn, terms_from_rows
from app.services.audit import record

router = APIRouter(prefix="/api/v1", tags=["agreements"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Edit = Annotated[Ctx, Depends(Requires(Permission.EDIT_AGREEMENTS, write=True))]
Activate = Annotated[Ctx, Depends(Requires(Permission.ACTIVATE_AGREEMENTS, write=True))]
Approve = Annotated[Ctx, Depends(Requires(Permission.APPROVE, write=True))]
Match = Annotated[str | None, Depends(if_match)]

ATTACHMENT_TYPES = {
    "pdf": ("application/pdf", b"%PDF-"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04",
    ),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04"),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}
MAX_ATTACHMENT = 20 * 1024 * 1024


class VersionOut(Out):
    id: uuid.UUID
    agreement_id: uuid.UUID
    version_no: int
    status: str
    effective_from: date
    effective_to: date | None
    summary: str
    row_version: int
    created_at: datetime
    activated_at: datetime | None
    terms: VersionTermsIn
    warnings: list[str] = Field(default_factory=list)


class AgreementOut(Out):
    id: uuid.UUID
    supplier_id: uuid.UUID
    name: str
    external_reference: str | None
    status: str
    notes: str
    row_version: int
    created_at: datetime
    active_version: int | None = None
    latest_version_status: str | None = None
    summary: str = ""


class AgreementDetail(AgreementOut):
    versions: list[VersionOut]


class AgreementPatch(In):
    name: Name | None = None
    external_reference: Annotated[str | None, Field(max_length=100)] = None
    notes: Annotated[str | None, Field(max_length=5000)] = None


class ActivateIn(In):
    note: Annotated[str, Field(max_length=1000)] = ""


class DecisionIn(In):
    decision: Literal["approve", "reject"]
    note: Annotated[str, Field(max_length=1000)] = ""


class ApprovalOut(Out):
    id: uuid.UUID
    object_type: str
    object_id: uuid.UUID
    status: str
    requested_by: uuid.UUID
    requested_at: datetime
    request_note: str


class PreviewIn(In):
    period_containing: date


class ComponentValue(Out):
    component_id: str
    type: str
    value: DecimalStr | None
    formula: str
    tier_reached: int | None


class PreviewResultOut(Out):
    period_start: date
    period_end: date
    full_period_start: date
    full_period_end: date
    expected: DecimalStr | None
    expected_unrounded: DecimalStr | None
    spend: DecimalStr
    quantity: DecimalStr
    measure: DecimalStr
    tier_reached: int | None
    eligible_count: int
    excluded_counts: dict[str, int]
    statuses: list[str]
    reasons: list[ReasonOut]
    components: list[ComponentValue]
    trace: list[TraceStepOut]
    engine_version: str
    input_hash: str


def result_out(r: PeriodResult) -> PreviewResultOut:
    return PreviewResultOut(
        period_start=r.period.start,
        period_end=r.period.end,
        full_period_start=r.full_period.start,
        full_period_end=r.full_period.end,
        expected=r.expected,
        expected_unrounded=r.expected_unrounded,
        spend=r.spend,
        quantity=r.quantity,
        measure=r.measure,
        tier_reached=r.tier_reached,
        eligible_count=r.eligible_count,
        excluded_counts=dict(r.excluded_counts),
        statuses=[s.value for s in r.statuses],
        reasons=[ReasonOut(code=x.code, message=x.message) for x in r.reasons],
        components=[
            ComponentValue(
                component_id=c.component_id,
                type=c.type.value,
                value=c.value,
                formula=c.formula,
                tier_reached=c.tier_reached,
            )
            for c in r.components
        ],
        trace=[
            TraceStepOut(step=t.step, name=t.name, description=t.description, values=dict(t.values))
            for t in r.trace
        ],
        engine_version=r.engine_version,
        input_hash=r.input_hash,
    )


def _version_out(ctx: Ctx, v: AgreementVersion, warnings: list[str] | None = None) -> VersionOut:
    return VersionOut(
        id=v.id,
        agreement_id=v.agreement_id,
        version_no=v.version_no,
        status=v.status,
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        summary=v.summary,
        row_version=v.row_version,
        created_at=v.created_at,
        activated_at=v.activated_at,
        terms=terms_from_rows(ctx.db, v),
        warnings=warnings or [],
    )


def _agreement_out(a: Agreement, versions: list[AgreementVersion]) -> AgreementOut:
    active = next((v for v in reversed(versions) if v.status == "active"), None)
    latest = versions[-1] if versions else None
    return AgreementOut(
        id=a.id,
        supplier_id=a.supplier_id,
        name=a.name,
        external_reference=a.external_reference,
        status=a.status,
        notes=a.notes,
        row_version=a.row_version,
        created_at=a.created_at,
        active_version=active.version_no if active else None,
        latest_version_status=latest.status if latest else None,
        summary=shown.summary if (shown := active or latest) is not None else "",
    )


class TermsCheckOut(Out):
    valid: bool
    summary: str
    warnings: list[str]
    error: str | None = None


@router.post("/agreement-terms/check", response_model=TermsCheckOut)
def check_terms(body: VersionTermsIn, ctx: Edit) -> TermsCheckOut:
    """Validate draft terms and return the plain-English summary without saving (live rule builder)."""
    from app.services.agreement_terms import summarize, to_snapshot, warnings_for

    assert ctx.tenant is not None
    try:
        snap = to_snapshot(
            body,
            agreement_id="draft",
            version_id="draft",
            version_no=1,
            supplier_id="draft",
            fiscal_start=ctx.tenant.fiscal_year_start_month,
        )
    except AppError as exc:
        return TermsCheckOut(valid=False, summary="", warnings=warnings_for(body), error=exc.detail)
    return TermsCheckOut(valid=True, summary=summarize(snap), warnings=warnings_for(body))


@router.get("/agreements", response_model=Page[AgreementOut])
def list_agreements(
    ctx: View,
    supplier_id: uuid.UUID | None = None,
    status: Literal["active", "archived"] | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AgreementOut]:
    query = select(Agreement).where(Agreement.tenant_id == ctx.tenant_uuid)
    if supplier_id:
        query = query.where(Agreement.supplier_id == supplier_id)
    if status:
        query = query.where(Agreement.status == status)
    if q:
        query = query.where(
            Agreement.name.ilike(f"%{q}%") | Agreement.external_reference.ilike(f"%{q}%")
        )
    if cursor:
        try:
            query = query.where(Agreement.id > uuid.UUID(cursor))
        except ValueError:
            raise AppError(
                422, "CURSOR_INVALID", "Invalid cursor", "Start the list again."
            ) from None
    rows = list(ctx.db.execute(query.order_by(Agreement.id).limit(limit + 1)).scalars())
    by_agreement: dict[uuid.UUID, list[AgreementVersion]] = {a.id: [] for a in rows}
    if rows:
        for v in ctx.db.execute(
            select(AgreementVersion)
            .where(
                AgreementVersion.tenant_id == ctx.tenant_uuid,
                AgreementVersion.agreement_id.in_(list(by_agreement)),
            )
            .order_by(AgreementVersion.version_no)
        ).scalars():
            by_agreement[v.agreement_id].append(v)
    nxt = str(rows[limit - 1].id) if len(rows) > limit else None
    return Page[AgreementOut](
        items=[_agreement_out(a, by_agreement[a.id]) for a in rows[:limit]], next_cursor=nxt
    )


@router.post("/agreements", response_model=AgreementDetail, status_code=201)
def create_agreement(body: AgreementCreateIn, ctx: Edit) -> AgreementDetail:
    a, v, warnings = svc.create(
        ctx.db,
        ctx,
        supplier_id=body.supplier_id,
        name=body.name,
        external_reference=body.external_reference,
        notes=body.notes,
        terms=body.terms,
    )
    return AgreementDetail(
        **_agreement_out(a, [v]).model_dump(), versions=[_version_out(ctx, v, warnings)]
    )


@router.get("/agreements/{agreement_id}", response_model=AgreementDetail)
def get_agreement(agreement_id: uuid.UUID, response: Response, ctx: View) -> AgreementDetail:
    a = svc.get_agreement(ctx.db, ctx.tenant_uuid, agreement_id)
    vs = svc.versions(ctx.db, ctx.tenant_uuid, a.id)
    response.headers["ETag"] = etag(a.row_version)
    return AgreementDetail(
        **_agreement_out(a, vs).model_dump(), versions=[_version_out(ctx, v) for v in vs]
    )


@router.patch("/agreements/{agreement_id}", response_model=AgreementOut)
def update_agreement(
    agreement_id: uuid.UUID, body: AgreementPatch, response: Response, ctx: Edit, match: Match
) -> AgreementOut:
    a = svc.get_agreement(ctx.db, ctx.tenant_uuid, agreement_id)
    check_if_match(match, a.row_version)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(a, key, value.strip() or None if key == "external_reference" else value)
    a.updated_by = ctx.user.id
    ctx.db.flush()
    record(
        ctx.db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.updated",
        object_type="agreement",
        object_id=a.id,
        summary={"fields": sorted(body.model_dump(exclude_none=True))},
    )
    response.headers["ETag"] = etag(a.row_version)
    return _agreement_out(a, svc.versions(ctx.db, ctx.tenant_uuid, a.id))


@router.post("/agreements/{agreement_id}/archive", response_model=Ok)
def archive_agreement(agreement_id: uuid.UUID, ctx: Edit) -> Ok:
    svc.set_archived(ctx.db, ctx, agreement_id, True)
    return Ok()


@router.post("/agreements/{agreement_id}/unarchive", response_model=Ok)
def unarchive_agreement(agreement_id: uuid.UUID, ctx: Edit) -> Ok:
    svc.set_archived(ctx.db, ctx, agreement_id, False)
    return Ok()


@router.post("/agreements/{agreement_id}/versions", response_model=VersionOut, status_code=201)
def create_version(agreement_id: uuid.UUID, body: VersionTermsIn, ctx: Edit) -> VersionOut:
    v, warnings = svc.new_version(ctx.db, ctx, agreement_id, body)
    return _version_out(ctx, v, warnings)


@router.get("/agreement-versions/{version_id}", response_model=VersionOut)
def get_version(version_id: uuid.UUID, response: Response, ctx: View) -> VersionOut:
    v, _ = svc.get_version(ctx.db, ctx.tenant_uuid, version_id)
    response.headers["ETag"] = etag(v.row_version)
    return _version_out(ctx, v)


@router.put("/agreement-versions/{version_id}", response_model=VersionOut)
def update_version(
    version_id: uuid.UUID, body: VersionTermsIn, response: Response, ctx: Edit, match: Match
) -> VersionOut:
    v, _ = svc.get_version(ctx.db, ctx.tenant_uuid, version_id)
    version = check_if_match(match, v.row_version)
    v, warnings = svc.update_draft(ctx.db, ctx, version_id, body, version)
    response.headers["ETag"] = etag(v.row_version)
    return _version_out(ctx, v, warnings)


@router.delete("/agreement-versions/{version_id}", response_model=Ok)
def delete_version(version_id: uuid.UUID, ctx: Edit) -> Ok:
    svc.delete_draft(ctx.db, ctx, version_id)
    return Ok()


@router.post("/agreement-versions/{version_id}/activate", response_model=VersionOut)
def activate_version(version_id: uuid.UUID, body: ActivateIn, ctx: Activate) -> VersionOut:
    return _version_out(ctx, svc.request_activation(ctx.db, ctx, version_id, body.note))


@router.post("/agreement-versions/{version_id}/preview", response_model=PreviewResultOut)
def preview_version(version_id: uuid.UUID, body: PreviewIn, ctx: View) -> PreviewResultOut:
    return result_out(svc.preview(ctx.db, ctx, version_id, body.period_containing))


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(
    ctx: View, status: Literal["pending", "approved", "rejected", "cancelled"] = "pending"
) -> list[ApprovalOut]:
    return [
        ApprovalOut.model_validate(a) for a in svc.list_approvals(ctx.db, ctx.tenant_uuid, status)
    ]


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
def decide_approval(approval_id: uuid.UUID, body: DecisionIn, ctx: Approve) -> ApprovalOut:
    return ApprovalOut.model_validate(
        svc.decide(ctx.db, ctx, approval_id, body.decision == "approve", body.note)
    )


@router.post("/approvals/{approval_id}/cancel", response_model=Ok)
def cancel_approval(
    approval_id: uuid.UUID,
    ctx: Annotated[Ctx, Depends(Requires(Permission.EDIT_AGREEMENTS, write=True))],
) -> Ok:
    svc.cancel_request(ctx.db, ctx, approval_id)
    return Ok()


# --------------------------------------------------------------------------- attachments


class AttachmentOut(Out):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


@router.get("/agreements/{agreement_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(agreement_id: uuid.UUID, ctx: View) -> list[AttachmentOut]:
    svc.get_agreement(ctx.db, ctx.tenant_uuid, agreement_id)
    rows = ctx.db.execute(
        select(AgreementAttachment)
        .where(
            AgreementAttachment.tenant_id == ctx.tenant_uuid,
            AgreementAttachment.agreement_id == agreement_id,
        )
        .order_by(AgreementAttachment.created_at)
    ).scalars()
    return [AttachmentOut.model_validate(r) for r in rows]


@router.post(
    "/agreements/{agreement_id}/attachments", response_model=AttachmentOut, status_code=201
)
def upload_attachment(
    agreement_id: uuid.UUID, ctx: Edit, file: Annotated[UploadFile, File()]
) -> AttachmentOut:
    a = svc.get_agreement(ctx.db, ctx.tenant_uuid, agreement_id)
    name = (file.filename or "document").replace("/", "_").replace("\\", "_")[-200:]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ATTACHMENT_TYPES:
        raise AppError(
            422,
            "FILE_TYPE_NOT_ALLOWED",
            "File type not allowed",
            "Attach a PDF, DOCX, XLSX, PNG or JPEG file.",
        )
    content_type, magic = ATTACHMENT_TYPES[ext]
    data = file.file.read(MAX_ATTACHMENT + 1)
    if len(data) > MAX_ATTACHMENT:
        raise AppError(422, "FILE_TOO_LARGE", "File too large", "Attachments may be at most 20 MB.")
    if not data.startswith(magic):
        raise AppError(
            422,
            "FILE_SIGNATURE_MISMATCH",
            "File content does not match its type",
            "The file's contents do not match its extension.",
        )
    subscriptions.check(ctx.db, ctx.tenant_uuid, storage_bytes=len(data))
    key = new_key(ctx.tenant_uuid, "attachments")
    get_storage().put(key, io.BytesIO(data))
    att = AgreementAttachment(
        tenant_id=ctx.tenant_uuid,
        agreement_id=a.id,
        filename=name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        uploaded_by=ctx.user.id,
    )
    ctx.db.add(att)
    ctx.db.flush()
    record(
        ctx.db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.attachment_added",
        object_type="agreement",
        object_id=a.id,
        summary={"attachment_id": str(att.id)},
    )
    return AttachmentOut.model_validate(att)


@router.get("/agreement-attachments/{attachment_id}/download")
def download_attachment(attachment_id: uuid.UUID, ctx: View) -> StreamingResponse:
    att = ctx.db.execute(
        select(AgreementAttachment).where(
            AgreementAttachment.id == attachment_id,
            AgreementAttachment.tenant_id == ctx.tenant_uuid,
        )
    ).scalar_one_or_none()
    if att is None:
        raise not_found("Attachment")
    fh = get_storage().open(att.storage_key)
    return StreamingResponse(
        iter(lambda: fh.read(64 * 1024), b""),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_filename(att.filename)}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _safe_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in name)[:150] or "download"
