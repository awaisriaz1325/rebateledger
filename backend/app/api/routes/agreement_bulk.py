"""Bulk agreement import from CSV (v1.2 Phase 21). Creates drafts only."""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response

from app.api.deps import Ctx, Requires, idempotency_key
from app.api.schemas.common import Out
from app.core import ratelimit
from app.core.permissions import Permission
from app.services import agreement_bulk as svc
from app.services import idempotency

router = APIRouter(prefix="/api/v1/agreements/bulk", tags=["agreements"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Edit = Annotated[Ctx, Depends(Requires(Permission.EDIT_AGREEMENTS, write=True))]


class BulkColumnOut(Out):
    name: str
    level: str
    required: bool
    help: str
    allowed: list[str]


class BulkErrorOut(Out):
    row: int | None
    column: str | None
    message: str


class BulkItemOut(Out):
    ref: str
    name: str
    supplier_name: str
    action: str
    agreement_id: uuid.UUID | None
    components: int
    tiers: int
    summary: str
    warnings: list[str]


class BulkPlanOut(Out):
    sha256: str
    items: list[BulkItemOut]
    errors: list[BulkErrorOut]


def _out(plan: svc.Plan) -> BulkPlanOut:
    return BulkPlanOut(
        sha256=plan.sha256,
        items=[
            BulkItemOut(
                ref=i.ref,
                name=i.name,
                supplier_name=i.supplier_name,
                action=i.action,
                agreement_id=i.agreement_id,
                components=i.components,
                tiers=i.tiers,
                summary=i.summary,
                warnings=i.warnings,
            )
            for i in plan.items
        ],
        errors=[BulkErrorOut(row=e.row, column=e.column, message=e.message) for e in plan.errors],
    )


def _read(file: UploadFile) -> bytes:
    return file.file.read(svc.MAX_BYTES + 1)


@router.get("/columns", response_model=list[BulkColumnOut])
def columns(ctx: View) -> list[BulkColumnOut]:
    return [
        BulkColumnOut(
            name=c.name, level=c.level, required=c.required, help=c.help, allowed=list(c.allowed)
        )
        for c in svc.COLUMNS
    ]


@router.get("/template", response_class=Response)
def template(ctx: View) -> Response:
    return Response(
        svc.template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="agreements-template.csv"'},
    )


@router.post("/preview", response_model=BulkPlanOut)
def preview(ctx: Edit, file: Annotated[UploadFile, File()]) -> BulkPlanOut:
    """Validate the file and show what would be created. Nothing is saved."""
    ratelimit.heavy(ctx.user.id)
    return _out(svc.parse(ctx.db, ctx, _read(file)))


@router.post("", response_model=BulkPlanOut, status_code=201)
def commit(
    ctx: Edit,
    file: Annotated[UploadFile, File()],
    key: Annotated[str | None, Depends(idempotency_key)],
) -> Any:
    """Create every agreement in the file as a draft, or nothing if any row has an error."""
    data = _read(file)
    payload = {"sha256": hashlib.sha256(data).hexdigest()}
    replay = idempotency.begin(ctx.db, ctx, "POST /agreements/bulk", key, payload)
    if replay:
        return JSONResponse(replay.body, status_code=replay.status)
    out = _out(svc.commit(ctx.db, ctx, data))
    idempotency.finish(ctx.db, ctx, "POST /agreements/bulk", key, 201, out.model_dump(mode="json"))
    return out
