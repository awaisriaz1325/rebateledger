"""Operations console services (SPEC §4.15). Callers run in platform context.

Platform admins see tenant metadata, plans, subscriptions, invoices and aggregate usage
only. Tenant business tables have no platform RLS policy, so business data is unreadable
here; the only way in is a tenant-granted support session (``enter_support``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.clock import utcnow
from app.core.errors import AppError, conflict, not_found
from app.db.models.billing import Announcement, FeatureFlag, Invoice, PilotRequest
from app.db.models.business import Plan, Subscription, SubscriptionStatus
from app.db.models.identity import Job, JobStatus, Membership, SupportAccessGrant, Tenant, User
from app.db.session import set_platform_context, set_tenant_context
from app.services import org as org_svc
from app.services.audit import Actor, record, record_in_tenant

FLAGS = {
    "beta_reports": "Early access to new reports",
    "large_imports": "Import files above the standard size limit",
}


def actor(ctx: Any) -> Actor:
    return Actor("platform_admin", ctx.user.id, ctx.user.email)


def _audit(
    db: Session,
    ctx: Any,
    action: str,
    object_type: str,
    object_id: Any,
    summary: dict[str, Any] | None = None,
) -> None:
    record(
        db,
        tenant_id=None,
        actor=actor(ctx),
        action=action,
        object_type=object_type,
        object_id=object_id,
        summary=summary,
    )


# --------------------------------------------------------------------------- tenants


def usage(db: Session) -> dict[uuid.UUID, dict[str, Any]]:
    rows = db.execute(text("SELECT * FROM rl.tenant_usage()")).mappings().all()
    return {r["tenant_id"]: dict(r) for r in rows}


def list_tenants(db: Session) -> list[dict[str, Any]]:
    use = usage(db)
    members = dict(
        db.execute(
            select(Membership.tenant_id, func.count())
            .where(Membership.status == "active")
            .group_by(Membership.tenant_id)
        ).all()
    )
    out = []
    for t, sub, plan in db.execute(
        select(Tenant, Subscription, Plan)
        .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .order_by(Tenant.name)
    ).all():
        u = use.get(t.id, {})
        out.append(
            {
                "id": t.id,
                "name": t.name,
                "is_demo": t.is_demo,
                "created_at": t.created_at,
                "plan": plan.name if plan else None,
                "status": sub.status if sub else None,
                "past_due_since": sub.past_due_since if sub else None,
                "members": members.get(t.id, 0),
                "active_agreements": int(u.get("active_agreements") or 0),
                "purchase_lines": int(u.get("purchase_lines") or 0),
                "open_claims": int(u.get("open_claims") or 0),
                "last_import_at": u.get("last_import_at"),
                "last_run_at": u.get("last_run_at"),
            }
        )
    return out


def tenant_detail(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    row = next((t for t in list_tenants(db) if t["id"] == tenant_id), None)
    if row is None:
        raise not_found("Organization")
    tenant = db.get(Tenant, tenant_id)
    sub = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()
    members = db.execute(
        select(User.name, User.email, Membership.role, Membership.status)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant_id)
        .order_by(User.name)
    ).all()
    grants = list(
        db.execute(
            select(SupportAccessGrant)
            .where(SupportAccessGrant.tenant_id == tenant_id)
            .order_by(SupportAccessGrant.created_at.desc())
            .limit(20)
        ).scalars()
    )
    flags = {
        f.key: f.enabled
        for f in db.execute(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id)).scalars()
    }
    assert tenant is not None
    return {
        **row,
        "timezone": tenant.timezone,
        "subscription": sub,
        "members_list": [{"name": n, "email": e, "role": r, "status": s} for n, e, r, s in members],
        "grants": grants,
        "flags": {k: flags.get(k, False) for k in FLAGS},
    }


def create_tenant(
    db: Session,
    ctx: Any,
    *,
    name: str,
    timezone: str,
    plan_code: str,
    owner_email: str,
    billing_email: str,
) -> Tenant:
    plan = db.execute(select(Plan).where(Plan.code == plan_code)).scalar_one_or_none()
    if plan is None:
        raise AppError(422, "PLAN_UNKNOWN", "Unknown plan", "Choose a plan from the catalog.")
    tenant = org_svc.create_tenant(
        db, name=name, timezone=timezone, fiscal_year_start_month=1, actor=actor(ctx)
    )
    db.add(
        Subscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status=SubscriptionStatus.PILOT.value,
            term_start=utcnow().date(),
            billing_contact_email=billing_email or owner_email,
        )
    )
    org_svc.invite_first_owner(db, tenant, owner_email, actor(ctx))
    set_tenant_context(db, None)
    set_platform_context(db, True)
    _audit(db, ctx, "ops.tenant_created", "tenant", tenant.id, {"name": name, "plan": plan_code})
    return tenant


def update_subscription(
    db: Session, ctx: Any, tenant_id: uuid.UUID, values: dict[str, Any]
) -> Subscription:
    sub = db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if sub is None:
        raise not_found("Subscription")
    before = {"status": sub.status, "plan_id": str(sub.plan_id)}
    if "plan_code" in values:
        plan = db.execute(
            select(Plan).where(Plan.code == values.pop("plan_code"))
        ).scalar_one_or_none()
        if plan is None:
            raise AppError(422, "PLAN_UNKNOWN", "Unknown plan", "Choose a plan from the catalog.")
        sub.plan_id = plan.id
    for key, value in values.items():
        setattr(sub, key, value)
    if sub.status == SubscriptionStatus.PAST_DUE.value and sub.past_due_since is None:
        sub.past_due_since = utcnow().date()
    if sub.status in (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PILOT.value):
        sub.past_due_since = None
    _audit(
        db,
        ctx,
        "ops.subscription_changed",
        "tenant",
        tenant_id,
        {"before": before, "after": {"status": sub.status, "plan_id": str(sub.plan_id)}},
    )
    record_in_tenant(
        db,
        tenant_id,
        actor=actor(ctx),
        action="subscription.changed",
        object_type="subscription",
        object_id=sub.id,
        summary={"status": sub.status},
    )
    return sub


def set_flag(db: Session, ctx: Any, tenant_id: uuid.UUID, key: str, enabled: bool) -> None:
    if key not in FLAGS:
        raise AppError(422, "FLAG_UNKNOWN", "Unknown feature flag", "Choose a defined flag.")
    flag = db.execute(
        select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == key)
    ).scalar_one_or_none()
    if flag is None:
        db.add(FeatureFlag(tenant_id=tenant_id, key=key, enabled=enabled))
    else:
        flag.enabled, flag.updated_at = enabled, utcnow()
    _audit(db, ctx, "ops.flag_changed", "tenant", tenant_id, {"flag": key, "enabled": enabled})


def tenant_flags(db: Session, tenant_id: uuid.UUID) -> dict[str, bool]:
    rows = {
        f.key: f.enabled
        for f in db.execute(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id)).scalars()
    }
    return {k: rows.get(k, False) for k in FLAGS}


# --------------------------------------------------------------------------- plans


def save_plan(
    db: Session, ctx: Any, values: dict[str, Any], plan_id: uuid.UUID | None = None
) -> Plan:
    if plan_id is None:
        if db.execute(select(Plan.id).where(Plan.code == values["code"])).first():
            raise conflict("PLAN_CODE_TAKEN", "Another plan uses this code.")
        plan = Plan(**values)
        db.add(plan)
        db.flush()
    else:
        plan = db.get(Plan, plan_id)  # type: ignore[assignment]
        if plan is None:
            raise not_found("Plan")
        values.pop("code", None)  # codes are stable identifiers
        for k, v in values.items():
            setattr(plan, k, v)
    _audit(
        db,
        ctx,
        "ops.plan_saved",
        "plan",
        plan.id,
        {"code": plan.code, "price": format(plan.monthly_price, "f")},
    )
    return plan


# --------------------------------------------------------------------------- pilot requests


def submit_pilot_request(db: Session, ip: str, values: dict[str, Any]) -> PilotRequest:
    """Public form (marketing site). Rate limited; stored for the operator inbox only."""
    ratelimit.hit("pilot-ip", ip or "unknown", 5, 3600)
    ratelimit.hit("pilot-email", values["email"].lower(), 3, 86400)
    set_platform_context(db, True)
    req = PilotRequest(**values)
    db.add(req)
    db.flush()
    _pilot_emails(db, req)
    return req


def _pilot_emails(db: Session, req: PilotRequest) -> None:
    """Confirmation to the requester and a notice to the operator inbox (SPEC §4.16).
    Queued as system emails; the request content is not repeated to the requester."""
    from app.core.config import get_settings
    from app.emails.service import queue_email

    settings = get_settings()
    queue_email(
        db,
        to=req.email,
        template="generic",
        context={
            "subject": f"We received your {settings.product_name} pilot request",
            "text": f"Hi {req.name}, thanks for your interest. We will reply within two business days to arrange a short call. If you did not submit this request, you can ignore this email.",
            "url": "",
            "link_label": "",
        },
    )
    if settings.ops_notify_email:
        queue_email(
            db,
            to=settings.ops_notify_email,
            template="generic",
            context={
                "subject": f"New pilot request: {req.company}",
                "text": f"{req.name} ({req.role or 'role not given'}) at {req.company} asked for a pilot. Segment: {req.segment or '—'}; ERP: {req.erp_system or '—'}; agreements: {req.supplier_count or '—'}.",
                "url": f"{settings.app_base_url}/ops/requests",
                "link_label": "Open the inbox",
            },
        )


def public_plans(db: Session) -> list[Plan]:
    """Plans are readable by everyone (RLS policy read_all)."""
    return list(
        db.execute(select(Plan).where(Plan.is_public.is_(True)).order_by(Plan.sort_order)).scalars()
    )


def update_pilot_request(
    db: Session, ctx: Any, request_id: uuid.UUID, status: str | None, notes: str | None
) -> PilotRequest:
    req = db.get(PilotRequest, request_id)
    if req is None:
        raise not_found("Request")
    if status is not None:
        req.status = status
    if notes is not None:
        req.operator_notes = notes
    _audit(db, ctx, "ops.pilot_request_updated", "pilot_request", req.id, {"status": req.status})
    return req


# --------------------------------------------------------------------------- announcements


def active_announcements(db: Session) -> list[Announcement]:
    now = utcnow()
    return list(
        db.execute(
            select(Announcement)
            .where(
                Announcement.starts_at <= now,
                (Announcement.ends_at.is_(None)) | (Announcement.ends_at > now),
            )
            .order_by(Announcement.starts_at.desc())
        ).scalars()
    )


def save_announcement(
    db: Session, ctx: Any, values: dict[str, Any], announcement_id: uuid.UUID | None = None
) -> Announcement:
    if announcement_id is None:
        a = Announcement(**values)
        db.add(a)
        db.flush()
    else:
        found = db.get(Announcement, announcement_id)
        if found is None:
            raise not_found("Announcement")
        a = found
        for k, v in values.items():
            setattr(a, k, v)
    _audit(db, ctx, "ops.announcement_saved", "announcement", a.id)
    return a


# --------------------------------------------------------------------------- jobs


def job_overview(db: Session, status: str | None) -> dict[str, Any]:
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    q = select(Job).order_by(Job.created_at.desc()).limit(100)
    if status:
        q = q.where(Job.status == status)
    return {
        "counts": {s.value: int(counts.get(s.value, 0)) for s in JobStatus},
        "jobs": list(db.execute(q).scalars()),
    }


def retry_job(db: Session, ctx: Any, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise not_found("Job")
    if job.status not in (JobStatus.DEAD.value, JobStatus.FAILED.value):
        raise conflict("JOB_NOT_FAILED", "Only failed jobs can be retried.")
    job.status, job.attempts, job.error, job.finished_at = JobStatus.QUEUED.value, 0, None, None
    # Same hand-off as enqueue(): dispatched to the broker after this transaction commits.
    db.info.setdefault("after_commit_jobs", []).append((job.id, job.tenant_id))
    _audit(db, ctx, "ops.job_retried", "job", job.id, {"type": job.type})
    return job


# --------------------------------------------------------------------------- support access


def enter_support(db: Session, ctx: Any, tenant_id: uuid.UUID) -> SupportAccessGrant:
    grant = (
        db.execute(
            select(SupportAccessGrant)
            .where(
                SupportAccessGrant.tenant_id == tenant_id,
                SupportAccessGrant.revoked_at.is_(None),
                SupportAccessGrant.expires_at > utcnow(),
            )
            .order_by(SupportAccessGrant.expires_at.desc())
        )
        .scalars()
        .first()
    )
    if grant is None:
        raise AppError(
            403,
            "SUPPORT_ACCESS_REQUIRED",
            "No support access",
            "This organization has not granted support access (or it expired).",
        )
    ctx.session.active_tenant_id = tenant_id
    _audit(
        db,
        ctx,
        "ops.support_entered",
        "tenant",
        tenant_id,
        {"grant_id": str(grant.id), "scope": grant.scope},
    )
    record_in_tenant(
        db,
        tenant_id,
        actor=Actor("platform_admin", ctx.user.id, f"support:{ctx.user.email}"),
        action="support.entered",
        object_type="support_grant",
        object_id=grant.id,
        summary={"scope": grant.scope},
    )
    return grant


def exit_support(db: Session, ctx: Any) -> None:
    ctx.session.active_tenant_id = None
    _audit(db, ctx, "ops.support_exited", "session", ctx.session.id)


def ops_audit(db: Session, limit: int = 200) -> list[Any]:
    from app.db.models.identity import AuditEvent

    return list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id.is_(None))
            .order_by(AuditEvent.occurred_at.desc())
            .limit(limit)
        ).scalars()
    )


def overdue_invoices(db: Session) -> list[Invoice]:
    today = utcnow().date()
    return list(
        db.execute(
            select(Invoice).where(Invoice.status == "issued", Invoice.due_date < today)
        ).scalars()
    )
