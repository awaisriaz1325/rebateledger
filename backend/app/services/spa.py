"""Ship-and-debit / SPA claims (v1.1 Phase 17): SPA records, matching job, claims, alerts.

The arithmetic lives in the pure matcher (``app/engine/spa.py``). This module loads data,
stores results and runs the claim workflow. Lines already in a (non-rejected) claim are
frozen: re-matching never changes them, and their quantities count against SPA caps.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.clock import today_in, utcnow
from app.core.csv_safe import csv_string
from app.core.errors import AppError, conflict, not_found
from app.db.models.business import (
    SaleLineRow,
    Spa,
    SpaClaim,
    SpaItem,
    SpaMatchRow,
    Supplier,
)
from app.db.models.identity import Notification, Tenant
from app.engine.spa import Sale, SpaItemTerms, SpaStatus, SpaTerms, match
from app.services import suppliers
from app.services.audit import record
from app.workers.jobs import JobContext, enqueue, handler

DEADLINE_WARNING_DAYS = 14
OPEN_CLAIM = ("draft", "submitted", "paid", "partially_paid")


# --------------------------------------------------------------------------- SPA records


def get(db: Session, tenant_id: uuid.UUID, spa_id: uuid.UUID) -> Spa:
    s = db.execute(
        select(Spa).where(Spa.tenant_id == tenant_id, Spa.id == spa_id)
    ).scalar_one_or_none()
    if s is None:
        raise not_found("SPA")
    return s


def items(db: Session, tenant_id: uuid.UUID, spa_id: uuid.UUID) -> list[SpaItem]:
    return list(
        db.execute(
            select(SpaItem)
            .where(SpaItem.tenant_id == tenant_id, SpaItem.spa_id == spa_id)
            .order_by(SpaItem.sku)
        ).scalars()
    )


def _validate(db: Session, ctx: Any, data: dict[str, Any]) -> None:
    sup = suppliers.get(db, ctx.tenant_uuid, data["supplier_id"])
    if sup.kind != "supplier":
        raise AppError(
            422,
            "SPA_SUPPLIER_INVALID",
            "Choose a supplier",
            "SPAs belong to a supplier, not a buying group.",
        )
    if data["valid_to"] < data["valid_from"]:
        raise AppError(422, "SPA_DATES_INVALID", "Invalid dates", "The SPA ends before it starts.")
    skus = [i["sku"].strip() for i in data["items"]]
    if len(set(skus)) != len(skus):
        raise AppError(
            422, "SPA_ITEMS_INVALID", "Duplicate SKU", "Each SKU may appear once per SPA."
        )
    for i in data["items"]:
        if i["book_cost"] <= 0 or i["spa_cost"] < 0:
            raise AppError(
                422,
                "SPA_ITEMS_INVALID",
                "Invalid cost",
                f"{i['sku']}: book cost must be above zero and SPA cost zero or more.",
            )
        if i.get("quantity_cap") is not None and i["quantity_cap"] <= 0:
            raise AppError(
                422,
                "SPA_ITEMS_INVALID",
                "Invalid cap",
                f"{i['sku']}: a quantity cap must be above zero.",
            )


def _set_items(db: Session, tenant_id: uuid.UUID, spa: Spa, rows: list[dict[str, Any]]) -> None:
    db.execute(delete(SpaItem).where(SpaItem.tenant_id == tenant_id, SpaItem.spa_id == spa.id))
    for i in rows:
        db.add(
            SpaItem(
                tenant_id=tenant_id,
                spa_id=spa.id,
                sku=i["sku"].strip(),
                book_cost=i["book_cost"],
                spa_cost=i["spa_cost"],
                quantity_cap=i.get("quantity_cap"),
            )
        )
    db.flush()


def create(db: Session, ctx: Any, data: dict[str, Any]) -> Spa:
    _validate(db, ctx, data)
    exists = db.execute(
        select(Spa.id).where(
            Spa.tenant_id == ctx.tenant_uuid,
            Spa.supplier_id == data["supplier_id"],
            Spa.spa_number == data["spa_number"],
        )
    ).first()
    if exists:
        raise conflict("SPA_NUMBER_TAKEN", "This supplier already has a SPA with that number.")
    spa = Spa(
        tenant_id=ctx.tenant_uuid,
        created_by=ctx.user.id,
        **{k: v for k, v in data.items() if k != "items"},
    )
    db.add(spa)
    db.flush()
    _set_items(db, ctx.tenant_uuid, spa, data["items"])
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="spa.created",
        object_type="spa",
        object_id=spa.id,
        summary={"spa_number": spa.spa_number, "items": len(data["items"])},
    )
    enqueue(db, tenant_id=ctx.tenant_uuid, job_type="spa_match", payload={})
    return spa


def update_spa(db: Session, ctx: Any, spa: Spa, data: dict[str, Any]) -> Spa:
    _validate(db, ctx, {**data, "supplier_id": spa.supplier_id})
    for k, v in data.items():
        if k not in ("items", "supplier_id"):
            setattr(spa, k, v)
    spa.updated_by = ctx.user.id
    _set_items(db, ctx.tenant_uuid, spa, data["items"])
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="spa.updated",
        object_type="spa",
        object_id=spa.id,
        summary={"spa_number": spa.spa_number, "items": len(data["items"])},
    )
    enqueue(db, tenant_id=ctx.tenant_uuid, job_type="spa_match", payload={})
    return spa


# --------------------------------------------------------------------------- matching job


def _terms(db: Session, tenant_id: uuid.UUID) -> dict[uuid.UUID, list[SpaTerms]]:
    spas = list(
        db.execute(select(Spa).where(Spa.tenant_id == tenant_id, Spa.status == "active")).scalars()
    )
    by_spa: dict[uuid.UUID, dict[str, SpaItemTerms]] = defaultdict(dict)
    if spas:
        for it in db.execute(
            select(SpaItem).where(
                SpaItem.tenant_id == tenant_id, SpaItem.spa_id.in_([s.id for s in spas])
            )
        ).scalars():
            by_spa[it.spa_id][it.sku] = SpaItemTerms(it.book_cost, it.spa_cost, it.quantity_cap)
    out: dict[uuid.UUID, list[SpaTerms]] = defaultdict(list)
    for s in spas:
        out[s.supplier_id].append(
            SpaTerms(
                spa_id=str(s.id),
                supplier_id=str(s.supplier_id),
                valid_from=s.valid_from,
                valid_to=s.valid_to,
                claim_deadline_days=s.claim_deadline_days,
                items=by_spa[s.id],
                customer=s.customer,
                job=s.job,
            )
        )
    return out


def rematch(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    """Rebuild every unclaimed match. Lines in an open claim are frozen and count toward caps."""
    db.execute(
        delete(SpaMatchRow).where(
            SpaMatchRow.tenant_id == tenant_id, SpaMatchRow.claim_id.is_(None)
        )
    )
    frozen_rows = db.execute(
        select(
            SpaMatchRow.sale_line_id,
            SpaMatchRow.spa_id,
            SaleLineRow.sku,
            SpaMatchRow.claimable_quantity,
            SpaMatchRow.status,
        )
        .join(SaleLineRow, SaleLineRow.id == SpaMatchRow.sale_line_id)
        .where(SpaMatchRow.tenant_id == tenant_id, SpaMatchRow.claim_id.is_not(None))
    ).all()
    frozen = {r[0] for r in frozen_rows}
    claimed: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for _lid, spa_id, sku, qty, status in frozen_rows:
        if spa_id is not None and status == SpaStatus.OK.value and qty > 0:
            claimed[(str(spa_id), sku)] += qty
    stored = 0
    for supplier_id, terms in _terms(db, tenant_id).items():
        start = min(t.valid_from for t in terms)
        end = max(t.valid_to for t in terms)
        sales = [
            Sale(str(r[0]), str(supplier_id), r[1], r[2], r[3], r[4], r[5], r[6])
            for r in db.execute(
                select(
                    SaleLineRow.id,
                    SaleLineRow.invoice_date,
                    SaleLineRow.sku,
                    SaleLineRow.quantity,
                    SaleLineRow.customer,
                    SaleLineRow.job,
                    SaleLineRow.unit_cost,
                ).where(
                    SaleLineRow.tenant_id == tenant_id,
                    SaleLineRow.supplier_id == supplier_id,
                    SaleLineRow.voided.is_(False),
                    SaleLineRow.invoice_date.between(start, end),
                )
            )
            if r[0] not in frozen
        ]
        rows = [
            {
                "tenant_id": tenant_id,
                "sale_line_id": int(res.line_id),
                "supplier_id": supplier_id,
                "spa_id": uuid.UUID(res.spa_id) if res.spa_id else None,
                "status": res.status.value,
                "reasons": [{"code": x.code, "message": x.message} for x in res.reasons],
                "claimable_quantity": res.claimable_quantity,
                "claimable_amount": res.claimable_amount,
                "unit_difference": res.unit_difference,
                "deadline": res.deadline,
                "engine_version": res.engine_version,
            }
            for res in match(terms, sales, claimed)
        ]
        for i in range(0, len(rows), 5_000):  # bounded statement size at 1M lines
            db.execute(insert(SpaMatchRow), rows[i : i + 5_000])
        stored += len(rows)
    return {"stored": stored, "frozen": len(frozen)}


@handler("spa_match")
def _spa_match_job(db: Session, job: JobContext) -> dict[str, Any]:
    assert job.tenant_id is not None
    return rematch(db, job.tenant_id)


# --------------------------------------------------------------------------- read models


def match_rows(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    supplier_id: uuid.UUID | None = None,
    status: str | None = None,
    unclaimed: bool | None = None,
    claim_id: uuid.UUID | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    q = (
        select(SpaMatchRow, SaleLineRow, Spa.spa_number)
        .join(SaleLineRow, SaleLineRow.id == SpaMatchRow.sale_line_id)
        .outerjoin(Spa, Spa.id == SpaMatchRow.spa_id)
        .where(SpaMatchRow.tenant_id == tenant_id)
    )
    if supplier_id:
        q = q.where(SpaMatchRow.supplier_id == supplier_id)
    if status:
        q = q.where(SpaMatchRow.status == status)
    if unclaimed is not None:
        q = q.where(
            SpaMatchRow.claim_id.is_(None) if unclaimed else SpaMatchRow.claim_id.is_not(None)
        )
    if claim_id:
        q = q.where(SpaMatchRow.claim_id == claim_id)
    q = q.order_by(SaleLineRow.invoice_date, SaleLineRow.id).limit(limit)
    return [
        {
            "sale_line_id": m.sale_line_id,
            "supplier_id": m.supplier_id,
            "invoice_number": s.invoice_number,
            "line_number": s.line_number,
            "invoice_date": s.invoice_date,
            "customer": s.customer,
            "job": s.job,
            "sku": s.sku,
            "quantity": s.quantity,
            "unit_cost": s.unit_cost,
            "spa_id": m.spa_id,
            "spa_number": number,
            "status": m.status,
            "reasons": m.reasons,
            "claimable_quantity": m.claimable_quantity,
            "claimable_amount": m.claimable_amount,
            "unit_difference": m.unit_difference,
            "deadline": m.deadline,
            "claim_id": m.claim_id,
        }
        for m, s, number in db.execute(q).all()
    ]


def summary(db: Session, tenant: Tenant) -> list[dict[str, Any]]:
    today = today_in(tenant.timezone)
    soon = today + timedelta(days=DEADLINE_WARNING_DAYS)
    rows = db.execute(
        select(
            SpaMatchRow.supplier_id,
            Supplier.name,
            func.coalesce(
                func.sum(SpaMatchRow.claimable_amount).filter(
                    SpaMatchRow.status == "ok", SpaMatchRow.claim_id.is_(None)
                ),
                0,
            ),
            func.count().filter(SpaMatchRow.status == "ok", SpaMatchRow.claim_id.is_(None)),
            func.count().filter(
                SpaMatchRow.status == "needs_review", SpaMatchRow.claim_id.is_(None)
            ),
            func.count().filter(
                SpaMatchRow.status == "ok",
                SpaMatchRow.claim_id.is_(None),
                SpaMatchRow.deadline.between(today, soon),
            ),
            func.count().filter(
                SpaMatchRow.status == "ok",
                SpaMatchRow.claim_id.is_(None),
                SpaMatchRow.deadline < today,
            ),
        )
        .join(Supplier, Supplier.id == SpaMatchRow.supplier_id)
        .where(SpaMatchRow.tenant_id == tenant.id)
        .group_by(SpaMatchRow.supplier_id, Supplier.name)
        .order_by(Supplier.name)
    ).all()
    return [
        {
            "supplier_id": r[0],
            "supplier_name": r[1],
            "unclaimed_amount": Decimal(r[2]).quantize(Decimal("0.01")),
            "unclaimed_lines": r[3],
            "needs_review_lines": r[4],
            "expiring_soon_lines": r[5],
            "past_deadline_lines": r[6],
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- claims


def get_claim(db: Session, tenant_id: uuid.UUID, claim_id: uuid.UUID) -> SpaClaim:
    c = db.execute(
        select(SpaClaim).where(SpaClaim.tenant_id == tenant_id, SpaClaim.id == claim_id)
    ).scalar_one_or_none()
    if c is None:
        raise not_found("SPA claim")
    return c


def create_claim(db: Session, ctx: Any, supplier_id: uuid.UUID, through: date) -> SpaClaim:
    """A draft claim with every unclaimed OK line of the supplier dated on or before ``through``."""
    suppliers.get(db, ctx.tenant_uuid, supplier_id)
    lines = list(
        db.execute(
            select(SpaMatchRow)
            .join(SaleLineRow, SaleLineRow.id == SpaMatchRow.sale_line_id)
            .where(
                SpaMatchRow.tenant_id == ctx.tenant_uuid,
                SpaMatchRow.supplier_id == supplier_id,
                SpaMatchRow.status == SpaStatus.OK.value,
                SpaMatchRow.claim_id.is_(None),
                SpaMatchRow.claimable_amount > 0,
                SaleLineRow.invoice_date <= through,
            )
            .with_for_update(of=SpaMatchRow)
        ).scalars()
    )
    if not lines:
        raise AppError(
            422,
            "NOTHING_TO_CLAIM",
            "Nothing to claim",
            "No unclaimed SPA lines for this supplier up to that date.",
        )
    number = (
        db.execute(
            select(func.max(SpaClaim.number)).where(SpaClaim.tenant_id == ctx.tenant_uuid)
        ).scalar()
        or 0
    ) + 1
    total = sum((m.claimable_amount for m in lines), Decimal("0.00"))
    claim = SpaClaim(
        tenant_id=ctx.tenant_uuid,
        number=number,
        supplier_id=supplier_id,
        total=total,
        line_count=len(lines),
        created_by=ctx.user.id,
    )
    db.add(claim)
    db.flush()
    for m in lines:
        m.claim_id = claim.id
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="spa_claim.created",
        object_type="spa_claim",
        object_id=claim.id,
        summary={
            "number": number,
            "lines": len(lines),
            "total": str(total),
            "through": through.isoformat(),
        },
    )
    return claim


TRANSITIONS = {
    "draft": {"submitted", "rejected"},
    "submitted": {"paid", "rejected"},
    "partially_paid": {"paid"},
}


def transition(
    db: Session,
    ctx: Any,
    claim: SpaClaim,
    to: str,
    paid_amount: Decimal | None,
    credit_reference: str,
) -> SpaClaim:
    allowed = TRANSITIONS.get(claim.status, set())
    if to not in allowed:
        raise conflict(
            "SPA_CLAIM_TRANSITION_INVALID", f"A {claim.status} claim cannot become {to}."
        )
    before = claim.status
    if to == "submitted":
        claim.status, claim.submitted_at = "submitted", utcnow()
    elif to == "paid":
        if paid_amount is None or paid_amount < 0 or not credit_reference:
            raise AppError(
                422,
                "SPA_PAYMENT_INVALID",
                "Payment details needed",
                "Enter the amount paid (zero or more) and the credit memo reference.",
            )
        received = (
            (claim.paid_amount or Decimal("0")) + paid_amount
            if claim.status == "partially_paid"
            else paid_amount
        )
        claim.paid_amount = received
        claim.credit_reference = credit_reference[:100]
        claim.status = "paid" if received >= claim.total else "partially_paid"
        if claim.status == "paid":
            claim.closed_at = utcnow()
    else:  # rejected: the lines go back to unclaimed and are matched again
        claim.status, claim.closed_at = "rejected", utcnow()
        db.execute(
            update(SpaMatchRow)
            .where(SpaMatchRow.tenant_id == ctx.tenant_uuid, SpaMatchRow.claim_id == claim.id)
            .values(claim_id=None)
        )
        enqueue(db, tenant_id=ctx.tenant_uuid, job_type="spa_match", payload={})
    claim.updated_by = ctx.user.id
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="spa_claim.transitioned",
        object_type="spa_claim",
        object_id=claim.id,
        summary={
            "from": before,
            "to": claim.status,
            "paid_amount": str(claim.paid_amount) if claim.paid_amount is not None else None,
        },
    )
    return claim


def evidence_csv(db: Session, tenant_id: uuid.UUID, claim: SpaClaim) -> str:
    rows = match_rows(db, tenant_id, claim_id=claim.id, limit=1_000_000)
    return csv_string(
        [
            "Claim",
            "SPA",
            "Invoice",
            "Line",
            "Invoice date",
            "Customer",
            "Job",
            "SKU",
            "Quantity claimed",
            "Book minus SPA cost",
            "Amount claimed",
        ],
        (
            [
                f"SPA-CL-{claim.number:04d}",
                r["spa_number"] or "",
                r["invoice_number"],
                r["line_number"] or "",
                r["invoice_date"].isoformat(),
                r["customer"] or "",
                r["job"] or "",
                r["sku"],
                f"{r['claimable_quantity']:f}",
                f"{r['unit_difference']:f}" if r["unit_difference"] is not None else "",
                f"{r['claimable_amount']:.2f}",
            ]
            for r in rows
        ),
    )


# --------------------------------------------------------------------------- deadline alerts


@handler("spa_deadlines")
def _spa_deadlines(db: Session, job: JobContext) -> dict[str, Any]:
    """Daily: unclaimed SPA lines whose claim deadline is within 14 days, once per supplier per day."""
    from app.services.notifications import managers, notify

    assert job.tenant_id is not None
    tenant = db.get(Tenant, job.tenant_id)
    assert tenant is not None
    today = today_in(tenant.timezone)
    sent = 0
    for s in summary(db, tenant):
        if not s["expiring_soon_lines"]:
            continue
        key = f"spa:{s['supplier_id']}:{today.isoformat()}"
        if db.execute(
            select(Notification.id).where(
                Notification.tenant_id == tenant.id,
                Notification.type == "spa_deadline",
                Notification.link.like(f"%{key}%"),
            )
        ).first():
            continue
        notify(
            db,
            tenant.id,
            managers(db, tenant.id),
            "spa_deadline",
            f"{s['supplier_name']}: {s['expiring_soon_lines']} SPA lines near their claim deadline",
            f"{s['expiring_soon_lines']} unclaimed SPA lines for {s['supplier_name']} reach their claim deadline within "
            f"{DEADLINE_WARNING_DAYS} days. Create a claim before then.",
            f"/app/spa?supplier={s['supplier_id']}&focus={key}",
        )
        sent += 1
    return {"sent": sent}
