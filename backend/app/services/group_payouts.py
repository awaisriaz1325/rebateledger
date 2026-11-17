"""Buying-group payouts (v1.2 Phase 23, ADR 0019 D3).

A supplier program can be paid *through* a buying group (``Agreement.paid_via_group_id``). The
group keeps one fee, a fraction of each rebate it passes through (``Supplier.group_fee_pct``).
Reconciliation then expects the rebate net of that fee:

    expected net = expected × (1 − fee), rounded half-up to cents.

The engine result (gross) is never changed; only the amount reconciliation compares with.
"""

from __future__ import annotations

import decimal
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.db.models.business import Agreement, BuyingGroupMember, Supplier
from app.services.audit import record

CENT = Decimal("0.01")


def net_expected(expected: Decimal | None, fee: Decimal | None) -> Decimal | None:
    """Pure: the amount the member should receive from the group."""
    if expected is None or not fee:
        return expected
    with decimal.localcontext() as ctx:
        ctx.prec = 34
        return (expected * (Decimal(1) - fee)).quantize(CENT, rounding=ROUND_HALF_UP)


def fee_amount(expected: Decimal | None, fee: Decimal | None) -> Decimal | None:
    net = net_expected(expected, fee)
    return None if expected is None or net is None else expected - net


def fees(db: Session, tenant_id: uuid.UUID) -> dict[uuid.UUID, Decimal | None]:
    """Buying group id → fee fraction (None when not set)."""
    return dict(
        db.execute(
            select(Supplier.id, Supplier.group_fee_pct).where(
                Supplier.tenant_id == tenant_id, Supplier.kind == "buying_group"
            )
        ).all()
    )


def fee_for(agreement: Agreement, group_fees: dict[uuid.UUID, Decimal | None]) -> Decimal | None:
    return group_fees.get(agreement.paid_via_group_id) if agreement.paid_via_group_id else None


def payer_id(agreement: Agreement) -> uuid.UUID:
    """Who sends the credit: the group when the program is paid through one."""
    return agreement.paid_via_group_id or agreement.supplier_id


def set_paid_via(db: Session, ctx: Any, agreement: Agreement, group_id: uuid.UUID | None) -> None:
    if group_id is not None:
        group = db.execute(
            select(Supplier).where(Supplier.id == group_id, Supplier.tenant_id == ctx.tenant_uuid)
        ).scalar_one_or_none()
        if group is None:
            raise not_found("Buying group")
        if group.kind != "buying_group":
            raise AppError(
                409, "NOT_A_BUYING_GROUP", "Not a buying group", "Choose a buying group."
            )
        member = db.execute(
            select(BuyingGroupMember.id).where(
                BuyingGroupMember.tenant_id == ctx.tenant_uuid,
                BuyingGroupMember.group_id == group.id,
                BuyingGroupMember.supplier_id == agreement.supplier_id,
            )
        ).first()
        if member is None:
            raise AppError(
                422,
                "NOT_A_GROUP_MEMBER",
                "Supplier is not in this group",
                "Add the agreement's supplier to the buying group's members first.",
            )
    agreement.paid_via_group_id = group_id
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="agreement.paid_via_group_set",
        object_type="agreement",
        object_id=agreement.id,
        summary={"group_id": str(group_id) if group_id else None},
    )
