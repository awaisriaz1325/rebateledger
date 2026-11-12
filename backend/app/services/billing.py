"""Invoice billing (SPEC §4.14): drafts, gap-free yearly numbering, PDF, payment, void,
lapse policy and reminders. No card payments and no tax computation in v1 ([OPEN] §15).

Numbering: the number is taken from ``invoice_sequences`` with a single
``INSERT … ON CONFLICT DO UPDATE … RETURNING`` inside the issuing transaction. The row
lock serialises concurrent issuers and a rolled-back issue rolls the counter back too,
so numbers never collide and never skip.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import AppError, conflict, not_found
from app.core.storage import get_storage, new_key
from app.db.models.billing import Invoice, InvoiceLine, InvoiceStatus, OpsSetting
from app.db.models.business import Subscription, SubscriptionStatus
from app.db.models.identity import Membership, Tenant, User
from app.db.session import set_platform_context
from app.services.audit import record, record_in_tenant
from app.workers.jobs import JobContext, handler

CENT = Decimal("0.01")
DEFAULT_SETTINGS: dict[str, Any] = {
    "seller": {
        "name": "[SELLER LEGAL NAME — set in ops settings]",
        "address": "[SELLER ADDRESS]",
        "email": "[BILLING EMAIL]",
        "tax_id": "",
    },
    "payment_instructions": "[PAYMENT INSTRUCTIONS — set in ops settings before issuing invoices]",
    "number_prefix": "RL",
    "payment_terms_days": 14,
    "grace_days": 14,  # [PROPOSED DEFAULT] SPEC §4.14
    "reminder_days": [3, 10],
}


def settings(db: Session) -> dict[str, Any]:
    row = db.get(OpsSetting, "billing")
    return {**DEFAULT_SETTINGS, **(row.value if row else {})}


def is_configured(cfg: dict[str, Any]) -> bool:
    texts = [
        cfg["seller"].get("name", ""),
        cfg["seller"].get("address", ""),
        cfg.get("payment_instructions", ""),
    ]
    return all(t and not t.startswith("[") for t in texts)


def save_settings(db: Session, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    row = db.get(OpsSetting, "billing")
    merged = {**settings(db), **values}
    if row is None:
        db.add(OpsSetting(key="billing", value=merged))
    else:
        row.value, row.updated_at = merged, utcnow()
    record(
        db,
        tenant_id=None,
        actor=ctx.actor,
        action="ops.billing_settings_changed",
        object_type="ops_settings",
        object_id="billing",
    )
    return merged


def get(db: Session, invoice_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> Invoice:
    q = select(Invoice).where(Invoice.id == invoice_id)
    if tenant_id is not None:
        q = q.where(Invoice.tenant_id == tenant_id)
    inv = db.execute(q).scalar_one_or_none()
    if inv is None:
        raise not_found("Invoice")
    return inv


def lines(db: Session, invoice: Invoice) -> list[InvoiceLine]:
    return list(
        db.execute(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice.id)
            .order_by(InvoiceLine.position)
        ).scalars()
    )


def _buyer(db: Session, tenant: Tenant) -> dict[str, str]:
    sub = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    ).scalar_one_or_none()
    return {
        "name": tenant.legal_name or tenant.name,
        "contact": sub.billing_contact_name if sub else "",
        "email": sub.billing_contact_email if sub else "",
    }


def save_draft(
    db: Session,
    ctx: Any,
    *,
    tenant_id: uuid.UUID,
    line_items: list[dict[str, Any]],
    period_start: date | None,
    period_end: date | None,
    notes: str,
    invoice: Invoice | None = None,
) -> Invoice:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise not_found("Organization")
    if invoice is not None and invoice.status != InvoiceStatus.DRAFT.value:
        raise conflict(
            "INVOICE_NOT_DRAFT", "Issued invoices cannot change. Void it and issue a new one."
        )
    if not line_items:
        raise AppError(422, "LINES_REQUIRED", "Add a line", "An invoice needs at least one line.")
    if invoice is None:
        invoice = Invoice(tenant_id=tenant_id, created_by=ctx.user.id)
        db.add(invoice)
        db.flush()
    else:
        for ln in lines(db, invoice):
            db.delete(ln)
        db.flush()
    total = Decimal(0)
    for i, item in enumerate(line_items):
        quantity, price = Decimal(item["quantity"]), Decimal(item["unit_price"])
        amount = (quantity * price).quantize(CENT)
        total += amount
        db.add(
            InvoiceLine(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                position=i,
                description=item["description"],
                quantity=quantity,
                unit_price=price,
                amount=amount,
            )
        )
    invoice.total, invoice.period_start, invoice.period_end, invoice.notes = (
        total,
        period_start,
        period_end,
        notes,
    )
    invoice.buyer = _buyer(db, tenant)
    db.flush()
    db.refresh(invoice)  # report stored NUMERIC values, same as later reads
    record(
        db,
        tenant_id=None,
        actor=ctx.actor,
        action="invoice.draft_saved",
        object_type="invoice",
        object_id=invoice.id,
        summary={"tenant_id": str(tenant_id), "total": format(total, "f")},
    )
    return invoice


def next_number(db: Session, year: int, prefix: str) -> str:
    value = db.execute(
        text(
            "INSERT INTO rl.invoice_sequences (year, last_value) VALUES (:y, 1) "
            "ON CONFLICT (year) DO UPDATE SET last_value = rl.invoice_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"y": year},
    ).scalar_one()
    return f"{prefix}-{year}-{int(value):04d}"


def issue(db: Session, ctx: Any, invoice: Invoice, issue_date: date | None = None) -> Invoice:
    if invoice.status != InvoiceStatus.DRAFT.value:
        raise conflict("INVOICE_NOT_DRAFT", "Only a draft can be issued.")
    cfg = settings(db)
    if not is_configured(cfg):
        raise AppError(
            422,
            "BILLING_NOT_CONFIGURED",
            "Seller details missing",
            "Set seller details and payment instructions in ops settings first.",
        )
    if not invoice.buyer.get("email"):
        raise AppError(
            422,
            "BILLING_CONTACT_MISSING",
            "No billing contact",
            "Add a billing contact email to the subscription first.",
        )
    day = issue_date or utcnow().date()
    invoice.number = next_number(db, day.year, cfg["number_prefix"])
    invoice.issue_date, invoice.due_date = day, day + timedelta(days=int(cfg["payment_terms_days"]))
    invoice.seller, invoice.payment_instructions = cfg["seller"], cfg["payment_instructions"]
    invoice.status, invoice.issued_at = InvoiceStatus.ISSUED.value, utcnow()
    db.flush()
    _store_pdf(db, invoice)
    _email(db, invoice, "issued")
    record(
        db,
        tenant_id=None,
        actor=ctx.actor,
        action="invoice.issued",
        object_type="invoice",
        object_id=invoice.id,
        summary={"number": invoice.number, "total": format(invoice.total, "f")},
    )
    record_in_tenant(
        db,
        invoice.tenant_id,
        actor=ctx.actor,
        action="invoice.issued",
        object_type="invoice",
        object_id=invoice.id,
        summary={"number": invoice.number},
    )
    return invoice


def render_pdf(db: Session, invoice: Invoice) -> bytes:
    from app.exports.writers import html_to_pdf, render_html

    return html_to_pdf(
        render_html(
            "invoice.html",
            inv=invoice,
            lines=lines(db, invoice),
            product=get_settings().product_name,
        )
    )


def _store_pdf(db: Session, invoice: Invoice) -> None:
    key = new_key(invoice.tenant_id, "invoices")
    get_storage().put(key, io.BytesIO(render_pdf(db, invoice)))
    invoice.storage_key = key


def _email(db: Session, invoice: Invoice, kind: str) -> None:
    from app.emails.service import queue_email

    to = invoice.buyer.get("email")
    if not to:
        return
    url = f"{get_settings().app_base_url}/app/settings/plan#invoices"
    subjects = {
        "issued": f"Invoice {invoice.number} from {invoice.seller.get('name', '')}",
        "reminder": f"Reminder: invoice {invoice.number} is due",
        "overdue": f"Invoice {invoice.number} is overdue",
    }
    text_body = (
        f"Invoice {invoice.number} for {invoice.total.quantize(CENT):,} USD is "
        f"{'due on ' + invoice.due_date.isoformat() if invoice.due_date else 'issued'}. "
        "Payment instructions are on the invoice. Owners and admins can download it in RebateLedger."
    )
    queue_email(
        db,
        to=to,
        template="generic",
        tenant_id=None,  # system email: operators queue it outside any tenant context
        context={
            "subject": subjects[kind],
            "text": text_body,
            "url": url,
            "link_label": "View invoice",
        },
    )
    invoice.emailed_at = utcnow()


def resend(db: Session, ctx: Any, invoice: Invoice) -> None:
    if invoice.status not in (InvoiceStatus.ISSUED.value, InvoiceStatus.PAID.value):
        raise conflict("INVOICE_NOT_ISSUED", "Only issued invoices can be sent.")
    _email(db, invoice, "issued")
    record(
        db,
        tenant_id=None,
        actor=ctx.actor,
        action="invoice.resent",
        object_type="invoice",
        object_id=invoice.id,
    )


def mark_paid(db: Session, ctx: Any, invoice: Invoice, paid_on: date, reference: str) -> Invoice:
    if invoice.status != InvoiceStatus.ISSUED.value:
        raise conflict("INVOICE_NOT_ISSUED", "Only an issued, unpaid invoice can be marked paid.")
    invoice.status, invoice.paid_on, invoice.payment_reference = (
        InvoiceStatus.PAID.value,
        paid_on,
        reference,
    )
    record(
        db,
        tenant_id=None,
        actor=ctx.actor,
        action="invoice.paid",
        object_type="invoice",
        object_id=invoice.id,
        summary={"number": invoice.number, "reference": reference[:100]},
    )
    _clear_past_due_if_settled(db, invoice.tenant_id)
    return invoice


def void(db: Session, ctx: Any, invoice: Invoice, reason: str) -> Invoice:
    if invoice.status == InvoiceStatus.DRAFT.value:
        db.delete(invoice)
        return invoice
    if invoice.status != InvoiceStatus.ISSUED.value:
        raise conflict("INVOICE_NOT_ISSUED", "Paid or void invoices cannot be voided.")
    invoice.status, invoice.voided_at, invoice.void_reason = (
        InvoiceStatus.VOID.value,
        utcnow(),
        reason,
    )
    record(
        db,
        tenant_id=None,
        actor=ctx.actor,
        action="invoice.voided",
        object_type="invoice",
        object_id=invoice.id,
        summary={"number": invoice.number, "reason": reason[:200]},
    )
    _clear_past_due_if_settled(db, invoice.tenant_id)
    return invoice


def reissue(db: Session, ctx: Any, invoice: Invoice) -> Invoice:
    """Corrections = void + reissue: a new draft copying the voided invoice's lines."""
    if invoice.status != InvoiceStatus.VOID.value:
        raise conflict("INVOICE_NOT_VOID", "Void the invoice before reissuing it.")
    draft = save_draft(
        db,
        ctx,
        tenant_id=invoice.tenant_id,
        line_items=[
            {"description": ln.description, "quantity": ln.quantity, "unit_price": ln.unit_price}
            for ln in lines(db, invoice)
        ],
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        notes=invoice.notes,
    )
    draft.replaces_id = invoice.id
    return draft


def _clear_past_due_if_settled(db: Session, tenant_id: uuid.UUID) -> None:
    sub = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if sub is None or sub.status != SubscriptionStatus.PAST_DUE.value:
        return
    today = utcnow().date()
    overdue = db.execute(
        select(Invoice.id).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.ISSUED.value,
            Invoice.due_date < today,
        )
    ).first()
    if overdue is None:
        sub.status, sub.past_due_since = SubscriptionStatus.ACTIVE.value, None


@handler("billing_lapse")
def _lapse(db: Session, job: JobContext) -> dict[str, Any]:
    """Daily, per tenant: overdue → past_due + reminder emails. Suspension stays a
    manual operator decision (SPEC §4.14 'MAY'); the console shows who is past grace."""
    assert job.tenant_id is not None
    cfg = settings(db)
    today = utcnow().date()
    sub = db.execute(
        select(Subscription).where(Subscription.tenant_id == job.tenant_id)
    ).scalar_one_or_none()
    invoices = list(
        db.execute(
            select(Invoice).where(
                Invoice.tenant_id == job.tenant_id, Invoice.status == InvoiceStatus.ISSUED.value
            )
        ).scalars()
    )
    sent = 0
    for inv in invoices:
        if inv.due_date is None:
            continue
        days_to_due = (inv.due_date - today).days
        if days_to_due in cfg["reminder_days"] or (
            days_to_due < 0
            and (inv.last_reminder_at is None or (today - inv.last_reminder_at.date()).days >= 7)
        ):
            _email(db, inv, "overdue" if days_to_due < 0 else "reminder")
            inv.last_reminder_at = utcnow()
            sent += 1
    overdue = [i for i in invoices if i.due_date and i.due_date < today]
    if (
        sub is not None
        and overdue
        and sub.status in (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PILOT.value)
    ):
        # Tenants may only read their subscription (RLS); this system job changes billing
        # metadata, so it lifts platform context for this one update and drops it again.
        set_platform_context(db, True)
        sub.status, sub.past_due_since = (
            SubscriptionStatus.PAST_DUE.value,
            min(i.due_date for i in overdue if i.due_date),
        )
        db.flush()
        set_platform_context(db, False)
    return {"reminders": sent, "overdue": len(overdue)}


def tenant_invoices(db: Session, tenant_id: uuid.UUID) -> list[Invoice]:
    return list(
        db.execute(
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id, Invoice.status != InvoiceStatus.DRAFT.value)
            .order_by(Invoice.issue_date.desc())
        ).scalars()
    )


def billing_admin_emails(db: Session, tenant_id: uuid.UUID) -> list[str]:
    return list(
        db.execute(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role.in_(["owner", "admin"]),
                Membership.status == "active",
            )
        ).scalars()
    )
