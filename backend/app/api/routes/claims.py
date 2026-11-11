"""Claims (SPEC §4.8)."""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, model_validator
from sqlalchemy import select

from app.api.deps import Ctx, Requires, idempotency_key, if_match
from app.api.etag import check_if_match, etag
from app.api.routes.agreements import ATTACHMENT_TYPES, MAX_ATTACHMENT, _safe_filename
from app.api.schemas.common import DecimalStr, In, MoneyIn, Ok, Out, Page
from app.core.errors import AppError, forbidden, not_found
from app.core.permissions import Permission
from app.core.storage import get_storage, new_key
from app.db.models.runs import (
    Claim,
    ClaimAttachment,
    ClaimEvent,
    ClaimItem,
    ClaimRecovery,
    ClaimStatus,
)
from app.services import claims as svc
from app.services import idempotency, subscriptions
from app.services.audit import record

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Edit = Annotated[Ctx, Depends(Requires(Permission.EDIT_CLAIMS, write=True))]
Channel = Literal["email", "portal", "phone", "other"]


class ClaimIn(In):
    result_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=100)]
    title: Annotated[str | None, Field(max_length=200)] = None
    claimed_amount: MoneyIn | None = None
    claimed_amount_reason: Annotated[str, Field(max_length=500)] = ""
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    follow_up_date: date | None = None
    supplier_contact_id: uuid.UUID | None = None
    channel: Channel = "email"
    notes: Annotated[str, Field(max_length=10_000)] = ""


class ClaimPatch(In):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    claimed_amount: MoneyIn | None = None
    claimed_amount_reason: Annotated[str | None, Field(max_length=500)] = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    follow_up_date: date | None = None
    supplier_contact_id: uuid.UUID | None = None
    channel: Channel | None = None
    notes: Annotated[str | None, Field(max_length=10_000)] = None


class TransitionIn(In):
    to: ClaimStatus
    note: Annotated[str, Field(max_length=2000)] = ""


class NoteIn(In):
    text: Annotated[str, Field(min_length=1, max_length=5000)]


class NewCreditIn(In):
    reference: Annotated[str, Field(min_length=1, max_length=100)]
    credit_date: date
    amount: MoneyIn


class RecoveryPart(In):
    item_id: uuid.UUID
    amount: MoneyIn


class RecoveryIn(In):
    credit_id: uuid.UUID | None = None
    new_credit: NewCreditIn | None = None
    allocations: Annotated[list[RecoveryPart], Field(default_factory=list, max_length=100)]

    @model_validator(mode="after")
    def _one(self) -> RecoveryIn:
        if (self.credit_id is None) == (self.new_credit is None):
            raise ValueError("give exactly one of credit_id or new_credit")
        return self


class ClaimItemOut(Out):
    id: uuid.UUID
    agreement_id: uuid.UUID
    period_start: date
    period_end: date
    result_id: uuid.UUID
    expected: DecimalStr
    received_at_creation: DecimalStr
    variance_at_creation: DecimalStr
    status_at_creation: str


class EventOut(Out):
    id: uuid.UUID
    occurred_at: datetime
    actor_label: str
    type: str
    from_status: str | None
    to_status: str | None
    text: str
    data: dict[str, Any]


class RecoveryOut(Out):
    id: uuid.UUID
    credit_id: uuid.UUID
    amount: DecimalStr
    linked_at: datetime


class ClaimAttachmentOut(Out):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class ClaimOut(Out):
    id: uuid.UUID
    number: int
    supplier_id: uuid.UUID
    title: str
    status: str
    identified_amount: DecimalStr
    claimed_amount: DecimalStr
    claimed_amount_reason: str
    recovered_amount: DecimalStr
    assignee_id: uuid.UUID | None
    due_date: date | None
    follow_up_date: date | None
    supplier_contact_id: uuid.UUID | None
    channel: str
    notes: str
    submitted_at: datetime | None
    resolved_at: datetime | None
    write_off_reason: str
    pending_write_off: bool
    row_version: int
    created_at: datetime


class ClaimDetail(ClaimOut):
    items: list[ClaimItemOut]
    events: list[EventOut]
    recoveries: list[RecoveryOut]
    attachments: list[ClaimAttachmentOut]
    allowed_transitions: list[str]


def _out(ctx: Ctx, c: Claim) -> ClaimOut:
    return ClaimOut(
        **{k: getattr(c, k) for k in ClaimOut.model_fields if k != "recovered_amount"},
        recovered_amount=svc.recovered_total(ctx.db, c.id),
    )


def _detail(ctx: Ctx, c: Claim, response: Response | None = None) -> ClaimDetail:
    if response is not None:
        response.headers["ETag"] = etag(c.row_version)
    db = ctx.db
    return ClaimDetail(
        **_out(ctx, c).model_dump(),
        items=[
            ClaimItemOut.model_validate(i)
            for i in db.execute(
                select(ClaimItem).where(ClaimItem.claim_id == c.id).order_by(ClaimItem.period_start)
            ).scalars()
        ],
        events=[
            EventOut.model_validate(e)
            for e in db.execute(
                select(ClaimEvent)
                .where(ClaimEvent.claim_id == c.id)
                .order_by(ClaimEvent.occurred_at)
            ).scalars()
        ],
        recoveries=[
            RecoveryOut.model_validate(r)
            for r in db.execute(
                select(ClaimRecovery).where(ClaimRecovery.claim_id == c.id)
            ).scalars()
        ],
        attachments=[
            ClaimAttachmentOut.model_validate(a)
            for a in db.execute(
                select(ClaimAttachment)
                .where(ClaimAttachment.claim_id == c.id)
                .order_by(ClaimAttachment.created_at)
            ).scalars()
        ],
        allowed_transitions=sorted(t.value for t in svc.TRANSITIONS[ClaimStatus(c.status)]),
    )


@router.get("", response_model=Page[ClaimOut])
def list_claims(
    ctx: View,
    status: Annotated[str | None, Query(max_length=200)] = None,
    supplier_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    open: bool | None = None,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[ClaimOut]:
    from app.db.models.runs import TERMINAL_CLAIM

    q = select(Claim).where(Claim.tenant_id == ctx.tenant_uuid)
    if status:
        q = q.where(Claim.status.in_([s.strip() for s in status.split(",")]))
    if supplier_id:
        q = q.where(Claim.supplier_id == supplier_id)
    if assignee_id:
        q = q.where(Claim.assignee_id == assignee_id)
    if open is not None:
        terminal = [s.value for s in TERMINAL_CLAIM]
        q = q.where(Claim.status.not_in(terminal) if open else Claim.status.in_(terminal))
    if cursor:
        q = q.where(Claim.number < cursor)
    rows = list(ctx.db.execute(q.order_by(Claim.number.desc()).limit(limit + 1)).scalars())
    nxt = str(rows[limit - 1].number) if len(rows) > limit else None
    return Page[ClaimOut](items=[_out(ctx, c) for c in rows[:limit]], next_cursor=nxt)


@router.post("", response_model=ClaimDetail, status_code=201)
def create_claim(
    body: ClaimIn, ctx: Edit, key: Annotated[str | None, Depends(idempotency_key)]
) -> Any:
    replay = idempotency.begin(ctx.db, ctx, "POST /claims", key, body.model_dump(mode="json"))
    if replay:
        return JSONResponse(replay.body, status_code=replay.status)
    c = svc.create(
        ctx.db,
        ctx,
        result_ids=body.result_ids,
        title=body.title,
        claimed_amount=body.claimed_amount,
        reason=body.claimed_amount_reason,
        assignee_id=body.assignee_id,
        due_date=body.due_date,
        follow_up_date=body.follow_up_date,
        supplier_contact_id=body.supplier_contact_id,
        channel=body.channel,
        notes=body.notes,
    )
    out = _detail(ctx, c)
    idempotency.finish(ctx.db, ctx, "POST /claims", key, 201, out.model_dump(mode="json"))
    return out


@router.get("/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: uuid.UUID, response: Response, ctx: View) -> ClaimDetail:
    return _detail(ctx, svc.get(ctx.db, ctx.tenant_uuid, claim_id), response)


@router.patch("/{claim_id}", response_model=ClaimDetail)
def update_claim(
    claim_id: uuid.UUID,
    body: ClaimPatch,
    response: Response,
    ctx: Edit,
    match: Annotated[str | None, Depends(if_match)],
) -> ClaimDetail:
    c = svc.get(ctx.db, ctx.tenant_uuid, claim_id, lock=True)
    version = check_if_match(match, c.row_version)
    svc.update(ctx.db, ctx, c, body.model_dump(exclude_unset=True), version)
    return _detail(ctx, c, response)


@router.post("/{claim_id}/transition", response_model=ClaimDetail)
def transition(
    claim_id: uuid.UUID, body: TransitionIn, response: Response, ctx: Edit
) -> ClaimDetail:
    c = svc.get(ctx.db, ctx.tenant_uuid, claim_id, lock=True)
    if body.to is ClaimStatus.WRITTEN_OFF and not ctx.can(Permission.WRITE_OFF_CLAIMS):
        raise forbidden("Your role cannot write off claims.")
    svc.transition(ctx.db, ctx, c, body.to, body.note)
    return _detail(ctx, c, response)


@router.post("/{claim_id}/notes", response_model=ClaimDetail, status_code=201)
def add_note(claim_id: uuid.UUID, body: NoteIn, ctx: Edit) -> ClaimDetail:
    c = svc.get(ctx.db, ctx.tenant_uuid, claim_id)
    svc.add_note(ctx.db, ctx, c, body.text)
    return _detail(ctx, c)


@router.post("/{claim_id}/recoveries", response_model=ClaimDetail, status_code=201)
def link_recovery(claim_id: uuid.UUID, body: RecoveryIn, ctx: Edit) -> ClaimDetail:
    c = svc.get(ctx.db, ctx.tenant_uuid, claim_id, lock=True)
    svc.link_recovery(
        ctx.db,
        ctx,
        c,
        credit_id=body.credit_id,
        new_credit=body.new_credit.model_dump() if body.new_credit else None,
        allocations=[a.model_dump() for a in body.allocations],
    )
    return _detail(ctx, c)


@router.delete("/{claim_id}/recoveries/{recovery_id}", response_model=Ok)
def remove_recovery(claim_id: uuid.UUID, recovery_id: uuid.UUID, ctx: Edit) -> Ok:
    c = svc.get(ctx.db, ctx.tenant_uuid, claim_id, lock=True)
    svc.remove_recovery(ctx.db, ctx, c, recovery_id)
    return Ok()


@router.post("/{claim_id}/attachments", response_model=ClaimAttachmentOut, status_code=201)
def upload_attachment(
    claim_id: uuid.UUID, ctx: Edit, file: Annotated[UploadFile, File()]
) -> ClaimAttachmentOut:
    c = svc.get(ctx.db, ctx.tenant_uuid, claim_id)
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
    key = new_key(ctx.tenant_uuid, "claim_attachments")
    get_storage().put(key, io.BytesIO(data))
    att = ClaimAttachment(
        tenant_id=ctx.tenant_uuid,
        claim_id=c.id,
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
        action="claim.attachment_added",
        object_type="claim",
        object_id=c.id,
    )
    return ClaimAttachmentOut.model_validate(att)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: uuid.UUID, ctx: View) -> StreamingResponse:
    att = ctx.db.execute(
        select(ClaimAttachment).where(
            ClaimAttachment.id == attachment_id, ClaimAttachment.tenant_id == ctx.tenant_uuid
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
