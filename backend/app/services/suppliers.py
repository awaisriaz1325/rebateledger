"""Suppliers, aliases, contacts, products, merge (SPEC §4.3)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, conflict, not_found
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    CreditLineRow,
    ImportMapping,
    Product,
    PurchaseLineRow,
    Supplier,
    SupplierAlias,
    SupplierContact,
    VersionStatus,
)
from app.services.audit import record


def normalise_code(code: str) -> str:
    return code.strip().upper()


def get(db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier:
    s = db.execute(
        select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if s is None or s.merged_into_id is not None:
        raise not_found("Supplier")
    return s


def aliases(
    db: Session, tenant_id: uuid.UUID, supplier_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {sid: [] for sid in supplier_ids}
    if supplier_ids:
        for a in db.execute(
            select(SupplierAlias)
            .where(
                SupplierAlias.tenant_id == tenant_id, SupplierAlias.supplier_id.in_(supplier_ids)
            )
            .order_by(SupplierAlias.code)
        ).scalars():
            out.setdefault(a.supplier_id, []).append(a.code)
    return out


def code_map(db: Session, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Alias code (upper) → supplier id, for imports."""
    return {
        a.code: a.supplier_id
        for a in db.execute(
            select(SupplierAlias).where(SupplierAlias.tenant_id == tenant_id)
        ).scalars()
    }


def _set_codes(db: Session, ctx: Any, supplier: Supplier, codes: list[str]) -> None:
    wanted = {normalise_code(c) for c in codes if c.strip()}
    if not wanted:
        raise AppError(
            422,
            "CODE_REQUIRED",
            "Supplier code required",
            "Add at least one supplier code as it appears in your files.",
        )
    existing = {
        a.code: a
        for a in db.execute(
            select(SupplierAlias).where(
                SupplierAlias.tenant_id == ctx.tenant_uuid, SupplierAlias.supplier_id == supplier.id
            )
        ).scalars()
    }
    for code, alias in existing.items():
        if code not in wanted:
            db.delete(alias)
    db.flush()
    for code in sorted(wanted - set(existing)):
        taken = db.execute(
            select(SupplierAlias.supplier_id).where(
                SupplierAlias.tenant_id == ctx.tenant_uuid, SupplierAlias.code == code
            )
        ).scalar()
        if taken is not None and taken != supplier.id:
            raise conflict(
                "CODE_IN_USE", f"Supplier code {code} already belongs to another supplier."
            )
        db.add(SupplierAlias(tenant_id=ctx.tenant_uuid, supplier_id=supplier.id, code=code))
    try:
        db.flush()
    except IntegrityError:  # pragma: no cover - concurrent insert of the same code
        raise conflict("CODE_IN_USE", "A supplier code is already in use.") from None


def create(
    db: Session,
    ctx: Any,
    *,
    name: str,
    codes: list[str],
    category_tags: list[str],
    payment_notes: str,
    notes: str,
) -> Supplier:
    s = Supplier(
        tenant_id=ctx.tenant_uuid,
        name=name,
        category_tags=category_tags,
        payment_notes=payment_notes,
        notes=notes,
        created_by=ctx.user.id,
    )
    db.add(s)
    db.flush()
    _set_codes(db, ctx, s, codes)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="supplier.created",
        object_type="supplier",
        object_id=s.id,
        summary={"name": name},
    )
    return s


def update_supplier(db: Session, ctx: Any, s: Supplier, values: dict[str, Any]) -> Supplier:
    codes = values.pop("codes", None)
    for key, value in values.items():
        setattr(s, key, value)
    if codes is not None:
        _set_codes(db, ctx, s, codes)
    s.updated_by = ctx.user.id
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="supplier.updated",
        object_type="supplier",
        object_id=s.id,
        summary={"fields": sorted([*values, *(["codes"] if codes is not None else [])])},
    )
    return s


def detail_stats(db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> dict[str, Any]:
    latest_purchase = db.execute(
        select(
            func.max(
                func.coalesce(
                    PurchaseLineRow.invoice_date,
                    PurchaseLineRow.ship_date,
                    PurchaseLineRow.receipt_date,
                )
            )
        ).where(
            PurchaseLineRow.tenant_id == tenant_id,
            PurchaseLineRow.supplier_id == supplier_id,
            PurchaseLineRow.voided.is_(False),
        )
    ).scalar()
    latest_credit = db.execute(
        select(func.max(CreditLineRow.credit_date)).where(
            CreditLineRow.tenant_id == tenant_id,
            CreditLineRow.supplier_id == supplier_id,
            CreditLineRow.voided.is_(False),
        )
    ).scalar()
    agreements = db.execute(
        select(func.count())
        .select_from(Agreement)
        .where(Agreement.tenant_id == tenant_id, Agreement.supplier_id == supplier_id)
    ).scalar_one()
    return {
        "latest_purchase_date": latest_purchase,
        "latest_credit_date": latest_credit,
        "agreement_count": agreements,
    }


# --------------------------------------------------------------------------- contacts


def add_contact(db: Session, ctx: Any, s: Supplier, values: dict[str, Any]) -> SupplierContact:
    c = SupplierContact(tenant_id=ctx.tenant_uuid, supplier_id=s.id, **values)
    db.add(c)
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="supplier.contact_added",
        object_type="supplier",
        object_id=s.id,
    )
    return c


def contacts(db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> list[SupplierContact]:
    return list(
        db.execute(
            select(SupplierContact)
            .where(
                SupplierContact.tenant_id == tenant_id, SupplierContact.supplier_id == supplier_id
            )
            .order_by(SupplierContact.name)
        ).scalars()
    )


def delete_contact(db: Session, ctx: Any, contact_id: uuid.UUID) -> None:
    c = db.execute(
        select(SupplierContact).where(
            SupplierContact.id == contact_id, SupplierContact.tenant_id == ctx.tenant_uuid
        )
    ).scalar_one_or_none()
    if c is None:
        raise not_found("Contact")
    db.delete(c)
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="supplier.contact_removed",
        object_type="supplier",
        object_id=c.supplier_id,
    )


# --------------------------------------------------------------------------- merge


def _active_ranges(
    db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID
) -> list[tuple[Any, Any, str]]:
    rows = db.execute(
        select(AgreementVersion.effective_from, AgreementVersion.effective_to, Agreement.name)
        .join(Agreement, Agreement.id == AgreementVersion.agreement_id)
        .where(
            Agreement.tenant_id == tenant_id,
            Agreement.supplier_id == supplier_id,
            Agreement.status == "active",
            AgreementVersion.status == VersionStatus.ACTIVE.value,
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def merge(db: Session, ctx: Any, source_id: uuid.UUID, target_id: uuid.UUID) -> Supplier:
    """Move aliases, agreements, lines, credits, products into the target (SPEC §4.3)."""
    if source_id == target_id:
        raise conflict("MERGE_SAME_SUPPLIER", "Choose two different suppliers.")
    tid = ctx.tenant_uuid
    source, target = get(db, tid, source_id), get(db, tid, target_id)
    from datetime import date as _date

    for a_from, a_to, a_name in _active_ranges(db, tid, source.id):
        for b_from, b_to, b_name in _active_ranges(db, tid, target.id):
            if a_from <= (b_to or _date.max) and b_from <= (a_to or _date.max):
                raise conflict(
                    "MERGE_OVERLAPPING_AGREEMENTS",
                    f"Both suppliers have overlapping active agreements ({a_name} and {b_name}). Archive or end one first.",
                )
    moved = {}
    for model in (
        SupplierAlias,
        SupplierContact,
        Agreement,
        PurchaseLineRow,
        CreditLineRow,
        Product,
        ImportMapping,
    ):
        result = db.execute(
            update(model)
            .where(model.tenant_id == tid, model.supplier_id == source.id)
            .values(supplier_id=target.id)
        )
        moved[model.__tablename__] = result.rowcount  # type: ignore[attr-defined]
    source.merged_into_id = target.id
    source.status = "inactive"
    record(
        db,
        tenant_id=tid,
        actor=ctx.actor,
        action="supplier.merged",
        object_type="supplier",
        object_id=target.id,
        summary={"source": str(source.id), "moved": moved},
    )
    return target
