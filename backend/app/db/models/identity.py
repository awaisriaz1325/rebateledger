"""Identity, tenancy, sessions, MFA, audit, jobs, notifications (SPEC §4.1–4.2, §4.11–4.12, §5)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import (
    SCHEMA,
    AuthorMixin,
    Base,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    VersionedMixin,
)


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class SessionState(StrEnum):
    PENDING_MFA = "pending_mfa"
    PENDING_ENROLLMENT = "pending_enrollment"
    ACTIVE = "active"


class EmailTokenType(StrEnum):
    VERIFY_EMAIL = "verify_email"
    # token type name, not a secret
    RESET_PASSWORD = "reset_password"  # noqa: S105  # nosec B105
    CHANGE_EMAIL = "change_email"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD = "dead"


def _enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    values = ", ".join(f"'{m.value}'" for m in enum)
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_valid")


class Tenant(IdMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_month"),
        CheckConstraint("currency = 'USD'", name="usd_only"),
        CheckConstraint("session_idle_minutes BETWEEN 15 AND 240", name="idle_range"),
        CheckConstraint("abs_tolerance >= 0 AND pct_tolerance >= 0", name="tolerance_non_negative"),
    )

    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Chicago")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    logo_key: Mapped[str | None] = mapped_column(String(300))
    # Security settings
    require_mfa_all: Mapped[bool] = mapped_column(Boolean, default=False)
    session_idle_minutes: Mapped[int] = mapped_column(Integer, default=30)
    allowed_invite_domains: Mapped[list[str]] = mapped_column(ARRAY(String(253)), default=list)
    # Reconciliation settings
    abs_tolerance: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("1.00"))
    pct_tolerance: Mapped[Decimal] = mapped_column(Numeric(9, 6), default=Decimal("0.005"))
    default_payment_terms_days: Mapped[int] = mapped_column(Integer, default=60)
    data_freshness_days: Mapped[int] = mapped_column(Integer, default=45)
    tier_alert_pct: Mapped[Decimal] = mapped_column(Numeric(9, 6), default=Decimal("0.10"))
    tier_alert_days: Mapped[int] = mapped_column(Integer, default=21)
    # Approvals
    four_eyes_activation: Mapped[bool] = mapped_column(Boolean, default=False)
    four_eyes_writeoff: Mapped[bool] = mapped_column(Boolean, default=False)
    # Onboarding
    onboarding: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Deletion lifecycle (SPEC §4.13)
    deletion_scheduled_for: Mapped[date | None] = mapped_column(Date)
    deletion_requested_by: Mapped[uuid.UUID | None]
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class User(IdMixin, TimestampMixin, Base):
    """Global identity. One user may belong to many tenants."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True)
    """Stored lower-cased and trimmed."""
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_reenroll_mfa: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Membership(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        _enum_check("role", Role),
        _enum_check("status", MembershipStatus),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=MembershipStatus.ACTIVE.value)
    role_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Invite(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "invites"
    __table_args__ = (_enum_check("role", Role),)

    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    invited_by: Mapped[uuid.UUID | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailToken(IdMixin, Base):
    __tablename__ = "email_tokens"
    __table_args__ = (_enum_check("type", EmailTokenType),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    new_email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(IdMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (_enum_check("state", SessionState),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    state: Mapped[str] = mapped_column(String(30))
    active_tenant_id: Mapped[uuid.UUID | None]
    is_platform: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_minutes: Mapped[int] = mapped_column(Integer)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stepped_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(60))


class MfaFactor(IdMixin, Base):
    __tablename__ = "mfa_factors"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), unique=True
    )
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_timestep: Mapped[int | None] = mapped_column(BigInteger)


class RecoveryCode(IdMixin, Base):
    __tablename__ = "recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportAccessGrant(IdMixin, TenantMixin, Base):
    __tablename__ = "support_access_grants"
    __table_args__ = (CheckConstraint("scope IN ('read_only', 'read_write')", name="scope_valid"),)

    scope: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500), default="")
    granted_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None]


class AuditEvent(IdMixin, Base):
    """Append-only; the app role has SELECT + INSERT only. Hash-chained per tenant."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("chain_key", "seq"),
        Index("ix_audit_events_tenant_time", "tenant_id", "occurred_at"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE")
    )
    chain_key: Mapped[str] = mapped_column(String(40))
    """Tenant id, or 'platform' for operator actions outside any tenant."""
    seq: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[uuid.UUID | None]
    actor_label: Mapped[str] = mapped_column(String(254), default="")
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(60), default="")
    object_id: Mapped[str] = mapped_column(String(80), default="")
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    request_id: Mapped[str] = mapped_column(String(80), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class IdempotencyKey(IdMixin, TenantMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "route", "key"),)

    user_id: Mapped[uuid.UUID]
    route: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(IdMixin, Base):
    """Durable job record backing `GET /api/v1/jobs/{id}`. tenant_id NULL = platform job."""

    __tablename__ = "jobs"
    __table_args__ = (_enum_check("status", JobStatus), Index("ix_jobs_status", "status"))

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value)
    progress: Mapped[int] = mapped_column(BigInteger, default=0)
    total: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[dict[str, Any] | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    queue_key: Mapped[str | None] = mapped_column(String(80))
    """Jobs sharing a queue_key run one at a time (e.g. one active run per tenant)."""
    created_by: Mapped[uuid.UUID | None]
    # Client-side default: INSERT ... RETURNING would need SELECT visibility under RLS.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(IdMixin, TenantMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "tenant_id", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreference(IdMixin, TenantMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "type"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(60))
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
