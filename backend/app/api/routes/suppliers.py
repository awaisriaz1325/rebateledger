"""Suppliers (SPEC §4.3)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy import func, or_, select

from app.api.deps import Ctx, Requires, if_match
from app.api.etag import check_if_match, etag
from app.api.schemas.common import In, Name, Ok, Out, Page
from app.core.permissions import Permission
from app.db.models.business import Supplier, SupplierAlias
from app.services import suppliers as svc

router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Edit = Annotated[Ctx, Depends(Requires(Permission.EDIT_SUPPLIERS, write=True))]
Code = Annotated[str, Field(min_length=1, max_length=100)]
Tag = Annotated[str, Field(min_length=1, max_length=60)]


Kind = Literal["supplier", "buying_group"]


class SupplierIn(In):
    name: Name
    kind: Kind = "supplier"
    codes: Annotated[list[Code], Field(min_length=1, max_length=50)]
    category_tags: Annotated[list[Tag], Field(default_factory=list, max_length=20)]
    payment_notes: Annotated[str, Field(max_length=2000)] = ""
    notes: Annotated[str, Field(max_length=5000)] = ""


class SupplierPatch(In):
    name: Name | None = None
    codes: Annotated[list[Code] | None, Field(min_length=1, max_length=50)] = None
    category_tags: Annotated[list[Tag] | None, Field(max_length=20)] = None
    payment_notes: Annotated[str | None, Field(max_length=2000)] = None
    notes: Annotated[str | None, Field(max_length=5000)] = None
    status: Literal["active", "inactive"] | None = None


class SupplierOut(Out):
    id: uuid.UUID
    name: str
    kind: str
    status: str
    codes: list[str]
    category_tags: list[str]
    payment_notes: str
    notes: str
    row_version: int
    created_at: datetime


class SupplierDetail(SupplierOut):
    latest_purchase_date: date | None
    latest_credit_date: date | None
    agreement_count: int
    member_ids: list[uuid.UUID]
    """For a buying group: suppliers whose purchases count toward its programs."""
    group_ids: list[uuid.UUID]
    """For a supplier: buying groups it belongs to."""


class MembersIn(In):
    supplier_ids: Annotated[list[uuid.UUID], Field(max_length=500)]


class ContactIn(In):
    name: Name
    email: Annotated[str, Field(max_length=254)] = ""
    phone: Annotated[str, Field(max_length=50)] = ""
    role: Annotated[str, Field(max_length=100)] = ""


class ContactOut(Out):
    id: uuid.UUID
    name: str
    email: str
    phone: str
    role: str


class MergeIn(In):
    source_id: uuid.UUID
    target_id: uuid.UUID


def _out(s: Supplier, codes: list[str]) -> SupplierOut:
    return SupplierOut(
        id=s.id,
        name=s.name,
        kind=s.kind,
        status=s.status,
        codes=codes,
        category_tags=s.category_tags,
        payment_notes=s.payment_notes,
        notes=s.notes,
        row_version=s.row_version,
        created_at=s.created_at,
    )


@router.get("", response_model=Page[SupplierOut])
def list_suppliers(
    ctx: View,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["active", "inactive"] | None = None,
    kind: Kind | None = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[SupplierOut]:
    query = select(Supplier).where(
        Supplier.tenant_id == ctx.tenant_uuid, Supplier.merged_into_id.is_(None)
    )
    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Supplier.name).like(pattern),
                Supplier.id.in_(
                    select(SupplierAlias.supplier_id).where(
                        SupplierAlias.tenant_id == ctx.tenant_uuid,
                        func.lower(SupplierAlias.code).like(pattern),
                    )
                ),
            )
        )
    if status:
        query = query.where(Supplier.status == status)
    if kind:
        query = query.where(Supplier.kind == kind)
    if cursor:
        name, _, sid = cursor.partition("|")
        query = query.where(
            (Supplier.name > name) | ((Supplier.name == name) & (Supplier.id > uuid.UUID(sid)))
        )
    rows = list(
        ctx.db.execute(query.order_by(Supplier.name, Supplier.id).limit(limit + 1)).scalars()
    )
    codes = svc.aliases(ctx.db, ctx.tenant_uuid, [s.id for s in rows])
    nxt = f"{rows[limit - 1].name}|{rows[limit - 1].id}" if len(rows) > limit else None
    return Page[SupplierOut](items=[_out(s, codes[s.id]) for s in rows[:limit]], next_cursor=nxt)


@router.post("", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, ctx: Edit) -> SupplierOut:
    s = svc.create(
        ctx.db,
        ctx,
        name=body.name,
        kind=body.kind,
        codes=body.codes,
        category_tags=body.category_tags,
        payment_notes=body.payment_notes,
        notes=body.notes,
    )
    return _out(s, svc.aliases(ctx.db, ctx.tenant_uuid, [s.id])[s.id])


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(supplier_id: uuid.UUID, response: Response, ctx: View) -> SupplierDetail:
    s = svc.get(ctx.db, ctx.tenant_uuid, supplier_id)
    response.headers["ETag"] = etag(s.row_version)
    base = _out(s, svc.aliases(ctx.db, ctx.tenant_uuid, [s.id])[s.id])
    return SupplierDetail(
        **base.model_dump(),
        **svc.detail_stats(ctx.db, ctx.tenant_uuid, s.id),
        member_ids=svc.member_ids(ctx.db, ctx.tenant_uuid, s.id),
        group_ids=svc.groups_of(ctx.db, ctx.tenant_uuid, s.id),
    )


@router.put("/{supplier_id}/members", response_model=SupplierDetail)
def set_members(
    supplier_id: uuid.UUID, body: MembersIn, response: Response, ctx: Edit
) -> SupplierDetail:
    """Replace a buying group's members. Its programs' results become stale (rerun)."""
    svc.set_members(ctx.db, ctx, supplier_id, body.supplier_ids)
    return get_supplier(supplier_id, response, ctx)


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: uuid.UUID,
    body: SupplierPatch,
    response: Response,
    ctx: Edit,
    match: Annotated[str | None, Depends(if_match)],
) -> SupplierOut:
    s = svc.get(ctx.db, ctx.tenant_uuid, supplier_id)
    check_if_match(match, s.row_version)
    svc.update_supplier(ctx.db, ctx, s, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(s.row_version)
    return _out(s, svc.aliases(ctx.db, ctx.tenant_uuid, [s.id])[s.id])


@router.get("/{supplier_id}/contacts", response_model=list[ContactOut])
def list_contacts(supplier_id: uuid.UUID, ctx: View) -> list[ContactOut]:
    svc.get(ctx.db, ctx.tenant_uuid, supplier_id)
    return [
        ContactOut.model_validate(c) for c in svc.contacts(ctx.db, ctx.tenant_uuid, supplier_id)
    ]


@router.post("/{supplier_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(supplier_id: uuid.UUID, body: ContactIn, ctx: Edit) -> ContactOut:
    s = svc.get(ctx.db, ctx.tenant_uuid, supplier_id)
    return ContactOut.model_validate(svc.add_contact(ctx.db, ctx, s, body.model_dump()))


@router.delete("/contacts/{contact_id}", response_model=Ok)
def delete_contact(contact_id: uuid.UUID, ctx: Edit) -> Ok:
    svc.delete_contact(ctx.db, ctx, contact_id)
    return Ok()


@router.post("/merge", response_model=SupplierOut)
def merge_suppliers(body: MergeIn, ctx: Edit) -> SupplierOut:
    target = svc.merge(ctx.db, ctx, body.source_id, body.target_id)
    return _out(target, svc.aliases(ctx.db, ctx.tenant_uuid, [target.id])[target.id])
