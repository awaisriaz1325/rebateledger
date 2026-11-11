"""Runs, results, allocations, reconciliation, claims (SPEC §4.7–4.9, §5)."""

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
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


def _fk(table: str, ondelete: str = "CASCADE") -> ForeignKey:
    return ForeignKey(f"{SCHEMA}.{table}.id", ondelete=ondelete)


def _in(column: str, values: list[str]) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=f"{column}_valid")


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CalculationRun(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "calculation_runs"
    __table_args__ = (
        _in("status", [s.value for s in RunStatus]),
        Index("ix_runs_tenant_finished", "tenant_id", "finished_at"),
    )

    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED.value)
    scope: Mapped[dict[str, Any]] = mapped_column(default=dict)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)
    engine_version: Mapped[str] = mapped_column(String(20), default="")
    totals: Mapped[dict[str, Any]] = mapped_column(default=dict)
    started_by: Mapped[uuid.UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None]
    error: Mapped[str] = mapped_column(String(500), default="")


class RunInput(IdMixin, TenantMixin, Base):
    __tablename__ = "run_inputs"
    __table_args__ = (
        _in("kind", ["batch", "version", "baseline"]),
        Index("ix_run_inputs_ref", "tenant_id", "kind", "ref_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(_fk("calculation_runs"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[uuid.UUID]


class PeriodResultRow(IdMixin, TenantMixin, Base):
    """Immutable engine output (stale fields are the only mutable columns)."""

    __tablename__ = "period_results"
    __table_args__ = (
        Index(
            "ix_period_results_version_period", "tenant_id", "agreement_version_id", "period_start"
        ),
        Index(
            "ix_period_results_agreement_period",
            "tenant_id",
            "agreement_id",
            "period_start",
            "period_end",
        ),
        Index("ix_period_results_run", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(_fk("calculation_runs"))
    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements", "RESTRICT"))
    agreement_version_id: Mapped[uuid.UUID] = mapped_column(_fk("agreement_versions", "RESTRICT"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    version_no: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    full_period_start: Mapped[date] = mapped_column(Date)
    full_period_end: Mapped[date] = mapped_column(Date)
    period_label: Mapped[str] = mapped_column(String(40), default="")
    expected: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    expected_unrounded: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    measure: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tier_reached: Mapped[int | None] = mapped_column(Integer)
    components: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    statuses: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    eligible_count: Mapped[int] = mapped_column(Integer)
    excluded_counts: Mapped[dict[str, Any]] = mapped_column(default=dict)
    payment_terms_days: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    input_hash: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(20))
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PeriodTrace(TenantMixin, Base):
    __tablename__ = "period_traces"

    result_id: Mapped[uuid.UUID] = mapped_column(_fk("period_results"), primary_key=True)
    trace: Mapped[list[dict[str, Any]]] = mapped_column(default=list)


class ReconciliationItem(IdMixin, TenantMixin, Base):
    """Per-run snapshot of the reconciliation at run time (history / diff)."""

    __tablename__ = "reconciliation_items"
    __table_args__ = (Index("ix_recon_items_run", "run_id"),)

    run_id: Mapped[uuid.UUID] = mapped_column(_fk("calculation_runs"))
    result_id: Mapped[uuid.UUID] = mapped_column(_fk("period_results"))
    received: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(20))
    flags: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list)
    as_of: Mapped[date] = mapped_column(Date)


class VersionResolutionRow(IdMixin, TenantMixin, Base):
    """User decisions for VERSION_CHANGE_IN_PERIOD (SPEC §4.4.4)."""

    __tablename__ = "version_resolutions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agreement_id", "period_start", "period_end"),
        _in("choice", ["apply_old", "apply_new", "split"]),
    )

    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    choice: Mapped[str] = mapped_column(String(20))
    decided_by: Mapped[uuid.UUID]
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditAllocation(IdMixin, TenantMixin, Base):
    __tablename__ = "credit_allocations"
    __table_args__ = (
        _in("method", ["auto", "manual", "recovery"]),
        Index("ix_allocations_target", "tenant_id", "agreement_id", "period_start", "period_end"),
        Index("ix_allocations_credit", "credit_id"),
    )

    credit_id: Mapped[uuid.UUID] = mapped_column(_fk("credit_lines", "RESTRICT"))
    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements", "RESTRICT"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    method: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None]


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED_RECOVERED = "resolved_recovered"
    RESOLVED_PARTIAL = "resolved_partial"
    REJECTED = "rejected"
    WRITTEN_OFF = "written_off"


TERMINAL_CLAIM = {
    ClaimStatus.RESOLVED_RECOVERED,
    ClaimStatus.RESOLVED_PARTIAL,
    ClaimStatus.REJECTED,
    ClaimStatus.WRITTEN_OFF,
}


class Claim(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        _in("status", [s.value for s in ClaimStatus]),
        _in("channel", ["email", "portal", "phone", "other"]),
    )

    number: Mapped[int] = mapped_column(Integer)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default=ClaimStatus.DRAFT.value)
    identified_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    claimed_amount_reason: Mapped[str] = mapped_column(String(500), default="")
    assignee_id: Mapped[uuid.UUID | None]
    due_date: Mapped[date | None] = mapped_column(Date)
    follow_up_date: Mapped[date | None] = mapped_column(Date)
    supplier_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        _fk("supplier_contacts", "SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(10), default="email")
    notes: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    write_off_reason: Mapped[str] = mapped_column(String(500), default="")
    pending_write_off: Mapped[bool] = mapped_column(Boolean, default=False)
    last_reminder: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ClaimItem(IdMixin, TenantMixin, Base):
    __tablename__ = "claim_items"
    __table_args__ = (UniqueConstraint("claim_id", "agreement_id", "period_start", "period_end"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(_fk("claims"), index=True)
    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements", "RESTRICT"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    result_id: Mapped[uuid.UUID] = mapped_column(_fk("period_results", "RESTRICT"))
    expected: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    received_at_creation: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    variance_at_creation: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    status_at_creation: Mapped[str] = mapped_column(String(20))


class ClaimEvent(IdMixin, TenantMixin, Base):
    __tablename__ = "claim_events"

    claim_id: Mapped[uuid.UUID] = mapped_column(_fk("claims"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_user_id: Mapped[uuid.UUID | None]
    actor_label: Mapped[str] = mapped_column(String(254), default="")
    type: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ClaimRecovery(IdMixin, TenantMixin, Base):
    """Recovered money = an actual credit linked to the claim (never inferred)."""

    __tablename__ = "claim_recoveries"
    __table_args__ = (UniqueConstraint("claim_id", "credit_id"),)

    claim_id: Mapped[uuid.UUID] = mapped_column(_fk("claims"), index=True)
    credit_id: Mapped[uuid.UUID] = mapped_column(_fk("credit_lines", "RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    linked_by: Mapped[uuid.UUID]
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimAttachment(IdMixin, TenantMixin, Base):
    __tablename__ = "claim_attachments"

    claim_id: Mapped[uuid.UUID] = mapped_column(_fk("claims"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
