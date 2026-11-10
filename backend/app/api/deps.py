"""Request-scoped dependencies: DB transaction, session auth, tenant context, permissions.

Every route MUST depend on exactly one of :class:`Requires`, :class:`Public`,
:class:`Authenticated` or :class:`PlatformAdminOnly`. ``tests/api/test_route_policy.py``
walks the route table and fails if one is missing (SPEC §8.2).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.permissions import READ_ONLY_PERMISSIONS, Permission, permissions_for
from app.core.security import check_csrf
from app.db.models.identity import (
    Membership,
    MembershipStatus,
    Role,
    SessionState,
    SupportAccessGrant,
    Tenant,
    User,
    UserSession,
)
from app.db.session import (
    session_factory,
    set_platform_context,
    set_tenant_context,
    set_user_context,
)
from app.services import auth as auth_service
from app.services.audit import Actor, record

SESSION_COOKIE = "__Host-rl_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_db() -> Iterator[Session]:
    """One transaction per request; committed before the response is sent."""
    db = session_factory()()
    try:
        db.begin()
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


DB = Annotated[Session, Depends(get_db, scope="function")]


@dataclass
class Ctx:
    """Who is calling, in which organization, with which permissions."""

    db: Session
    user: User
    session: UserSession
    tenant_id: uuid.UUID | None = None
    tenant: Tenant | None = None
    membership: Membership | None = None
    role: Role | None = None
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    support_grant: SupportAccessGrant | None = None
    is_platform: bool = False

    @property
    def actor(self) -> Actor:
        if self.support_grant is not None:
            return Actor("platform_admin", self.user.id, f"support:{self.user.email}")
        return Actor("user", self.user.id, self.user.email)

    @property
    def tenant_uuid(self) -> uuid.UUID:
        if self.tenant_id is None:  # pragma: no cover - guarded by Requires
            raise AppError(403, "NO_ORGANIZATION", "No organization selected")
        return self.tenant_id

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


def _csrf_and_origin(request: Request, s: UserSession | None) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    allowed = get_settings().allowed_origins
    source = origin or (referer and "/".join(referer.split("/", 3)[:3]))
    if not source or source.rstrip("/") not in allowed:
        raise AppError(
            403, "CSRF_ORIGIN", "Request blocked", "The request did not come from this application."
        )
    if s is not None and not check_csrf(str(s.id), request.headers.get("x-csrf-token")):
        raise AppError(
            403,
            "CSRF_TOKEN",
            "Request blocked",
            "Missing or invalid CSRF token. Reload the page and try again.",
        )


def _load(
    request: Request, db: Session, *, allow_pending: bool = False, require_tenant: bool = False
) -> Ctx:
    resolved = auth_service.resolve(db, request.cookies.get(SESSION_COOKIE))
    if resolved is None:
        raise AppError(
            401, "UNAUTHENTICATED", "Sign in required", "Your session has ended. Sign in again."
        )
    s, user = resolved
    _csrf_and_origin(request, s)
    request.state.user_id = str(user.id)
    if s.state != SessionState.ACTIVE.value and not allow_pending:
        code = (
            "MFA_REQUIRED"
            if s.state == SessionState.PENDING_MFA.value
            else "MFA_ENROLLMENT_REQUIRED"
        )
        raise AppError(
            403,
            code,
            "Two-factor authentication required",
            "Complete two-factor authentication to continue.",
        )
    ctx = Ctx(db=db, user=user, session=s, is_platform=s.is_platform)
    if s.active_tenant_id is None:
        if s.is_platform:
            set_platform_context(db, True)
        return ctx
    tenant_id = s.active_tenant_id
    if s.is_platform:
        set_platform_context(db, True)
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
        set_platform_context(db, False)
        if grant is None:
            s.active_tenant_id = None
            raise AppError(
                403,
                "SUPPORT_ACCESS_ENDED",
                "Support access ended",
                "The organization's support access grant has expired or was revoked.",
            )
        set_tenant_context(db, tenant_id)
        ctx.tenant_id, ctx.support_grant = tenant_id, grant
        ctx.tenant = db.get(Tenant, tenant_id)
        ctx.permissions = (
            READ_ONLY_PERMISSIONS
            if grant.scope == "read_only"
            else permissions_for(Role.ANALYST.value)
        )
        record(
            db,
            tenant_id=tenant_id,
            actor=ctx.actor,
            action="support.request",
            object_type="route",
            object_id=request.url.path[:80],
            summary={"method": request.method},
        )
        return ctx
    set_tenant_context(db, tenant_id)
    set_user_context(db, user.id)
    membership = db.execute(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.ACTIVE.value,
        )
    ).scalar_one_or_none()
    if membership is None:
        # Removed from the org mid-session (SPEC §9 case 42). Org-scoped routes refuse;
        # org-agnostic routes (switch organization, profile, logout) still work.
        if not require_tenant:
            set_tenant_context(db, None)
            return ctx
        raise AppError(
            403,
            "NO_MEMBERSHIP",
            "No access to this organization",
            "You are no longer a member of this organization. Choose another organization.",
        )
    ctx.tenant_id = tenant_id
    ctx.tenant = db.get(Tenant, tenant_id)
    ctx.membership = membership
    ctx.role = Role(membership.role)
    ctx.permissions = permissions_for(membership.role)
    if (
        ctx.tenant is not None
        and auth_service.mfa_required(db, user, ctx.tenant, membership.role)
        and not auth_service.has_mfa(db, user.id)
    ):
        s.state = SessionState.PENDING_ENROLLMENT.value
        if not allow_pending:
            raise AppError(
                403,
                "MFA_ENROLLMENT_REQUIRED",
                "Two-factor authentication required",
                "Set up two-factor authentication to continue.",
            )
    return ctx


class Requires:
    """Route needs an active session in an organization with this permission."""

    def __init__(self, permission: Permission, *, write: bool = False) -> None:
        self.permission = permission
        self.write = write

    def __call__(self, request: Request, db: DB) -> Ctx:
        ctx = _load(request, db, require_tenant=True)
        if ctx.tenant_id is None:
            raise AppError(
                403, "NO_ORGANIZATION", "No organization selected", "Choose an organization first."
            )
        if self.permission not in ctx.permissions:
            raise AppError(403, "FORBIDDEN", "Forbidden", "Your role does not allow this action.")
        if self.write and ctx.tenant is not None:
            _check_not_suspended(db, ctx)
        return ctx


def _check_not_suspended(db: Session, ctx: Ctx) -> None:
    """Suspended tenants are read-only (SPEC §4.14). Hooked up in Phase 8."""
    from app.services.subscriptions import is_read_only

    if is_read_only(db, ctx.tenant_uuid):
        raise AppError(
            403,
            "TENANT_READ_ONLY",
            "Organization is read-only",
            "This organization is suspended. You can view and export data; contact your account owner about billing.",
        )


class Authenticated:
    """Any signed-in user; organization optional. ``allow_pending`` admits MFA-pending sessions."""

    def __init__(self, *, allow_pending: bool = False) -> None:
        self.allow_pending = allow_pending

    def __call__(self, request: Request, db: DB) -> Ctx:
        return _load(request, db, allow_pending=self.allow_pending)


class Public:
    """Explicit marker for unauthenticated endpoints. Still enforces Origin on writes."""

    def __call__(self, request: Request) -> None:
        _csrf_and_origin(request, None)


class PlatformAdminOnly:
    """Operator console routes (SPEC §4.15), enforced server-side."""

    def __call__(self, request: Request, db: DB) -> Ctx:
        ctx = _load(request, db)
        if not ctx.is_platform:
            raise AppError(404, "NOT_FOUND", "Not found")
        allow = get_settings().platform_admin_ip_allowlist
        if allow and (request.client is None or request.client.host not in allow):
            raise AppError(404, "NOT_FOUND", "Not found")
        set_tenant_context(db, None)
        set_platform_context(db, True)
        return ctx


def idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> str | None:
    return key


def if_match(
    value: Annotated[str | None, Header(alias="If-Match", max_length=100)] = None,
) -> str | None:
    return value
