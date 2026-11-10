"""Organizations, members, invites, settings and support access (SPEC §4.2, §4.13, §4.15)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import AppError, conflict, forbidden, invalid, not_found
from app.core.permissions import Permission
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    password_problem,
    verify_password,
)
from app.db.models.identity import (
    Invite,
    Membership,
    MembershipStatus,
    Role,
    SupportAccessGrant,
    Tenant,
    User,
    UserSession,
)
from app.db.session import set_tenant_context
from app.emails.service import queue_email
from app.services import auth as auth_service
from app.services.audit import Actor, record

ROLE_RANK = {Role.VIEWER: 0, Role.ANALYST: 1, Role.ADMIN: 2, Role.OWNER: 3}


# --------------------------------------------------------------------------- tenants


def create_tenant(
    db: Session,
    *,
    name: str,
    timezone: str,
    fiscal_year_start_month: int,
    actor: Actor,
    is_demo: bool = False,
) -> Tenant:
    """Platform-admin action (ops console / seed). Caller has platform context set."""
    tenant = Tenant(
        name=name,
        timezone=timezone,
        fiscal_year_start_month=fiscal_year_start_month,
        is_demo=is_demo,
        created_by=actor.user_id,
    )
    db.add(tenant)
    db.flush()
    set_tenant_context(db, tenant.id)
    record(
        db,
        tenant_id=tenant.id,
        actor=actor,
        action="org.created",
        object_type="tenant",
        object_id=tenant.id,
        summary={"name": name},
    )
    return tenant


SETTINGS_FIELDS = {
    "profile": {"name", "legal_name", "timezone", "fiscal_year_start_month"},
    "security": {"require_mfa_all", "session_idle_minutes", "allowed_invite_domains"},
    "reconciliation": {
        "abs_tolerance",
        "pct_tolerance",
        "default_payment_terms_days",
        "data_freshness_days",
        "tier_alert_pct",
        "tier_alert_days",
    },
    "approvals": {"four_eyes_activation", "four_eyes_writeoff"},
}


def update_settings(
    db: Session, ctx: Any, section: str, values: dict[str, Any], expected_version: int
) -> Tenant:
    tenant: Tenant | None = ctx.tenant
    assert tenant is not None
    if tenant.row_version != expected_version:
        raise AppError(
            412,
            "PRECONDITION_FAILED",
            "Changed by someone else",
            "These settings were changed by someone else. Reload and try again.",
        )
    allowed = SETTINGS_FIELDS[section]
    before = {k: _jsonable(getattr(tenant, k)) for k in values if k in allowed}
    for key, value in values.items():
        if key not in allowed:
            raise invalid("UNKNOWN_FIELD", f"{key} is not a {section} setting", key)
        setattr(tenant, key, value)
    tenant.updated_by = ctx.user.id
    db.flush()
    record(
        db,
        tenant_id=tenant.id,
        actor=ctx.actor,
        action=f"settings.{section}.updated",
        object_type="tenant",
        object_id=tenant.id,
        summary={"before": before, "after": {k: _jsonable(getattr(tenant, k)) for k in before}},
    )
    return tenant


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    return v


# --------------------------------------------------------------------------- members


def list_members(db: Session, tenant_id: uuid.UUID) -> list[tuple[Membership, User]]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant_id)
        .order_by(User.email)
    ).all()
    return [(m, u) for m, u in rows]


def _membership(db: Session, tenant_id: uuid.UUID, membership_id: uuid.UUID) -> Membership:
    m = db.execute(
        select(Membership).where(Membership.id == membership_id, Membership.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Member")
    return m


def _active_owner_count(db: Session, tenant_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == Role.OWNER.value,
                Membership.status == MembershipStatus.ACTIVE.value,
            )
        ).scalar_one()
    )


def _lock_owners(db: Session, tenant_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 7))"), {"k": f"owners:{tenant_id}"}
    )


def change_role(db: Session, ctx: Any, membership_id: uuid.UUID, new_role: Role) -> Membership:
    tenant_id = ctx.tenant_uuid
    _lock_owners(db, tenant_id)
    m = _membership(db, tenant_id, membership_id)
    auth_service.require_recent_step_up(ctx.session)
    old = Role(m.role)
    if old == new_role:
        return m
    touches_owner = Role.OWNER in (old, new_role)
    if touches_owner and not ctx.can(Permission.MANAGE_OWNERS):
        raise forbidden("Only an Owner can promote or demote Owners.")
    if (
        old is Role.OWNER
        and m.status == MembershipStatus.ACTIVE.value
        and _active_owner_count(db, tenant_id) <= 1
    ):
        raise conflict(
            "LAST_OWNER",
            "The last active Owner cannot be demoted. Make someone else an Owner first.",
        )
    m.role = new_role.value
    m.role_changed_at = utcnow()
    m.updated_by = ctx.user.id
    # Privilege change: sessions of that user in this org must re-evaluate (rotation on next use).
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == m.user_id,
            UserSession.active_tenant_id == tenant_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow(), revoked_reason="role_changed")
    )
    user = db.get(User, m.user_id)
    assert user is not None
    record(
        db,
        tenant_id=tenant_id,
        actor=ctx.actor,
        action="member.role_changed",
        object_type="membership",
        object_id=m.id,
        summary={"from": old.value, "to": new_role.value},
    )
    auth_service.security_notice(
        db,
        user,
        "Your role changed",
        f"Your role in {ctx.tenant.name} changed from {old.value} to {new_role.value}.",
    )
    return m


def set_member_status(db: Session, ctx: Any, membership_id: uuid.UUID, active: bool) -> Membership:
    tenant_id = ctx.tenant_uuid
    _lock_owners(db, tenant_id)
    m = _membership(db, tenant_id, membership_id)
    if Role(m.role) is Role.OWNER and not ctx.can(Permission.MANAGE_OWNERS):
        raise forbidden("Only an Owner can change another Owner.")
    if not active:
        if m.user_id == ctx.user.id:
            raise conflict("CANNOT_DEACTIVATE_SELF", "You cannot deactivate yourself.")
        if Role(m.role) is Role.OWNER and _active_owner_count(db, tenant_id) <= 1:
            raise conflict("LAST_OWNER", "The last active Owner cannot be deactivated.")
        m.status = MembershipStatus.DEACTIVATED.value
        db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == m.user_id,
                UserSession.active_tenant_id == tenant_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow(), revoked_reason="deactivated")
        )
        action = "member.deactivated"
    else:
        m.status = MembershipStatus.ACTIVE.value
        action = "member.reactivated"
    m.updated_by = ctx.user.id
    record(
        db,
        tenant_id=tenant_id,
        actor=ctx.actor,
        action=action,
        object_type="membership",
        object_id=m.id,
    )
    return m


# --------------------------------------------------------------------------- invites


def create_invite(
    db: Session, ctx: Any, email: str, role: Role, *, inviter_label: str | None = None
) -> Invite:
    tenant = ctx.tenant
    assert tenant is not None
    email = auth_service.normalise_email(email)
    ratelimit.hit("invite", str(tenant.id), 50, 3600)
    if role is Role.OWNER and not ctx.can(Permission.MANAGE_OWNERS):
        raise forbidden("Only an Owner can invite another Owner.")
    domains = [d.lower() for d in tenant.allowed_invite_domains]
    if domains and email.rsplit("@", 1)[-1] not in domains:
        raise invalid(
            "DOMAIN_NOT_ALLOWED", f"Invites are limited to: {', '.join(domains)}.", "email"
        )
    existing_member = db.execute(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant.id, User.email == email)
    ).first()
    if existing_member:
        raise conflict(
            "ALREADY_MEMBER", "This person is already a member. Reactivate them instead."
        )
    # Revoke older pending invites for the same address.
    db.execute(
        update(Invite)
        .where(
            Invite.tenant_id == tenant.id,
            Invite.email == email,
            Invite.accepted_at.is_(None),
            Invite.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    return _issue_invite(
        db,
        tenant,
        email,
        role,
        ctx.user.id,
        inviter_label or ctx.user.name or ctx.user.email,
        ctx.actor,
    )


def _issue_invite(
    db: Session,
    tenant: Tenant,
    email: str,
    role: Role,
    invited_by: uuid.UUID | None,
    inviter_label: str,
    actor: Actor,
) -> Invite:
    s = get_settings()
    token = new_token()
    invite = Invite(
        tenant_id=tenant.id,
        email=email,
        role=role.value,
        token_hash=hash_token(token),
        invited_by=invited_by,
        expires_at=utcnow() + timedelta(days=s.invite_ttl_days),
    )
    db.add(invite)
    db.flush()
    queue_email(
        db,
        to=email,
        template="invite",
        tenant_id=tenant.id,
        context={
            "org_name": tenant.name,
            "inviter": inviter_label,
            "role": role.value.title(),
            "url": f"{s.app_base_url}/accept-invite?token={token}",
            "ttl_days": s.invite_ttl_days,
        },
    )
    record(
        db,
        tenant_id=tenant.id,
        actor=actor,
        action="invite.created",
        object_type="invite",
        object_id=invite.id,
        summary={"role": role.value},
    )
    return invite


def invite_first_owner(db: Session, tenant: Tenant, email: str, actor: Actor) -> Invite:
    """Ops console: create a tenant and invite its first Owner."""
    return _issue_invite(
        db,
        tenant,
        auth_service.normalise_email(email),
        Role.OWNER,
        actor.user_id,
        "The RebateLedger team",
        actor,
    )


def list_invites(db: Session, tenant_id: uuid.UUID) -> list[Invite]:
    return list(
        db.execute(
            select(Invite)
            .where(
                Invite.tenant_id == tenant_id,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
            )
            .order_by(Invite.created_at.desc())
        ).scalars()
    )


def revoke_invite(db: Session, ctx: Any, invite_id: uuid.UUID) -> None:
    inv = db.execute(
        select(Invite).where(Invite.id == invite_id, Invite.tenant_id == ctx.tenant_uuid)
    ).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.revoked_at is not None:
        raise not_found("Invite")
    if Role(inv.role) is Role.OWNER and not ctx.can(Permission.MANAGE_OWNERS):
        raise forbidden("Only an Owner can revoke an Owner invite.")
    inv.revoked_at = utcnow()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="invite.revoked",
        object_type="invite",
        object_id=inv.id,
    )


def resend_invite(db: Session, ctx: Any, invite_id: uuid.UUID) -> Invite:
    inv = db.execute(
        select(Invite).where(Invite.id == invite_id, Invite.tenant_id == ctx.tenant_uuid)
    ).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.revoked_at is not None:
        raise not_found("Invite")
    return create_invite(db, ctx, inv.email, Role(inv.role))


def _invite_by_token(db: Session, token: str) -> Invite:
    tenant_id = db.execute(text("SELECT rl.invite_tenant(:h)"), {"h": hash_token(token)}).scalar()
    if tenant_id is None:
        raise AppError(
            400,
            "TOKEN_INVALID",
            "Invitation not valid",
            "This invitation is invalid, expired, revoked or already used. Ask for a new one.",
        )
    set_tenant_context(db, tenant_id)
    inv = db.execute(
        select(Invite).where(Invite.token_hash == hash_token(token)).with_for_update()
    ).scalar_one()
    return inv


def preview_invite(db: Session, token: str) -> dict[str, Any]:
    inv = _invite_by_token(db, token)
    tenant = db.get(Tenant, inv.tenant_id)
    assert tenant is not None
    has_account = db.execute(select(User.id).where(User.email == inv.email)).first() is not None
    return {
        "organization_name": tenant.name,
        "email": inv.email,
        "role": inv.role,
        "has_account": has_account,
    }


def accept_invite(
    db: Session, token: str, *, name: str | None, password: str, user_agent: str, ip: str
) -> auth_service.IssuedSession:
    """New users set a password; existing users (SPEC §9 case 41) confirm theirs."""
    ratelimit.hit("invite-accept", ip or "unknown", 20, 3600)
    inv = _invite_by_token(db, token)
    tenant = db.get(Tenant, inv.tenant_id)
    assert tenant is not None
    user = db.execute(select(User).where(User.email == inv.email)).scalar_one_or_none()
    if user is None:
        if not name or not name.strip():
            raise invalid("NAME_REQUIRED", "Enter your name.", "name")
        problem = password_problem(password, email=inv.email, name=name)
        if problem:
            raise invalid("WEAK_PASSWORD", problem, "password")
        user = User(
            email=inv.email,
            name=name.strip(),
            password_hash=hash_password(password),
            email_verified_at=utcnow(),
            password_changed_at=utcnow(),
        )
        db.add(user)
        db.flush()
    elif not verify_password(user.password_hash, password):
        raise AppError(
            401,
            "INVALID_CREDENTIALS",
            "Password incorrect",
            "Enter the password of your existing account to accept.",
        )
    existing = db.execute(
        select(Membership).where(Membership.tenant_id == tenant.id, Membership.user_id == user.id)
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Membership(
                tenant_id=tenant.id, user_id=user.id, role=inv.role, created_by=inv.invited_by
            )
        )
    else:
        existing.status = MembershipStatus.ACTIVE.value
        existing.role = inv.role
    inv.accepted_at = utcnow()
    user.preferences = {**user.preferences, "last_tenant_id": str(tenant.id)}
    db.flush()
    record(
        db,
        tenant_id=tenant.id,
        actor=Actor("user", user.id, user.email),
        action="invite.accepted",
        object_type="invite",
        object_id=inv.id,
        summary={"role": inv.role},
    )
    return auth_service.login_after_signup(db, user, tenant, inv.role, user_agent=user_agent, ip=ip)


# --------------------------------------------------------------------------- support access


def grant_support_access(
    db: Session, ctx: Any, hours: int, scope: str, reason: str
) -> SupportAccessGrant:
    auth_service.require_recent_step_up(ctx.session)
    if not 1 <= hours <= 24 * 7:
        raise invalid("DURATION_INVALID", "Choose between 1 hour and 7 days.", "hours")
    grant = SupportAccessGrant(
        tenant_id=ctx.tenant_uuid,
        scope=scope,
        reason=reason,
        granted_by=ctx.user.id,
        expires_at=utcnow() + timedelta(hours=hours),
    )
    db.add(grant)
    db.flush()
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="support_access.granted",
        object_type="support_access_grant",
        object_id=grant.id,
        summary={"scope": scope, "hours": hours},
    )
    return grant


def active_support_grants(db: Session, tenant_id: uuid.UUID) -> list[SupportAccessGrant]:
    return list(
        db.execute(
            select(SupportAccessGrant)
            .where(
                SupportAccessGrant.tenant_id == tenant_id,
                SupportAccessGrant.revoked_at.is_(None),
                SupportAccessGrant.expires_at > utcnow(),
            )
            .order_by(SupportAccessGrant.created_at.desc())
        ).scalars()
    )


def revoke_support_access(db: Session, ctx: Any, grant_id: uuid.UUID) -> None:
    grant = db.execute(
        select(SupportAccessGrant).where(
            SupportAccessGrant.id == grant_id, SupportAccessGrant.tenant_id == ctx.tenant_uuid
        )
    ).scalar_one_or_none()
    if grant is None or grant.revoked_at is not None:
        raise not_found("Support access grant")
    grant.revoked_at, grant.revoked_by = utcnow(), ctx.user.id
    db.execute(
        update(UserSession)
        .where(UserSession.is_platform.is_(True), UserSession.active_tenant_id == ctx.tenant_uuid)
        .values(active_tenant_id=None)
    )
    record(
        db,
        tenant_id=ctx.tenant_uuid,
        actor=ctx.actor,
        action="support_access.revoked",
        object_type="support_access_grant",
        object_id=grant.id,
    )
