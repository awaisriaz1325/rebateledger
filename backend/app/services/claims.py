"""Claims lifecycle (SPEC §4.8). Recovered money is recorded only by linking a real credit."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError, conflict, not_found
from app.core.permissions import Permission
from app.db.models.business import Approval, SupplierContact
from app.db.models.identity import Membership, MembershipStatus
from app.db.models.runs import (
    TERMINAL_CLAIM,
    Claim,
    ClaimEvent,
    ClaimItem,
    ClaimRecovery,
    ClaimStatus,
    CreditAllocation,
)
from app.engine.reconcile import ReconStatus
from app.services import reconciliation as recon
from app.services.audit import record

S = ClaimStatus
TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    S.DRAFT: {S.READY, S.SUBMITTED, S.WRITTEN_OFF},
    S.READY: {S.DRAFT, S.SUBMITTED, S.WRITTEN_OFF},
    S.SUBMITTED: {
        S.ACKNOWLEDGED,
        S.RESOLVED_RECOVERED,
        S.RESOLVED_PARTIAL,
        S.REJECTED,
        S.WRITTEN_OFF,
    },
    S.ACKNOWLEDGED: {S.RESOLVED_RECOVERED, S.RESOLVED_PARTIAL, S.REJECTED, S.WRITTEN_OFF},
    S.REJECTED: {S.SUBMITTED, S.WRITTEN_OFF},
    S.RESOLVED_PARTIAL: {S.SUBMITTED, S.RESOLVED_RECOVERED, S.WRITTEN_OFF},
    S.RESOLVED_RECOVERED: set(),
    S.WRITTEN_OFF: set(),
}
CLAIMABLE = {ReconStatus.SHORT_PAID, ReconStatus.MISSING}


def get(db: Session, tenant_id: uuid.UUID, claim_id: uuid.UUID, *, lock: bool = False) -> Claim:
    q = select(Claim).where(Claim.id == claim_id, Claim.tenant_id == tenant_id)
    if lock:
        q = q.with_for_update()
    c = db.execute(q).scalar_one_or_none()
    if c is None:
        raise not_found("Claim")
    return c


def _event(
    db: Session,
    ctx: Any,
    claim: Claim,
    type_: str,
    *,
    text: str = "",
    from_status: str | None = None,
    to_status: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        ClaimEvent(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            actor_user_id=ctx.user.id if ctx else None,
            actor_label=ctx.user.email if ctx else "system",
            type=type_,
            text=text,
            from_status=from_status,
            to_status=to_status,
            data=data or {},
        )
    )


def _check_assignee(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    ok = db.execute(
        select(Membership.id).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE.value,
        )
    ).first()
    if not ok:
        raise AppError(
            422,
            "ASSIGNEE_INVALID",
            "Unknown assignee",
            "Assign the claim to an active member of this organization.",
        )


def _check_contact(
    db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID, contact_id: uuid.UUID | None
) -> None:
    if contact_id is None:
        return
    ok = db.execute(
        select(SupplierContact.id).where(
            SupplierContact.id == contact_id,
            SupplierContact.tenant_id == tenant_id,
            SupplierContact.supplier_id == supplier_id,
        )
    ).first()
    if not ok:
        raise AppError(
            422, "CONTACT_INVALID", "Unknown contact", "Choose a contact of this supplier."
        )


def create(
    db: Session,
    ctx: Any,
    *,
    result_ids: list[uuid.UUID],
    title: str | None,
    claimed_amount: Decimal | None,
    reason: str,
    assignee_id: uuid.UUID | None,
    due_date: date | None,
    follow_up_date: date | None,
    supplier_contact_id: uuid.UUID | None,
    channel: str,
    notes: str,
) -> Claim:
    """From one or more discrepancies of the same supplier (SPEC §4.8)."""
    assert ctx.tenant is not None
    items = {li.result.id: li for li in recon.live_items(db, ctx.tenant)}
    chosen = []
    for rid in dict.fromkeys(result_ids):
        li = items.get(rid)
        if li is None:
            raise not_found("Discrepancy")
        if li.item.status not in CLAIMABLE:
            raise conflict(
                "NOT_CLAIMABLE",
                f"{li.agreement_name} {li.result.period_start}–{li.result.period_end} is {li.item.status.value}; only short-paid or missing amounts can be claimed.",
            )
        chosen.append(li)
    if not chosen:
        raise AppError(
            422, "NO_DISCREPANCIES", "Nothing selected", "Select at least one discrepancy."
        )
    suppliers = {li.result.supplier_id for li in chosen}
    if len(suppliers) != 1:
        raise AppError(
            422,
            "MIXED_SUPPLIERS",
            "Different suppliers",
            "A claim covers discrepancies of one supplier.",
        )
    open_items = db.execute(
        select(ClaimItem.agreement_id, ClaimItem.period_start)
        .join(Claim, Claim.id == ClaimItem.claim_id)
        .where(
            Claim.tenant_id == ctx.tenant_uuid,
            Claim.status.not_in([s.value for s in TERMINAL_CLAIM]),
        )
    ).all()
    taken = {(a, p) for a, p in open_items}
    for li in chosen:
        if (li.result.agreement_id, li.result.period_start) in taken:
            raise conflict(
                "ALREADY_CLAIMED",
                f"{li.agreement_name} {li.result.period_start} already has an open claim.",
            )
    supplier_id = suppliers.pop()
    _check_assignee(db, ctx.tenant_uuid, assignee_id)
    _check_contact(db, ctx.tenant_uuid, supplier_id, supplier_contact_id)
    identified = sum((-(li.item.variance or Decimal(0)) for li in chosen), Decimal("0.00"))
    amount = identified if claimed_amount is None else claimed_amount
    if claimed_amount is not None and claimed_amount != identified and not reason.strip():
        raise AppError(
            422,
            "REASON_REQUIRED",
            "Reason required",
            "Explain why the claimed amount differs from the identified amount.",
        )
    if amount <= 0:
        raise AppError(
            422, "AMOUNT_INVALID", "Invalid amount", "The claimed amount must be positive."
        )
    number = (
        db.execute(
            select(func.max(Claim.number)).where(Claim.tenant_id == ctx.tenant_uuid)
        ).scalar()
        or 0
    ) + 1
    claim = Claim(
        tenant_id=ctx.tenant_uuid,
        number=number,
        supplier_id=supplier_id,
        title=title or f"{chosen[0].supplier_name} — {len(chosen)} period(s)",
        identified_amount=identified,
        claimed_amount=amount,
        claimed_amount_reason=reason,
        assignee_id=assignee_id,
        due_date=due_date,
        follow_up_date=follow_up_date,
        supplier_contact_id=supplier_contact_id,
        channel=channel,
        notes=notes,
        created_by=ctx.user.id,
    )
    db.add(claim)
    db.flush()
    for li in chosen:
        db.add(
            ClaimItem(
                tenant_id=ctx.tenant_uuid,
                claim_id=claim.id,
                agreement_id=li.result.agreement_id,
                period_start=li.result.period_start,
                period_end=li.result.period_end,
                result_id=li.result.id,
                expected=li.item.expected or Decimal(0),
                received_at_creation=li.item.received,
                variance_at_creation=li.item.variance or Decimal(0),
                status_at_creation=li.item.status.value,
            )
        )
    _event(
        db,
        ctx,
        claim,
        "created",
        to_status=claim.status,
        data={"identified": format(identified, "f"), "claimed": format(amount, "f")},
    )
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="claim.created",
        object_type="claim",
        object_id=claim.id,
        summary={"number": number, "claimed": format(amount, "f"), "items": len(chosen)},
    )
    return claim


def update(
    db: Session, ctx: Any, claim: Claim, values: dict[str, Any], expected_version: int
) -> Claim:
    if claim.row_version != expected_version:
        raise AppError(
            412,
            "PRECONDITION_FAILED",
            "Changed by someone else",
            "This claim was changed by someone else. Reload and try again.",
        )
    if S(claim.status) in TERMINAL_CLAIM:
        raise conflict("CLAIM_CLOSED", "Closed claims cannot be edited.")
    if "claimed_amount" in values and values["claimed_amount"] != claim.claimed_amount:
        reason = (values.get("claimed_amount_reason") or "").strip()
        if not reason:
            raise AppError(
                422,
                "REASON_REQUIRED",
                "Reason required",
                "Editing the claimed amount requires a reason.",
            )
        if values["claimed_amount"] <= 0:
            raise AppError(
                422, "AMOUNT_INVALID", "Invalid amount", "The claimed amount must be positive."
            )
        _event(
            db,
            ctx,
            claim,
            "amount_changed",
            text=reason,
            data={
                "from": format(claim.claimed_amount, "f"),
                "to": format(values["claimed_amount"], "f"),
            },
        )
    if "assignee_id" in values:
        _check_assignee(db, ctx.tenant_uuid, values["assignee_id"])
    if "supplier_contact_id" in values:
        _check_contact(db, ctx.tenant_uuid, claim.supplier_id, values["supplier_contact_id"])
    for k, v in values.items():
        setattr(claim, k, v)
    claim.updated_by = ctx.user.id
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="claim.updated",
        object_type="claim",
        object_id=claim.id,
        summary={"fields": sorted(values)},
    )
    return claim


def recovered_total(db: Session, claim_id: uuid.UUID) -> Decimal:
    return Decimal(
        db.execute(
            select(func.coalesce(func.sum(ClaimRecovery.amount), 0)).where(
                ClaimRecovery.claim_id == claim_id
            )
        ).scalar_one()
    )


def transition(db: Session, ctx: Any, claim: Claim, to: ClaimStatus, note: str = "") -> Claim:
    current = S(claim.status)
    if to not in TRANSITIONS[current]:
        raise conflict(
            "TRANSITION_NOT_ALLOWED", f"A {current.value} claim cannot move to {to.value}."
        )
    if claim.pending_write_off:
        raise conflict("WRITE_OFF_PENDING", "A write-off is awaiting approval.")
    if to is S.WRITTEN_OFF:
        return _request_write_off(db, ctx, claim, note)
    recovered = recovered_total(db, claim.id)
    if to is S.RESOLVED_RECOVERED and recovered < claim.claimed_amount:
        raise conflict(
            "RECOVERY_INCOMPLETE",
            f"Recovered {recovered:,.2f} of {claim.claimed_amount:,.2f}. Link the credits first, or resolve as partial.",
        )
    if to is S.RESOLVED_PARTIAL and recovered <= 0:
        raise conflict(
            "NO_RECOVERY", "Link at least one recovering credit before resolving as partial."
        )
    _apply(db, ctx, claim, to, note)
    return claim


def _apply(db: Session, ctx: Any, claim: Claim, to: ClaimStatus, note: str) -> None:
    before = claim.status
    claim.status = to.value
    if to is S.SUBMITTED and claim.submitted_at is None:
        claim.submitted_at = utcnow()
    if to in TERMINAL_CLAIM:
        claim.resolved_at = utcnow()
    _event(db, ctx, claim, "status_changed", text=note, from_status=before, to_status=to.value)
    record(
        db,
        tenant_id=claim.tenant_id,
        actor=ctx.actor,
        action="claim.status_changed",
        object_type="claim",
        object_id=claim.id,
        summary={"from": before, "to": to.value},
    )


def _request_write_off(db: Session, ctx: Any, claim: Claim, reason: str) -> Claim:
    if not reason.strip():
        raise AppError(
            422, "REASON_REQUIRED", "Reason required", "Writing off a claim requires a reason."
        )
    claim.write_off_reason = reason
    assert ctx.tenant is not None
    if ctx.tenant.four_eyes_writeoff:
        claim.pending_write_off = True
        approval = Approval(
            tenant_id=claim.tenant_id,
            object_type="claim_write_off",
            object_id=claim.id,
            requested_by=ctx.user.id,
            request_note=reason,
        )
        db.add(approval)
        db.flush()
        _event(
            db,
            ctx,
            claim,
            "write_off_requested",
            text=reason,
            data={"approval_id": str(approval.id)},
        )
        record(
            db,
            tenant_id=claim.tenant_id,
            actor=ctx.actor,
            action="claim.write_off_requested",
            object_type="claim",
            object_id=claim.id,
        )
        return claim
    _apply(db, ctx, claim, S.WRITTEN_OFF, reason)
    return claim


def apply_write_off_decision(db: Session, ctx: Any, approval: Approval, approve: bool) -> None:
    """Called by approvals.decide after the four-eyes checks (SPEC §9 case 38)."""
    claim = get(db, ctx.tenant_uuid, approval.object_id, lock=True)
    claim.pending_write_off = False
    if approve:
        _apply(db, ctx, claim, S.WRITTEN_OFF, approval.request_note)
    else:
        _event(db, ctx, claim, "write_off_rejected", text=approval.decision_note)


def add_note(db: Session, ctx: Any, claim: Claim, text: str) -> None:
    _event(db, ctx, claim, "note", text=text)
    record(
        db,
        tenant_id=claim.tenant_id,
        actor=ctx.actor,
        action="claim.note_added",
        object_type="claim",
        object_id=claim.id,
    )


def link_recovery(
    db: Session,
    ctx: Any,
    claim: Claim,
    *,
    credit_id: uuid.UUID | None,
    new_credit: dict[str, Any] | None,
    allocations: list[dict[str, Any]],
) -> ClaimRecovery:
    """Record recovered money by linking an actual credit (imported, or entered with
    reference and date) and allocating it to the claim's periods. Never inferred."""
    if S(claim.status) in {S.WRITTEN_OFF, S.RESOLVED_RECOVERED}:
        raise conflict("CLAIM_CLOSED", "This claim is closed.")
    if (credit_id is None) == (new_credit is None):
        raise AppError(
            422,
            "CREDIT_REQUIRED",
            "Credit required",
            "Link an existing credit or enter a new one (reference, date, amount).",
        )
    if credit_id is not None:
        credit = recon.get_credit(db, ctx.tenant_uuid, credit_id)
    else:
        assert new_credit is not None
        credit = recon.create_manual_credit(
            db,
            ctx,
            supplier_id=claim.supplier_id,
            reference=new_credit["reference"],
            credit_date=new_credit["credit_date"],
            amount=new_credit["amount"],
            memo=f"Recovery for claim {claim.number}",
        )
    if credit.supplier_id != claim.supplier_id:
        raise AppError(
            422,
            "SUPPLIER_MISMATCH",
            "Different supplier",
            "The credit belongs to another supplier.",
        )
    if credit.amount <= 0:
        raise AppError(
            422, "AMOUNT_INVALID", "Invalid credit", "A recovery must be a positive credit."
        )
    items = {
        i.id: i
        for i in db.execute(select(ClaimItem).where(ClaimItem.claim_id == claim.id)).scalars()
    }
    if not allocations:
        if len(items) != 1:
            raise AppError(
                422,
                "ALLOCATIONS_REQUIRED",
                "Allocations required",
                "Say how much of the credit applies to each period of this claim.",
            )
        only = next(iter(items.values()))
        allocations = [{"item_id": only.id, "amount": recon.remainder(db, credit)}]
    parts = []
    for a in allocations:
        item = items.get(a["item_id"])
        if item is None:
            raise not_found("Claim item")
        parts.append(
            {
                "agreement_id": item.agreement_id,
                "period_start": item.period_start,
                "period_end": item.period_end,
                "amount": a["amount"],
            }
        )
    recon.allocate(db, ctx, credit.id, parts, method="recovery")
    total = sum((p["amount"] for p in parts), Decimal(0))
    existing = db.execute(
        select(ClaimRecovery).where(
            ClaimRecovery.claim_id == claim.id, ClaimRecovery.credit_id == credit.id
        )
    ).scalar_one_or_none()
    if existing:
        existing.amount += total
        rec = existing
    else:
        rec = ClaimRecovery(
            tenant_id=claim.tenant_id,
            claim_id=claim.id,
            credit_id=credit.id,
            amount=total,
            linked_by=ctx.user.id,
        )
        db.add(rec)
    db.flush()
    recovered = recovered_total(db, claim.id)
    overage = recovered - claim.claimed_amount
    _event(
        db,
        ctx,
        claim,
        "recovery_linked",
        data={
            "credit_id": str(credit.id),
            "amount": format(total, "f"),
            "recovered_total": format(recovered, "f"),
            "overage": format(overage, "f") if overage > 0 else None,
        },
    )
    record(
        db,
        tenant_id=claim.tenant_id,
        actor=ctx.actor,
        action="claim.recovery_linked",
        object_type="claim",
        object_id=claim.id,
        summary={"credit_id": str(credit.id), "amount": format(total, "f")},
    )
    return rec


def remove_recovery(db: Session, ctx: Any, claim: Claim, recovery_id: uuid.UUID) -> None:
    rec = db.execute(
        select(ClaimRecovery).where(
            ClaimRecovery.id == recovery_id, ClaimRecovery.claim_id == claim.id
        )
    ).scalar_one_or_none()
    if rec is None:
        raise not_found("Recovery")
    if S(claim.status) in {S.RESOLVED_RECOVERED, S.WRITTEN_OFF}:
        raise conflict("CLAIM_CLOSED", "Reopen is not possible for this claim.")
    items = list(db.execute(select(ClaimItem).where(ClaimItem.claim_id == claim.id)).scalars())
    for item in items:
        for a in db.execute(
            select(CreditAllocation).where(
                CreditAllocation.tenant_id == claim.tenant_id,
                CreditAllocation.credit_id == rec.credit_id,
                CreditAllocation.agreement_id == item.agreement_id,
                CreditAllocation.period_start == item.period_start,
                CreditAllocation.method == "recovery",
                CreditAllocation.reversed_at.is_(None),
            )
        ).scalars():
            a.reversed_at, a.reversed_by = utcnow(), ctx.user.id
    db.delete(rec)
    _event(db, ctx, claim, "recovery_removed", data={"credit_id": str(rec.credit_id)})
    record(
        db,
        tenant_id=claim.tenant_id,
        actor=ctx.actor,
        action="claim.recovery_removed",
        object_type="claim",
        object_id=claim.id,
    )


def can_write_off(ctx: Any) -> bool:
    return bool(ctx.can(Permission.WRITE_OFF_CLAIMS))
