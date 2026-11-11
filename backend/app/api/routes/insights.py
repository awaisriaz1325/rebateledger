"""Dashboard, tier tracker, accruals, notifications (SPEC §4.9–4.11)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DB, Ctx, Public, Requires
from app.api.schemas.common import DecimalStr, In, Ok, Out
from app.api.schemas.views import DashboardOut
from app.core.errors import AppError
from app.core.permissions import Permission
from app.db.models.identity import Notification
from app.services import dashboard, notifications, tiers

router = APIRouter(prefix="/api/v1", tags=["insights"])
View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(ctx: View) -> DashboardOut:
    assert ctx.tenant is not None
    return DashboardOut.model_validate(dashboard.kpis(ctx.db, ctx.tenant))


class TierOut(Out):
    agreement_id: uuid.UUID
    agreement_name: str
    supplier_name: str
    period_start: date
    period_end: date
    measure_kind: str
    current_measure: DecimalStr
    current_tier: int | None
    next_tier: int | None
    next_threshold: DecimalStr | None
    gap: DecimalStr | None
    days_remaining: int
    days_elapsed: int
    projected_measure: DecimalStr
    projected_reaches_next: bool
    potential_additional: DecimalStr | None
    expected_to_date: DecimalStr | None
    needs_review: bool
    data_as_of: date | None
    is_estimate: bool = True


@router.get("/tiers", response_model=list[TierOut])
def tier_tracker(ctx: View) -> list[TierOut]:
    """Open periods only. Projections and accruals are ESTIMATES (SPEC §4.9)."""
    assert ctx.tenant is not None
    return [
        TierOut.model_validate(r, from_attributes=True) for r in tiers.tracker(ctx.db, ctx.tenant)
    ]


class NotificationOut(Out):
    id: uuid.UUID
    type: str
    title: str
    body: str
    link: str
    created_at: datetime
    read_at: datetime | None


class NotificationList(Out):
    items: list[NotificationOut]
    unread: int


class MarkReadIn(In):
    ids: Annotated[list[uuid.UUID] | None, Field(max_length=500)] = None


class PreferenceIn(In):
    type: Annotated[str, Field(max_length=60)]
    in_app: bool | None = None
    email: bool | None = None


class PreferenceOut(Out):
    type: str
    label: str
    in_app: bool
    email: bool


Member = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]


@router.get("/notifications", response_model=NotificationList)
def list_notifications(
    ctx: Member, unread_only: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> NotificationList:
    q = select(Notification).where(
        Notification.tenant_id == ctx.tenant_uuid, Notification.user_id == ctx.user.id
    )
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = ctx.db.execute(q.order_by(Notification.created_at.desc()).limit(limit)).scalars()
    return NotificationList(
        items=[NotificationOut.model_validate(n) for n in rows],
        unread=notifications.unread_count(ctx.db, ctx.tenant_uuid, ctx.user.id),
    )


@router.post("/notifications/read", response_model=Ok)
def mark_read(body: MarkReadIn, ctx: Member) -> Ok:
    notifications.mark_read(ctx.db, ctx.tenant_uuid, ctx.user.id, body.ids)
    return Ok()


@router.get("/notification-preferences", response_model=list[PreferenceOut])
def get_preferences(ctx: Member) -> list[PreferenceOut]:
    prefs = notifications.preferences(ctx.db, ctx.tenant_uuid, ctx.user.id)
    return [
        PreferenceOut(type=t, label=label, in_app=prefs[t][0], email=prefs[t][1])
        for t, label in notifications.ALERT_TYPES.items()
    ]


@router.put("/notification-preferences", response_model=Ok)
def set_preference(body: PreferenceIn, ctx: Member) -> Ok:
    if body.type not in notifications.ALERT_TYPES:
        raise AppError(
            422,
            "PREFERENCE_UNKNOWN",
            "Unknown notification type",
            "Security and account emails cannot be turned off.",
        )
    notifications.set_preference(
        ctx.db, ctx.tenant_uuid, ctx.user.id, body.type, in_app=body.in_app, email=body.email
    )
    return Ok()


class UnsubscribeIn(In):
    token: Annotated[str, Field(min_length=10, max_length=1000)]


@router.post("/unsubscribe", dependencies=[Depends(Public())])
def unsubscribe(body: UnsubscribeIn, db: DB) -> dict[str, str]:
    """One-click unsubscribe from alert emails without signing in (signed token)."""
    label = notifications.apply_unsubscribe(db, body.token)
    if label is None:
        raise AppError(
            400,
            "TOKEN_INVALID",
            "Link not valid",
            "This unsubscribe link is invalid or expired. Change preferences in Settings instead.",
        )
    return {"unsubscribed_from": label}
