"""Organization settings, members, invites, support access, audit log (SPEC §4.2, §4.12, §4.13)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select

from app.api.deps import Ctx, Requires, if_match
from app.api.etag import check_if_match, etag
from app.api.schemas.common import DecimalStr, Email, In, Name, Ok, Out, Page, RateIn, ShortText
from app.core.csv_safe import csv_string
from app.core.errors import invalid
from app.core.permissions import Permission
from app.db.models.identity import AuditEvent, Role
from app.services import org as org_service

router = APIRouter(prefix="/api/v1/org", tags=["organization"])

View = Annotated[Ctx, Depends(Requires(Permission.VIEW_DATA))]
ManageSettings = Annotated[Ctx, Depends(Requires(Permission.MANAGE_SETTINGS, write=True))]
ManageUsers = Annotated[Ctx, Depends(Requires(Permission.MANAGE_USERS))]
ManageSupport = Annotated[Ctx, Depends(Requires(Permission.MANAGE_SUPPORT_ACCESS))]
ViewAudit = Annotated[Ctx, Depends(Requires(Permission.VIEW_AUDIT))]


class OrgOut(Out):
    id: uuid.UUID
    name: str
    legal_name: str | None
    timezone: str
    fiscal_year_start_month: int
    currency: str
    require_mfa_all: bool
    session_idle_minutes: int
    allowed_invite_domains: list[str]
    abs_tolerance: DecimalStr
    pct_tolerance: DecimalStr
    default_payment_terms_days: int
    data_freshness_days: int
    tier_alert_pct: DecimalStr
    tier_alert_days: int
    four_eyes_activation: bool
    four_eyes_writeoff: bool
    gl_receivable_account: str
    gl_offset_account: str
    onboarding: dict[str, Any]
    deletion_scheduled_for: date | None
    row_version: int


class ProfileSettingsIn(In):
    name: Name | None = None
    legal_name: Annotated[str | None, Field(max_length=200)] = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    fiscal_year_start_month: Annotated[int | None, Field(ge=1, le=12)] = None


class SecuritySettingsIn(In):
    require_mfa_all: bool | None = None
    session_idle_minutes: Annotated[int | None, Field(ge=15, le=240)] = None
    allowed_invite_domains: Annotated[
        list[
            Annotated[str, Field(min_length=3, max_length=253, pattern=r"^[a-z0-9.-]+\.[a-z]{2,}$")]
        ]
        | None,
        Field(max_length=50),
    ] = None


class ReconciliationSettingsIn(In):
    abs_tolerance: RateIn | None = None
    pct_tolerance: RateIn | None = None
    default_payment_terms_days: Annotated[int | None, Field(ge=0, le=730)] = None
    data_freshness_days: Annotated[int | None, Field(ge=1, le=365)] = None
    tier_alert_pct: RateIn | None = None
    tier_alert_days: Annotated[int | None, Field(ge=1, le=366)] = None


class ApprovalSettingsIn(In):
    four_eyes_activation: bool | None = None
    four_eyes_writeoff: bool | None = None


GlAccount = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9 .:/_()&-]+$")]


class AccountingSettingsIn(In):
    gl_receivable_account: GlAccount | None = None
    gl_offset_account: GlAccount | None = None


class OnboardingIn(In):
    dismissed: bool


def _org_response(response: Response, ctx: Ctx) -> OrgOut:
    assert ctx.tenant is not None
    response.headers["ETag"] = etag(ctx.tenant.row_version)
    return OrgOut.model_validate(ctx.tenant)


@router.get("", response_model=OrgOut)
def get_org(response: Response, ctx: View) -> OrgOut:
    return _org_response(response, ctx)


def _update(
    section: str, values: dict[str, Any], response: Response, ctx: Ctx, match: str | None
) -> OrgOut:
    assert ctx.tenant is not None
    version = check_if_match(match, ctx.tenant.row_version)
    if section == "profile" and "timezone" in values:
        from zoneinfo import available_timezones

        if values["timezone"] not in available_timezones():
            raise invalid(
                "TIMEZONE_INVALID",
                "Choose a valid IANA timezone, e.g. America/Chicago.",
                "timezone",
            )
    for key, value in values.items():
        if isinstance(value, Decimal) and value < 0:
            raise invalid("NEGATIVE_NOT_ALLOWED", f"{key} must be zero or more.", key)
    org_service.update_settings(ctx.db, ctx, section, values, version)
    return _org_response(response, ctx)


@router.patch("/settings/profile", response_model=OrgOut)
def update_profile(
    body: ProfileSettingsIn,
    response: Response,
    ctx: ManageSettings,
    match: Annotated[str | None, Depends(if_match)],
) -> OrgOut:
    return _update("profile", body.model_dump(exclude_none=True), response, ctx, match)


@router.patch("/settings/security", response_model=OrgOut)
def update_security(
    body: SecuritySettingsIn,
    response: Response,
    ctx: ManageSettings,
    match: Annotated[str | None, Depends(if_match)],
) -> OrgOut:
    from app.services.auth import require_recent_step_up

    require_recent_step_up(ctx.session)
    return _update("security", body.model_dump(exclude_none=True), response, ctx, match)


@router.patch("/settings/reconciliation", response_model=OrgOut)
def update_reconciliation(
    body: ReconciliationSettingsIn,
    response: Response,
    ctx: ManageSettings,
    match: Annotated[str | None, Depends(if_match)],
) -> OrgOut:
    return _update("reconciliation", body.model_dump(exclude_none=True), response, ctx, match)


@router.patch("/settings/approvals", response_model=OrgOut)
def update_approvals(
    body: ApprovalSettingsIn,
    response: Response,
    ctx: ManageSettings,
    match: Annotated[str | None, Depends(if_match)],
) -> OrgOut:
    return _update("approvals", body.model_dump(exclude_none=True), response, ctx, match)


@router.patch("/settings/accounting", response_model=OrgOut)
def update_accounting(
    body: AccountingSettingsIn,
    response: Response,
    ctx: ManageSettings,
    match: Annotated[str | None, Depends(if_match)],
) -> OrgOut:
    """GL account codes used in the accrual journal export (v1.1 Phase 15)."""
    return _update("accounting", body.model_dump(exclude_none=True), response, ctx, match)


@router.post("/onboarding", response_model=Ok)
def set_onboarding(body: OnboardingIn, ctx: View) -> Ok:
    assert ctx.tenant is not None
    ctx.tenant.onboarding = {**ctx.tenant.onboarding, "dismissed": body.dismissed}
    return Ok()


# --------------------------------------------------------------------------- members


class MemberOut(Out):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    status: str
    created_at: datetime


class RoleIn(In):
    role: Role


@router.get("/members", response_model=list[MemberOut])
def list_members(ctx: View) -> list[MemberOut]:
    return [
        MemberOut(
            id=m.id,
            user_id=u.id,
            email=u.email,
            name=u.name,
            role=m.role,
            status=m.status,
            created_at=m.created_at,
        )
        for m, u in org_service.list_members(ctx.db, ctx.tenant_uuid)
    ]


@router.patch("/members/{membership_id}", response_model=Ok)
def change_member_role(membership_id: uuid.UUID, body: RoleIn, ctx: ManageUsers) -> Ok:
    org_service.change_role(ctx.db, ctx, membership_id, body.role)
    return Ok()


@router.post("/members/{membership_id}/deactivate", response_model=Ok)
def deactivate_member(membership_id: uuid.UUID, ctx: ManageUsers) -> Ok:
    org_service.set_member_status(ctx.db, ctx, membership_id, active=False)
    return Ok()


@router.post("/members/{membership_id}/reactivate", response_model=Ok)
def reactivate_member(membership_id: uuid.UUID, ctx: ManageUsers) -> Ok:
    org_service.set_member_status(ctx.db, ctx, membership_id, active=True)
    return Ok()


# --------------------------------------------------------------------------- invites


class InviteIn(In):
    email: Email
    role: Role


class InviteOut(Out):
    id: uuid.UUID
    email: str
    role: str
    created_at: datetime
    expires_at: datetime


@router.get("/invites", response_model=list[InviteOut])
def list_invites(ctx: ManageUsers) -> list[InviteOut]:
    return [InviteOut.model_validate(i) for i in org_service.list_invites(ctx.db, ctx.tenant_uuid)]


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(body: InviteIn, ctx: ManageUsers) -> InviteOut:
    return InviteOut.model_validate(org_service.create_invite(ctx.db, ctx, body.email, body.role))


@router.post("/invites/{invite_id}/resend", response_model=InviteOut)
def resend_invite(invite_id: uuid.UUID, ctx: ManageUsers) -> InviteOut:
    return InviteOut.model_validate(org_service.resend_invite(ctx.db, ctx, invite_id))


@router.delete("/invites/{invite_id}", response_model=Ok)
def revoke_invite(invite_id: uuid.UUID, ctx: ManageUsers) -> Ok:
    org_service.revoke_invite(ctx.db, ctx, invite_id)
    return Ok()


# --------------------------------------------------------------------------- support access


class SupportGrantIn(In):
    hours: Annotated[int, Field(ge=1, le=168)] = 24
    scope: Literal["read_only", "read_write"] = "read_only"
    reason: ShortText = ""


class SupportGrantOut(Out):
    id: uuid.UUID
    scope: str
    reason: str
    created_at: datetime
    expires_at: datetime


@router.get("/support-access", response_model=list[SupportGrantOut])
def list_support_access(ctx: View) -> list[SupportGrantOut]:
    """Every member sees active grants (the in-app banner relies on this)."""
    return [
        SupportGrantOut.model_validate(g)
        for g in org_service.active_support_grants(ctx.db, ctx.tenant_uuid)
    ]


@router.post("/support-access", response_model=SupportGrantOut, status_code=201)
def grant_support_access(body: SupportGrantIn, ctx: ManageSupport) -> SupportGrantOut:
    return SupportGrantOut.model_validate(
        org_service.grant_support_access(ctx.db, ctx, body.hours, body.scope, body.reason)
    )


@router.delete("/support-access/{grant_id}", response_model=Ok)
def revoke_support_access(grant_id: uuid.UUID, ctx: ManageSupport) -> Ok:
    org_service.revoke_support_access(ctx.db, ctx, grant_id)
    return Ok()


# --------------------------------------------------------------------------- audit log


class AuditOut(Out):
    id: uuid.UUID
    seq: int
    occurred_at: datetime
    actor_type: str
    actor_label: str
    action: str
    object_type: str
    object_id: str
    summary: dict[str, Any]
    request_id: str


def _audit_query(
    ctx: Ctx,
    actor: str | None,
    action: str | None,
    object_type: str | None,
    date_from: date | None,
    date_to: date | None,
) -> Any:
    q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_uuid)
    if actor:
        q = q.where(AuditEvent.actor_label.ilike(f"%{actor}%"))
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    if object_type:
        q = q.where(AuditEvent.object_type == object_type)
    if date_from:
        q = q.where(
            AuditEvent.occurred_at >= datetime.combine(date_from, datetime.min.time()).astimezone()
        )
    if date_to:
        q = q.where(
            AuditEvent.occurred_at < datetime.combine(date_to, datetime.max.time()).astimezone()
        )
    return q.order_by(AuditEvent.seq.desc())


AuditFilter = Annotated[str | None, Query(max_length=100)]


@router.get("/audit-events", response_model=Page[AuditOut])
def list_audit(
    ctx: ViewAudit,
    actor: AuditFilter = None,
    action: AuditFilter = None,
    object_type: AuditFilter = None,
    date_from: date | None = None,
    date_to: date | None = None,
    cursor: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AuditOut]:
    q = _audit_query(ctx, actor, action, object_type, date_from, date_to)
    if cursor:
        q = q.where(AuditEvent.seq < cursor)
    rows = list(ctx.db.execute(q.limit(limit + 1)).scalars())
    nxt = str(rows[limit - 1].seq) if len(rows) > limit else None
    return Page[AuditOut](items=[AuditOut.model_validate(r) for r in rows[:limit]], next_cursor=nxt)


@router.get("/audit-events/export.csv")
def export_audit(
    ctx: ViewAudit,
    actor: AuditFilter = None,
    action: AuditFilter = None,
    object_type: AuditFilter = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StreamingResponse:
    q = _audit_query(ctx, actor, action, object_type, date_from, date_to).limit(100_000)
    rows = ctx.db.execute(q).scalars()
    body = csv_string(
        [
            "seq",
            "occurred_at",
            "actor_type",
            "actor",
            "action",
            "object_type",
            "object_id",
            "request_id",
            "hash",
        ],
        (
            [
                e.seq,
                e.occurred_at.isoformat(),
                e.actor_type,
                e.actor_label,
                e.action,
                e.object_type,
                e.object_id,
                e.request_id,
                e.hash,
            ]
            for e in rows
        ),
    )
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )
