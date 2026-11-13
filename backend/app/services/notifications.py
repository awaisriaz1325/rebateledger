"""In-app notifications + alert emails with preferences and signed unsubscribe (SPEC §4.11)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.clock import today_in, utcnow
from app.core.config import get_settings
from app.core.security import sign, unsign
from app.db.models.identity import (
    DigestSend,
    Membership,
    MembershipStatus,
    Notification,
    NotificationPreference,
    Role,
    Tenant,
    User,
)
from app.emails.service import queue_email
from app.workers.jobs import JobContext, handler

ALERT_TYPES = {
    "run_finished": "Calculation run finished",
    "missing_detected": "New missing rebates detected",
    "claim_follow_up": "Claim follow-up due",
    "claim_aging": "Claim aging",
    "tier_proximity": "Close to the next tier",
    "import_finished": "Import finished",
    "export_ready": "Export ready",
    "weekly_digest": "Weekly tier opportunities",
    "spa_deadline": "SPA claim deadlines",
}
UNSUBSCRIBE_TTL = 365 * 24 * 3600


def preferences(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, tuple[bool, bool]]:
    prefs = dict.fromkeys(ALERT_TYPES, (True, True))
    for p in db.execute(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == tenant_id, NotificationPreference.user_id == user_id
        )
    ).scalars():
        if p.type in prefs:
            prefs[p.type] = (p.in_app_enabled, p.email_enabled)
    return prefs


def set_preference(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    type_: str,
    *,
    in_app: bool | None = None,
    email: bool | None = None,
) -> None:
    row = db.execute(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == tenant_id,
            NotificationPreference.user_id == user_id,
            NotificationPreference.type == type_,
        )
    ).scalar_one_or_none()
    if row is None:
        row = NotificationPreference(
            tenant_id=tenant_id,
            user_id=user_id,
            type=type_,
            in_app_enabled=True,
            email_enabled=True,
        )
        db.add(row)
    if in_app is not None:
        row.in_app_enabled = in_app
    if email is not None:
        row.email_enabled = email
    db.flush()


def unsubscribe_url(tenant_id: uuid.UUID, user_id: uuid.UUID, type_: str) -> str:
    token = sign(
        "unsubscribe", {"t": str(tenant_id), "u": str(user_id), "k": type_}, UNSUBSCRIBE_TTL
    )
    return f"{get_settings().app_base_url}/unsubscribe?token={token}"


def apply_unsubscribe(db: Session, token: str) -> str | None:
    data = unsign("unsubscribe", token)
    if not data or data.get("k") not in ALERT_TYPES:
        return None
    from app.db.session import set_tenant_context

    tenant_id = uuid.UUID(data["t"])
    set_tenant_context(db, tenant_id)
    set_preference(db, tenant_id, uuid.UUID(data["u"]), data["k"], email=False)
    return ALERT_TYPES[data["k"]]


def notify(
    db: Session,
    tenant_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    type_: str,
    title: str,
    body: str,
    link: str = "",
) -> int:
    sent = 0
    for uid in dict.fromkeys(user_ids):
        in_app, email = preferences(db, tenant_id, uid).get(type_, (True, True))
        if in_app:
            db.add(
                Notification(
                    tenant_id=tenant_id,
                    user_id=uid,
                    type=type_,
                    title=title[:200],
                    body=body,
                    link=link[:300],
                )
            )
            sent += 1
        if email:
            user = db.get(User, uid)
            if user is not None and user.disabled_at is None:
                queue_email(
                    db,
                    to=user.email,
                    template="generic",
                    tenant_id=tenant_id,
                    transactional=False,
                    context={
                        "subject": title,
                        "text": body,
                        "url": f"{get_settings().app_base_url}{link}" if link else "",
                        "link_label": "Open in RebateLedger",
                        "unsubscribe_url": unsubscribe_url(tenant_id, uid, type_),
                    },
                )
    db.flush()
    return sent


def managers(db: Session, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.execute(
            select(Membership.user_id).where(
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE.value,
                Membership.role.in_([Role.OWNER.value, Role.ADMIN.value]),
            )
        ).scalars()
    )


def notify_run_finished(db: Session, run: Any) -> None:
    from app.db.models.runs import ReconciliationItem

    missing = db.execute(
        select(ReconciliationItem.id).where(
            ReconciliationItem.run_id == run.id, ReconciliationItem.status == "MISSING"
        )
    ).all()
    link = f"/app/runs/{run.id}"
    if run.started_by:
        notify(
            db,
            run.tenant_id,
            [run.started_by],
            "run_finished",
            f"Run {run.number} finished",
            f"{run.totals.get('results', 0)} agreement-periods calculated; {run.totals.get('needs_review', 0)} need review.",
            link,
        )
    if missing:
        notify(
            db,
            run.tenant_id,
            managers(db, run.tenant_id),
            "missing_detected",
            f"{len(missing)} missing rebate(s) in run {run.number}",
            "Expected rebates with no credit after the due date were found. Review the discrepancy queue.",
            "/app/discrepancies?status=MISSING",
        )


def unread_count(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return int(
        db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
        ).scalar_one()
    )


def mark_read(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID] | None
) -> int:
    q = update(Notification).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    )
    if ids is not None:
        q = q.where(Notification.id.in_(ids))
    return int(db.execute(q.values(read_at=utcnow())).rowcount)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- daily jobs


@handler("claim_reminders")
def _claim_reminders(db: Session, job: JobContext) -> dict[str, Any]:
    """Follow-up date reached, and 30/60/90-day aging since submission (SPEC §4.8)."""
    from app.db.models.runs import TERMINAL_CLAIM, Claim

    assert job.tenant_id is not None
    tenant = db.get(Tenant, job.tenant_id)
    assert tenant is not None
    today = today_in(tenant.timezone)
    sent = 0
    claims = db.execute(
        select(Claim).where(
            Claim.tenant_id == tenant.id, Claim.status.not_in([s.value for s in TERMINAL_CLAIM])
        )
    ).scalars()
    for c in claims:
        target = [c.assignee_id or c.created_by]
        target_ids = [t for t in target if t is not None]
        last = dict(c.last_reminder)
        if (
            c.follow_up_date
            and c.follow_up_date <= today
            and last.get("follow_up") != c.follow_up_date.isoformat()
        ):
            notify(
                db,
                tenant.id,
                target_ids,
                "claim_follow_up",
                f"Follow up claim CL-{c.number:04d}",
                f"The follow-up date {c.follow_up_date:%b %d, %Y} for “{c.title}” has arrived.",
                f"/app/claims/{c.id}",
            )
            last["follow_up"] = c.follow_up_date.isoformat()
            sent += 1
        if c.submitted_at:
            age = (today - c.submitted_at.astimezone(ZoneInfo(tenant.timezone)).date()).days
            for threshold in (90, 60, 30):
                if age >= threshold:
                    if last.get("aging", 0) < threshold:
                        notify(
                            db,
                            tenant.id,
                            target_ids,
                            "claim_aging",
                            f"Claim CL-{c.number:04d} is {threshold}+ days old",
                            f"“{c.title}” was submitted {age} days ago and is still open.",
                            f"/app/claims/{c.id}",
                        )
                        last["aging"] = threshold
                        sent += 1
                    break
        c.last_reminder = last
    return {"sent": sent}


@handler("tier_alerts")
def _tier_alerts(db: Session, job: JobContext) -> dict[str, Any]:
    """Within X% of the next tier with ≤ Y days left (SPEC §4.9; tenant defaults 10% / 21 days)."""
    from app.services.tiers import tracker

    assert job.tenant_id is not None
    tenant = db.get(Tenant, job.tenant_id)
    assert tenant is not None
    sent = 0
    for row in tracker(db, tenant):
        if row.gap is None or row.next_threshold is None or row.next_threshold == 0:
            continue
        close = row.gap <= row.next_threshold * tenant.tier_alert_pct
        if close and row.days_remaining <= tenant.tier_alert_days:
            key = f"tier:{row.agreement_id}:{row.period_start}:{row.next_tier}"
            already = db.execute(
                select(Notification.id).where(
                    Notification.tenant_id == tenant.id,
                    Notification.type == "tier_proximity",
                    Notification.link.like(f"%{key}%"),
                )
            ).first()
            if already:
                continue
            notify(
                db,
                tenant.id,
                managers(db, tenant.id),
                "tier_proximity",
                f"{row.agreement_name}: {row.gap:,.2f} to tier {row.next_tier}",
                f"With {row.days_remaining} days left, the next tier is {row.gap:,.2f} away (estimate). Potential additional rebate: {row.potential_additional or 0:,.2f}.",
                f"/app/tiers?focus={key}",
            )
            sent += 1
    return {"sent": sent}


# --------------------------------------------------------------------------- weekly digest

DIGEST_ROLES = (Role.OWNER.value, Role.ADMIN.value, Role.ANALYST.value)
DIGEST_TOP = 5


def _measure_text(kind: str, value: Any) -> str:
    return f"${value:,.2f}" if kind == "spend" else f"{value:,.2f} units"


def digest_text(items: list[Any]) -> str:
    """Plain-text digest body. Agreement names and estimates only; never purchase rows."""
    lines = ["Where more purchases this period would unlock more rebate (estimates):", ""]
    for i, o in enumerate(items, 1):
        gain = (
            f" for about ${o.potential_additional:,.2f} more rebate"
            if o.potential_additional is not None
            else ""
        )
        lines.append(
            f"{i}. {o.supplier_name} — {o.agreement_name}: {_measure_text(o.measure_kind, o.gap)} "
            f"more by {o.period_end:%b %d, %Y} ({o.days_remaining} days) reaches tier {o.next_tier}{gain}."
        )
        lines.append(
            f"   Needed per day: {_measure_text(o.measure_kind, o.required_daily)}; "
            f"current pace: {_measure_text(o.measure_kind, o.current_daily)} per day."
        )
    lines += [
        "",
        "Estimates use the purchases imported so far. Check the tier tracker before acting.",
    ]
    return "\n".join(lines)


@handler("weekly_digest")
def _weekly_digest(db: Session, job: JobContext) -> dict[str, Any]:
    """Monday digest of the top tier opportunities (v1.1 Phase 14).

    Scheduled daily; sends only on the organization's local Monday. At most one digest per
    user per ISO week (``digest_sends``), so retries and re-runs never send twice.
    """
    from app.services.tiers import opportunities

    assert job.tenant_id is not None
    tenant = db.get(Tenant, job.tenant_id)
    assert tenant is not None
    today = today_in(tenant.timezone)
    if today.weekday() != 0:
        return {"sent": 0, "skipped": "not_monday"}
    items = opportunities(db, tenant, today)[:DIGEST_TOP]
    if not items:
        return {"sent": 0, "skipped": "no_opportunities"}
    iso = today.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    users = db.execute(
        select(Membership.user_id).where(
            Membership.tenant_id == tenant.id,
            Membership.status == MembershipStatus.ACTIVE.value,
            Membership.role.in_(DIGEST_ROLES),
        )
    ).scalars()
    body = digest_text(items)
    title = f"{len(items)} tier {'opportunity' if len(items) == 1 else 'opportunities'} this week"
    sent = 0
    for uid in users:
        done = db.execute(
            select(DigestSend.id).where(
                DigestSend.tenant_id == tenant.id,
                DigestSend.user_id == uid,
                DigestSend.week == week,
            )
        ).first()
        if done:
            continue
        db.add(DigestSend(tenant_id=tenant.id, user_id=uid, week=week))
        db.flush()
        notify(db, tenant.id, [uid], "weekly_digest", title, body, "/app/tiers")
        sent += 1
    return {"sent": sent, "week": week}
