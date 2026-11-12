"""Operations console API (SPEC §4.15) and tenant billing endpoints (SPEC §4.14).

Every ``/ops`` route depends on ``PlatformAdminOnly`` (404 for everyone else). Tenant
business data is never returned here; support sessions go through the normal tenant
routes with a grant-limited permission set.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.api.deps import DB, Ctx, PlatformAdminOnly, Public, Requires
from app.api.schemas.common import DecimalStr, Email, In, MoneyIn, Name, Ok, Out
from app.core.errors import conflict
from app.core.permissions import Permission
from app.core.storage import get_storage
from app.db.models.business import Plan
from app.services import billing
from app.services import ops as svc

router = APIRouter(prefix="/api/v1", tags=["ops"])
Op = Annotated[Ctx, Depends(PlatformAdminOnly())]
Billing = Annotated[Ctx, Depends(Requires(Permission.VIEW_BILLING))]
Member = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
Status = Literal["pilot", "active", "past_due", "suspended", "cancelled"]


# --------------------------------------------------------------------------- schemas


class TenantRow(Out):
    id: uuid.UUID
    name: str
    is_demo: bool
    created_at: datetime
    plan: str | None
    status: str | None
    past_due_since: date | None
    members: int
    active_agreements: int
    purchase_lines: int
    open_claims: int
    last_import_at: datetime | None
    last_run_at: datetime | None


class SubscriptionOut(Out):
    plan_id: uuid.UUID
    status: str
    term_start: date | None
    term_end: date | None
    limit_overrides: dict[str, Any]
    billing_contact_name: str
    billing_contact_email: str
    past_due_since: date | None


class GrantOut(Out):
    id: uuid.UUID
    scope: str
    reason: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class TenantDetail(TenantRow):
    timezone: str
    subscription: SubscriptionOut | None
    members_list: list[dict[str, str]]
    grants: list[GrantOut]
    flags: dict[str, bool]


class TenantIn(In):
    name: Name
    timezone: Annotated[str, Field(max_length=60)] = "America/Chicago"
    plan_code: Annotated[str, Field(max_length=40)] = "pilot"
    owner_email: Email
    billing_email: Email | None = None


class SubscriptionIn(In):
    plan_code: Annotated[str | None, Field(max_length=40)] = None
    status: Status | None = None
    term_start: date | None = None
    term_end: date | None = None
    billing_contact_name: Annotated[str | None, Field(max_length=200)] = None
    billing_contact_email: Email | None = None
    limit_overrides: (
        dict[
            Literal[
                "max_active_agreements", "max_users", "max_import_rows_per_month", "max_storage_mb"
            ],
            int | None,
        ]
        | None
    ) = None


class FlagIn(In):
    key: Annotated[str, Field(max_length=60)]
    enabled: bool


class PlanOut(Out):
    id: uuid.UUID
    code: str
    name: str
    monthly_price: DecimalStr
    max_active_agreements: int | None
    max_users: int | None
    max_import_rows_per_month: int | None
    max_storage_mb: int | None
    features: dict[str, Any]
    is_public: bool
    sort_order: int


class PlanIn(In):
    code: Annotated[str, Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")]
    name: Name
    monthly_price: MoneyIn
    max_active_agreements: int | None = Field(default=None, ge=0)
    max_users: int | None = Field(default=None, ge=0)
    max_import_rows_per_month: int | None = Field(default=None, ge=0)
    max_storage_mb: int | None = Field(default=None, ge=0)
    is_public: bool = True
    sort_order: int = 0


class LineIn(In):
    description: Annotated[str, Field(min_length=1, max_length=300)]
    quantity: MoneyIn
    unit_price: MoneyIn


class InvoiceIn(In):
    tenant_id: uuid.UUID
    period_start: date | None = None
    period_end: date | None = None
    notes: Annotated[str, Field(max_length=2000)] = ""
    lines: Annotated[list[LineIn], Field(min_length=1, max_length=50)]


class InvoiceLineOut(Out):
    description: str
    quantity: DecimalStr
    unit_price: DecimalStr
    amount: DecimalStr


class InvoiceOut(Out):
    id: uuid.UUID
    tenant_id: uuid.UUID
    number: str | None
    status: str
    currency: str
    period_start: date | None
    period_end: date | None
    issue_date: date | None
    due_date: date | None
    buyer: dict[str, Any]
    total: DecimalStr
    paid_on: date | None
    payment_reference: str
    void_reason: str
    replaces_id: uuid.UUID | None
    emailed_at: datetime | None
    created_at: datetime


class InvoiceDetail(InvoiceOut):
    lines: list[InvoiceLineOut]
    seller: dict[str, Any]
    payment_instructions: str
    notes: str


class PaidIn(In):
    paid_on: date
    reference: Annotated[str, Field(min_length=1, max_length=200)]


class VoidIn(In):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class BillingSettingsIn(In):
    seller: (
        dict[Literal["name", "address", "email", "tax_id"], Annotated[str, Field(max_length=500)]]
        | None
    ) = None
    payment_instructions: Annotated[str | None, Field(max_length=2000)] = None
    number_prefix: Annotated[str | None, Field(pattern=r"^[A-Z]{2,6}$")] = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=120)
    grace_days: int | None = Field(default=None, ge=0, le=90)


class PilotIn(In):
    name: Name
    email: Email
    company: Name
    role: Annotated[str, Field(max_length=100)] = ""
    segment: Annotated[str, Field(max_length=60)] = ""
    erp_system: Annotated[str, Field(max_length=100)] = ""
    supplier_count: Annotated[str, Field(max_length=40)] = ""
    """Approximate number of supplier rebate agreements."""
    message: Annotated[str, Field(max_length=2000)] = ""
    consent: Literal[True]
    """The visitor agrees to be contacted about the pilot (required)."""
    website: Annotated[str, Field(max_length=200)] = ""
    """Honeypot: humans never fill it."""


class PilotOut(Out):
    id: uuid.UUID
    name: str
    email: str
    company: str
    role: str
    segment: str
    erp_system: str
    supplier_count: str
    message: str
    status: str
    operator_notes: str
    created_at: datetime


class PilotPatch(In):
    status: Literal["new", "contacted", "converted", "declined", "spam"] | None = None
    operator_notes: Annotated[str | None, Field(max_length=5000)] = None


class AnnouncementIn(In):
    message: Annotated[str, Field(min_length=1, max_length=500)]
    level: Literal["info", "warning"] = "info"
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementOut(Out):
    id: uuid.UUID
    message: str
    level: str
    starts_at: datetime
    ends_at: datetime | None


class JobOut(Out):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    type: str
    status: str
    attempts: int
    max_attempts: int
    error: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None


class JobsOverview(Out):
    counts: dict[str, int]
    jobs: list[JobOut]


class AuditOut(Out):
    id: uuid.UUID
    occurred_at: datetime
    actor_label: str
    action: str
    object_type: str
    object_id: str


class EnterIn(In):
    tenant_id: uuid.UUID


def _invoice_detail(ctx: Ctx, inv: Any) -> InvoiceDetail:
    return InvoiceDetail(
        **InvoiceOut.model_validate(inv).model_dump(),
        lines=[InvoiceLineOut.model_validate(ln) for ln in billing.lines(ctx.db, inv)],
        seller=inv.seller,
        payment_instructions=inv.payment_instructions,
        notes=inv.notes,
    )


# --------------------------------------------------------------------------- tenants


@router.get("/ops/tenants", response_model=list[TenantRow])
def ops_tenants(ctx: Op) -> list[TenantRow]:
    return [TenantRow.model_validate(t) for t in svc.list_tenants(ctx.db)]


@router.post("/ops/tenants", response_model=TenantRow, status_code=201)
def ops_create_tenant(body: TenantIn, ctx: Op) -> TenantRow:
    t = svc.create_tenant(
        ctx.db,
        ctx,
        name=body.name,
        timezone=body.timezone,
        plan_code=body.plan_code,
        owner_email=body.owner_email,
        billing_email=body.billing_email or "",
    )
    ctx.db.flush()
    return TenantRow.model_validate(svc.tenant_detail(ctx.db, t.id))


@router.get("/ops/tenants/{tenant_id}", response_model=TenantDetail)
def ops_tenant(tenant_id: uuid.UUID, ctx: Op) -> TenantDetail:
    return TenantDetail.model_validate(svc.tenant_detail(ctx.db, tenant_id))


@router.patch("/ops/tenants/{tenant_id}/subscription", response_model=SubscriptionOut)
def ops_subscription(tenant_id: uuid.UUID, body: SubscriptionIn, ctx: Op) -> SubscriptionOut:
    return SubscriptionOut.model_validate(
        svc.update_subscription(ctx.db, ctx, tenant_id, body.model_dump(exclude_unset=True))
    )


@router.put("/ops/tenants/{tenant_id}/flags", response_model=Ok)
def ops_flag(tenant_id: uuid.UUID, body: FlagIn, ctx: Op) -> Ok:
    svc.tenant_detail(ctx.db, tenant_id)
    svc.set_flag(ctx.db, ctx, tenant_id, body.key, body.enabled)
    return Ok()


@router.post("/ops/support/enter", response_model=Ok)
def ops_enter(body: EnterIn, ctx: Op) -> Ok:
    svc.enter_support(ctx.db, ctx, body.tenant_id)
    return Ok()


@router.post("/ops/support/exit", response_model=Ok)
def ops_exit(ctx: Op) -> Ok:
    svc.exit_support(ctx.db, ctx)
    return Ok()


# --------------------------------------------------------------------------- plans


@router.get("/ops/plans", response_model=list[PlanOut])
def ops_plans(ctx: Op) -> list[PlanOut]:
    from sqlalchemy import select

    return [
        PlanOut.model_validate(p)
        for p in ctx.db.execute(select(Plan).order_by(Plan.sort_order)).scalars()
    ]


@router.post("/ops/plans", response_model=PlanOut, status_code=201)
def ops_create_plan(body: PlanIn, ctx: Op) -> PlanOut:
    return PlanOut.model_validate(svc.save_plan(ctx.db, ctx, body.model_dump()))


@router.patch("/ops/plans/{plan_id}", response_model=PlanOut)
def ops_update_plan(plan_id: uuid.UUID, body: PlanIn, ctx: Op) -> PlanOut:
    return PlanOut.model_validate(svc.save_plan(ctx.db, ctx, body.model_dump(), plan_id))


# --------------------------------------------------------------------------- invoices


@router.get("/ops/invoices", response_model=list[InvoiceOut])
def ops_invoices(ctx: Op, tenant_id: uuid.UUID | None = None) -> list[InvoiceOut]:
    from sqlalchemy import select

    from app.db.models.billing import Invoice

    q = select(Invoice).order_by(Invoice.created_at.desc()).limit(500)
    if tenant_id:
        q = q.where(Invoice.tenant_id == tenant_id)
    return [InvoiceOut.model_validate(i) for i in ctx.db.execute(q).scalars()]


@router.post("/ops/invoices", response_model=InvoiceDetail, status_code=201)
def ops_create_invoice(body: InvoiceIn, ctx: Op) -> InvoiceDetail:
    inv = billing.save_draft(
        ctx.db,
        ctx,
        tenant_id=body.tenant_id,
        line_items=[ln.model_dump() for ln in body.lines],
        period_start=body.period_start,
        period_end=body.period_end,
        notes=body.notes,
    )
    return _invoice_detail(ctx, inv)


@router.get("/ops/invoices/{invoice_id}", response_model=InvoiceDetail)
def ops_invoice(invoice_id: uuid.UUID, ctx: Op) -> InvoiceDetail:
    return _invoice_detail(ctx, billing.get(ctx.db, invoice_id))


@router.put("/ops/invoices/{invoice_id}", response_model=InvoiceDetail)
def ops_update_invoice(invoice_id: uuid.UUID, body: InvoiceIn, ctx: Op) -> InvoiceDetail:
    inv = billing.get(ctx.db, invoice_id)
    if inv.tenant_id != body.tenant_id:
        raise conflict("INVOICE_TENANT_FIXED", "An invoice cannot move to another organization.")
    billing.save_draft(
        ctx.db,
        ctx,
        tenant_id=body.tenant_id,
        line_items=[ln.model_dump() for ln in body.lines],
        period_start=body.period_start,
        period_end=body.period_end,
        notes=body.notes,
        invoice=inv,
    )
    return _invoice_detail(ctx, inv)


@router.post("/ops/invoices/{invoice_id}/issue", response_model=InvoiceDetail)
def ops_issue(invoice_id: uuid.UUID, ctx: Op) -> InvoiceDetail:
    return _invoice_detail(ctx, billing.issue(ctx.db, ctx, billing.get(ctx.db, invoice_id)))


@router.post("/ops/invoices/{invoice_id}/paid", response_model=InvoiceDetail)
def ops_paid(invoice_id: uuid.UUID, body: PaidIn, ctx: Op) -> InvoiceDetail:
    return _invoice_detail(
        ctx,
        billing.mark_paid(
            ctx.db, ctx, billing.get(ctx.db, invoice_id), body.paid_on, body.reference
        ),
    )


@router.post("/ops/invoices/{invoice_id}/void", response_model=Ok)
def ops_void(invoice_id: uuid.UUID, body: VoidIn, ctx: Op) -> Ok:
    billing.void(ctx.db, ctx, billing.get(ctx.db, invoice_id), body.reason)
    return Ok()


@router.post("/ops/invoices/{invoice_id}/reissue", response_model=InvoiceDetail, status_code=201)
def ops_reissue(invoice_id: uuid.UUID, ctx: Op) -> InvoiceDetail:
    return _invoice_detail(ctx, billing.reissue(ctx.db, ctx, billing.get(ctx.db, invoice_id)))


@router.post("/ops/invoices/{invoice_id}/resend", response_model=Ok)
def ops_resend(invoice_id: uuid.UUID, ctx: Op) -> Ok:
    billing.resend(ctx.db, ctx, billing.get(ctx.db, invoice_id))
    return Ok()


@router.get("/ops/invoices/{invoice_id}/pdf")
def ops_invoice_pdf(invoice_id: uuid.UUID, ctx: Op) -> StreamingResponse:
    return _pdf(ctx, billing.get(ctx.db, invoice_id))


@router.get("/ops/billing-settings", response_model=dict[str, Any])
def ops_billing_settings(ctx: Op) -> dict[str, Any]:
    return {
        **billing.settings(ctx.db),
        "configured": billing.is_configured(billing.settings(ctx.db)),
    }


@router.put("/ops/billing-settings", response_model=dict[str, Any])
def ops_save_billing_settings(body: BillingSettingsIn, ctx: Op) -> dict[str, Any]:
    return billing.save_settings(ctx.db, ctx, body.model_dump(exclude_none=True))


# --------------------------------------------------------------------------- inbox, flags, announcements, jobs, audit


@router.get("/ops/pilot-requests", response_model=list[PilotOut])
def ops_pilot_requests(ctx: Op) -> list[PilotOut]:
    from sqlalchemy import select

    from app.db.models.billing import PilotRequest

    return [
        PilotOut.model_validate(p)
        for p in ctx.db.execute(
            select(PilotRequest).order_by(PilotRequest.created_at.desc()).limit(500)
        ).scalars()
    ]


@router.patch("/ops/pilot-requests/{request_id}", response_model=PilotOut)
def ops_update_pilot(request_id: uuid.UUID, body: PilotPatch, ctx: Op) -> PilotOut:
    return PilotOut.model_validate(
        svc.update_pilot_request(ctx.db, ctx, request_id, body.status, body.operator_notes)
    )


@router.get("/ops/feature-flags", response_model=dict[str, str])
def ops_flags_catalog(ctx: Op) -> dict[str, str]:
    return svc.FLAGS


@router.get("/ops/announcements", response_model=list[AnnouncementOut])
def ops_announcements(ctx: Op) -> list[AnnouncementOut]:
    from sqlalchemy import select

    from app.db.models.billing import Announcement

    return [
        AnnouncementOut.model_validate(a)
        for a in ctx.db.execute(
            select(Announcement).order_by(Announcement.created_at.desc()).limit(100)
        ).scalars()
    ]


@router.post("/ops/announcements", response_model=AnnouncementOut, status_code=201)
def ops_create_announcement(body: AnnouncementIn, ctx: Op) -> AnnouncementOut:
    return AnnouncementOut.model_validate(
        svc.save_announcement(ctx.db, ctx, body.model_dump(exclude_none=True))
    )


@router.patch("/ops/announcements/{announcement_id}", response_model=AnnouncementOut)
def ops_update_announcement(
    announcement_id: uuid.UUID, body: AnnouncementIn, ctx: Op
) -> AnnouncementOut:
    return AnnouncementOut.model_validate(
        svc.save_announcement(ctx.db, ctx, body.model_dump(exclude_unset=True), announcement_id)
    )


@router.get("/ops/jobs", response_model=JobsOverview)
def ops_jobs(
    ctx: Op,
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "dead"] | None = None,
) -> JobsOverview:
    return JobsOverview.model_validate(svc.job_overview(ctx.db, status))


@router.post("/ops/jobs/{job_id}/retry", response_model=Ok)
def ops_retry_job(job_id: uuid.UUID, ctx: Op) -> Ok:
    svc.retry_job(ctx.db, ctx, job_id)
    return Ok()


@router.get("/ops/audit", response_model=list[AuditOut])
def ops_audit(ctx: Op) -> list[AuditOut]:
    return [AuditOut.model_validate(e) for e in svc.ops_audit(ctx.db)]


# --------------------------------------------------------------------------- tenant-facing


def _pdf(ctx: Ctx, inv: Any) -> StreamingResponse:
    if inv.storage_key is None:
        raise conflict("INVOICE_NOT_ISSUED", "Only issued invoices have a PDF.")
    stream = get_storage().open(inv.storage_key)

    def chunks() -> Any:
        with stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{inv.number}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/billing/invoices", response_model=list[InvoiceOut])
def tenant_invoices(ctx: Billing) -> list[InvoiceOut]:
    return [InvoiceOut.model_validate(i) for i in billing.tenant_invoices(ctx.db, ctx.tenant_uuid)]


@router.get("/billing/invoices/{invoice_id}/pdf")
def tenant_invoice_pdf(invoice_id: uuid.UUID, ctx: Billing) -> StreamingResponse:
    inv = billing.get(ctx.db, invoice_id, ctx.tenant_uuid)
    if inv.status == "draft":
        from app.core.errors import not_found

        raise not_found("Invoice")
    return _pdf(ctx, inv)


@router.get("/announcements", response_model=list[AnnouncementOut])
def announcements(ctx: Member) -> list[AnnouncementOut]:
    return [AnnouncementOut.model_validate(a) for a in svc.active_announcements(ctx.db)]


@router.get("/feature-flags", response_model=dict[str, bool])
def feature_flags(ctx: Member) -> dict[str, bool]:
    return svc.tenant_flags(ctx.db, ctx.tenant_uuid)


@router.post(
    "/pilot-requests", response_model=Ok, status_code=202, dependencies=[Depends(Public())]
)
def pilot_request(body: PilotIn, request: Request, db: DB) -> Ok:
    """Public 'request a pilot' form. Same answer whether stored or dropped as spam."""
    if not body.website:
        svc.submit_pilot_request(
            db, request.client.host if request.client else "", body.model_dump(exclude={"website"})
        )
    return Ok()


class PublicPlan(Out):
    code: str
    name: str
    monthly_price: DecimalStr
    max_active_agreements: int | None
    max_users: int | None
    max_import_rows_per_month: int | None


@router.get("/public/plans", response_model=list[PublicPlan], dependencies=[Depends(Public())])
def public_plans(db: DB) -> list[PublicPlan]:
    """Pricing page: public plans only (prices are [PROPOSED DEFAULT] until confirmed)."""
    return [PublicPlan.model_validate(p) for p in svc.public_plans(db)]
