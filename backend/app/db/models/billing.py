"""Invoice billing and operator data (SPEC §4.14, §4.15).

Invoices are tenant-scoped (tenants read their own; platform admins manage all).
Operator tables (sequences, settings, pilot requests, announcements) are platform-only,
except announcements, which every signed-in user may read.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import SCHEMA, Base, IdMixin, TenantMixin


def _in(column: str, values: list[str]) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=f"{column}_valid")


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    VOID = "void"


class Invoice(IdMixin, TenantMixin, Base):
    """Issued invoices are immutable (DB trigger); corrections = void + reissue."""

    __tablename__ = "invoices"
    __table_args__ = (
        _in("status", [s.value for s in InvoiceStatus]),
        UniqueConstraint("number"),
        CheckConstraint("status = 'draft' OR number IS NOT NULL", name="issued_has_number"),
        Index("ix_invoices_status_due", "status", "due_date"),
    )

    number: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default=InvoiceStatus.DRAFT.value)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    seller: Mapped[dict[str, Any]] = mapped_column(default=dict)
    buyer: Mapped[dict[str, Any]] = mapped_column(default=dict)
    payment_instructions: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal(0))
    paid_on: Mapped[date | None] = mapped_column(Date)
    payment_reference: Mapped[str] = mapped_column(String(200), default="")
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str] = mapped_column(String(500), default="")
    replaces_id: Mapped[uuid.UUID | None]
    storage_key: Mapped[str | None] = mapped_column(String(200))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceLine(IdMixin, TenantMixin, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class InvoiceSequence(Base):
    """One row per year; incremented in the issuing transaction (no gaps, no collisions)."""

    __tablename__ = "invoice_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)


class OpsSetting(Base):
    """Operator settings (seller details, payment instructions, grace days). Never hard-coded."""

    __tablename__ = "ops_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PilotRequest(IdMixin, Base):
    __tablename__ = "pilot_requests"
    __table_args__ = (_in("status", ["new", "contacted", "converted", "declined", "spam"]),)

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(100), default="")
    supplier_count: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="new")
    operator_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeatureFlag(IdMixin, TenantMixin, Base):
    __tablename__ = "feature_flags"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)

    key: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Announcement(IdMixin, Base):
    __tablename__ = "announcements"
    __table_args__ = (_in("level", ["info", "warning"]),)

    message: Mapped[str] = mapped_column(String(500))
    level: Mapped[str] = mapped_column(String(10), default="info")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
