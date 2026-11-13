"""Suppliers, agreements, imports, plans (SPEC §4.3–4.5, §4.14, §5)."""

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
    text,
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


def _in(column: str, values: list[str], name: str | None = None) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name or f"{column}_valid")


# --------------------------------------------------------------------------- suppliers


class Supplier(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        _in("status", ["active", "inactive"]),
        _in("kind", ["supplier", "buying_group"]),
        Index("ix_suppliers_tenant_name", "tenant_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(200))
    #: "buying_group": a payer whose programs count purchases from its member suppliers
    #: (v1.1 Phase 16). Purchases are never imported against a group.
    kind: Mapped[str] = mapped_column(String(20), default="supplier", server_default="supplier")
    status: Mapped[str] = mapped_column(String(20), default="active")
    category_tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    payment_notes: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(_fk("suppliers", "SET NULL"))


class BuyingGroupMember(IdMixin, TenantMixin, Base):
    """A supplier whose purchases count toward the group's programs (v1.1 Phase 16)."""

    __tablename__ = "buying_group_members"
    __table_args__ = (UniqueConstraint("tenant_id", "group_id", "supplier_id"),)

    group_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "CASCADE"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierAlias(IdMixin, TenantMixin, TimestampMixin, Base):
    """A supplier code as it appears in import files. Unique per tenant (case-insensitive)."""

    __tablename__ = "supplier_aliases"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    """Stored upper-cased and trimmed."""


class SupplierContact(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "supplier_contacts"

    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[str] = mapped_column(String(100), default="")


class Product(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)

    sku: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(_fk("suppliers", "SET NULL"))
    batch_id: Mapped[uuid.UUID | None]


# --------------------------------------------------------------------------- agreements


class VersionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class Agreement(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "agreements"
    __table_args__ = (_in("status", ["active", "archived"]),)

    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    external_reference: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active")
    owner_user_id: Mapped[uuid.UUID | None]
    notes: Mapped[str] = mapped_column(Text, default="")


class AgreementVersion(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    """Effective-dated rules. Immutable once not a draft (enforced by a DB trigger)."""

    __tablename__ = "agreement_versions"
    __table_args__ = (
        UniqueConstraint("agreement_id", "version_no"),
        _in("status", [s.value for s in VersionStatus]),
        _in("period_type", ["monthly", "quarterly", "semiannual", "annual", "custom"]),
        _in("date_basis", ["invoice_date", "ship_date", "receipt_date"]),
        _in("measure", ["spend", "quantity"]),
        _in("spend_basis", ["net_of_returns", "gross"]),
        _in("threshold_comparison", ["gte", "gt"]),
        _in("negative_result", ["floor_at_zero", "allow_clawback"]),
        _in("rounding_mode", ["half_up", "half_even"]),
        _in("stacking", ["exclusive", "stackable"]),
        _in("zero_baseline_policy", ["needs_review", "qualifies", "does_not_qualify"]),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from", name="effective_range"
        ),
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_month"),
        CheckConstraint("payment_terms_days >= 0", name="terms_non_negative"),
    )

    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=VersionStatus.DRAFT.value)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(20))
    fiscal_aligned: Mapped[bool] = mapped_column(Boolean, default=True)
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer)
    """Snapshot of the month used (tenant fiscal start if aligned, else 1)."""
    custom_periods: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    date_basis: Mapped[str] = mapped_column(String(20))
    measure: Mapped[str] = mapped_column(String(20))
    spend_basis: Mapped[str] = mapped_column(String(20))
    threshold_comparison: Mapped[str] = mapped_column(String(5))
    negative_result: Mapped[str] = mapped_column(String(20))
    rounding_mode: Mapped[str] = mapped_column(String(20))
    payment_terms_days: Mapped[int] = mapped_column(Integer)
    stacking: Mapped[str] = mapped_column(String(20))
    prorate_thresholds_on_partial_period: Mapped[bool] = mapped_column(Boolean)
    zero_baseline_policy: Mapped[str] = mapped_column(String(20))
    cap_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    minimum_payout: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    summary: Mapped[str] = mapped_column(Text, default="")
    submitted_by: Mapped[uuid.UUID | None]
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None]
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgreementComponent(IdMixin, TenantMixin, Base):
    __tablename__ = "agreement_components"
    __table_args__ = (
        UniqueConstraint("version_id", "component_key"),
        _in(
            "type",
            [
                "flat_percent",
                "per_unit",
                "tiered_all_units",
                "tiered_incremental",
                "growth_incremental",
                "growth_threshold",
                "fixed_bonus",
            ],
        ),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(_fk("agreement_versions"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    component_key: Mapped[str] = mapped_column(String(60))
    type: Mapped[str] = mapped_column(String(30))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    amount_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    growth_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    baseline_source: Mapped[str | None] = mapped_column(String(30))
    prior_period_offset: Mapped[str | None] = mapped_column(String(30))


class AgreementTier(IdMixin, TenantMixin, Base):
    __tablename__ = "agreement_tiers"
    __table_args__ = (UniqueConstraint("component_id", "position"),)

    component_id: Mapped[uuid.UUID] = mapped_column(_fk("agreement_components"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    amount_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class EligibilityRuleRow(IdMixin, TenantMixin, Base):
    __tablename__ = "eligibility_rules"
    __table_args__ = (
        UniqueConstraint("version_id", "rule_key"),
        _in("action", ["include", "exclude"]),
        _in("field", ["sku", "category", "branch", "flag", "min_line_amount"]),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(_fk("agreement_versions"), index=True)
    rule_key: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(10))
    field: Mapped[str] = mapped_column(String(20))
    values: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    flag: Mapped[str | None] = mapped_column(String(60))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class AgreementAttachment(IdMixin, TenantMixin, Base):
    __tablename__ = "agreement_attachments"

    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(IdMixin, TenantMixin, Base):
    """Four-eyes requests (agreement activation, claim write-off)."""

    __tablename__ = "approvals"
    __table_args__ = (
        _in("object_type", ["agreement_version", "claim_write_off"]),
        _in("status", ["pending", "approved", "rejected", "cancelled"]),
        CheckConstraint(
            "decided_by IS NULL OR decided_by <> requested_by", name="no_self_approval"
        ),
        Index("ix_approvals_object", "tenant_id", "object_type", "object_id"),
    )

    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_by: Mapped[uuid.UUID]
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    request_note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[uuid.UUID | None]
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --------------------------------------------------------------------------- imports


class ImportType(StrEnum):
    PURCHASES = "purchases"
    CREDITS = "credits"
    BASELINES = "baselines"
    PRODUCTS = "products"
    SUPPLIERS = "suppliers"
    SALES = "sales"  # v1.1 Phase 17: sales lines for ship-and-debit / SPA claims


class BatchStatus(StrEnum):
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    VALIDATED = "validated"
    COMMITTING = "committing"
    COMMITTED = "committed"
    FAILED = "failed"
    VOIDED = "voided"


class ImportMapping(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, Base):
    """Saved, versioned mapping templates (SPEC §4.5.2 step 3)."""

    __tablename__ = "import_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "import_type", "name", "version"),
        _in("import_type", [t.value for t in ImportType]),
    )

    name: Mapped[str] = mapped_column(String(120))
    import_type: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(_fk("suppliers", "SET NULL"))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class ImportBatch(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        _in("import_type", [t.value for t in ImportType]),
        _in("status", [s.value for s in BatchStatus]),
        Index("ix_import_batches_hash", "tenant_id", "file_hash"),
    )

    import_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=BatchStatus.UPLOADED.value)
    filename: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    mapping_id: Mapped[uuid.UUID | None] = mapped_column(_fk("import_mappings", "SET NULL"))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Detection + mapping + formats chosen for this batch."""
    commit_mode: Mapped[str | None] = mapped_column(String(20))
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    duplicate_of_batch_id: Mapped[uuid.UUID | None]
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None]
    void_reason: Mapped[str] = mapped_column(String(500), default="")
    job_id: Mapped[uuid.UUID | None]


class ImportRowError(IdMixin, TenantMixin, Base):
    __tablename__ = "import_row_errors"
    __table_args__ = (Index("ix_import_row_errors_batch", "batch_id", "row_number"),)

    batch_id: Mapped[uuid.UUID] = mapped_column(_fk("import_batches"))
    row_number: Mapped[int] = mapped_column(Integer)
    column_name: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[str] = mapped_column(String(200), default="")
    """Truncated cell value shown to the importing user only; never logged."""
    code: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(10), default="error")


class PurchaseLineRow(TenantMixin, Base):
    __tablename__ = "purchase_lines"
    __table_args__ = (
        Index("ix_purchase_lines_invoice_date", "tenant_id", "supplier_id", "invoice_date"),
        Index("ix_purchase_lines_ship_date", "tenant_id", "supplier_id", "ship_date"),
        Index("ix_purchase_lines_receipt_date", "tenant_id", "supplier_id", "receipt_date"),
        Index("ix_purchase_lines_batch", "batch_id"),
        Index(
            "uq_purchase_lines_dedupe",
            "tenant_id",
            "supplier_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("NOT voided"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(_fk("import_batches", "RESTRICT"))
    source_row: Mapped[int] = mapped_column(Integer)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    dedupe_key: Mapped[bytes] = mapped_column(LargeBinary(32))
    invoice_number: Mapped[str] = mapped_column(String(100))
    line_number: Mapped[str | None] = mapped_column(String(50))
    sku: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    ship_date: Mapped[date | None] = mapped_column(Date)
    receipt_date: Mapped[date | None] = mapped_column(Date)
    branch: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    flags: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_return: Mapped[bool] = mapped_column(Boolean, default=False)
    voided: Mapped[bool] = mapped_column(Boolean, default=False)


class CreditLineRow(IdMixin, TenantMixin, Base):
    __tablename__ = "credit_lines"
    __table_args__ = (
        Index("ix_credit_lines_date", "tenant_id", "supplier_id", "credit_date"),
        Index(
            "uq_credit_lines_dedupe",
            "tenant_id",
            "supplier_id",
            "credit_reference",
            unique=True,
            postgresql_where=text("NOT voided"),
        ),
    )

    batch_id: Mapped[uuid.UUID | None] = mapped_column(_fk("import_batches", "RESTRICT"))
    """NULL for credits entered manually (e.g. recording a recovery)."""
    source_row: Mapped[int | None] = mapped_column(Integer)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    credit_reference: Mapped[str] = mapped_column(String(100))
    credit_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    memo: Mapped[str] = mapped_column(String(500), default="")
    agreement_reference: Mapped[str | None] = mapped_column(String(100))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_label: Mapped[str | None] = mapped_column(String(40))
    possible_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    entered_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BaselineRow(IdMixin, TenantMixin, Base):
    __tablename__ = "baselines"
    __table_args__ = (Index("ix_baselines_agreement", "tenant_id", "agreement_id", "period_start"),)

    batch_id: Mapped[uuid.UUID] = mapped_column(_fk("import_batches", "RESTRICT"))
    source_row: Mapped[int] = mapped_column(Integer)
    agreement_id: Mapped[uuid.UUID] = mapped_column(_fk("agreements"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    notes: Mapped[str] = mapped_column(String(500), default="")
    voided: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- plans & subscriptions


class Plan(IdMixin, TimestampMixin, Base):
    """Platform-wide plan catalog (not tenant data). Prices are [PROPOSED DEFAULT]."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    max_active_agreements: Mapped[int | None] = mapped_column(Integer)
    max_users: Mapped[int | None] = mapped_column(Integer)
    max_import_rows_per_month: Mapped[int | None] = mapped_column(BigInteger)
    max_storage_mb: Mapped[int | None] = mapped_column(Integer)
    features: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SubscriptionStatus(StrEnum):
    PILOT = "pilot"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Subscription(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        _in("status", [s.value for s in SubscriptionStatus]),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(_fk("plans", "RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default=SubscriptionStatus.PILOT.value)
    term_start: Mapped[date | None] = mapped_column(Date)
    term_end: Mapped[date | None] = mapped_column(Date)
    limit_overrides: Mapped[dict[str, Any]] = mapped_column(default=dict)
    billing_contact_name: Mapped[str] = mapped_column(String(200), default="")
    billing_contact_email: Mapped[str] = mapped_column(String(254), default="")
    past_due_since: Mapped[date | None] = mapped_column(Date)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AccrualExport(IdMixin, TenantMixin, Base):
    """A downloaded month-end accrual journal (v1.1 Phase 15): who, when, what, file hash.

    ``lines`` keeps the exported amounts per agreement period so a later export for the same
    closing date can show what changed.
    """

    __tablename__ = "accrual_exports"
    __table_args__ = (Index("ix_accrual_exports_closing", "tenant_id", "closing_date"),)

    closing_date: Mapped[date] = mapped_column(Date)
    format: Mapped[str] = mapped_column(String(20))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_count: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(String(64))
    lines: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- SPA / ship-and-debit (v1.1 Phase 17)


class SaleLineRow(TenantMixin, Base):
    """A line the distributor sold (contains customer names: tenant data, never logged)."""

    __tablename__ = "sales_lines"
    __table_args__ = (
        Index("ix_sales_lines_supplier_date", "tenant_id", "supplier_id", "invoice_date"),
        Index("ix_sales_lines_batch", "batch_id"),
        Index(
            "uq_sales_lines_dedupe",
            "tenant_id",
            "supplier_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("NOT voided"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(_fk("import_batches", "RESTRICT"))
    source_row: Mapped[int] = mapped_column(Integer)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    dedupe_key: Mapped[bytes] = mapped_column(LargeBinary(32))
    invoice_number: Mapped[str] = mapped_column(String(100))
    line_number: Mapped[str | None] = mapped_column(String(50))
    invoice_date: Mapped[date] = mapped_column(Date)
    customer: Mapped[str | None] = mapped_column(String(200))
    job: Mapped[str | None] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sell_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    voided: Mapped[bool] = mapped_column(Boolean, default=False)


class Spa(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    """A special pricing agreement: the supplier pays back (book cost − SPA cost) per unit sold."""

    __tablename__ = "spas"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "spa_number"),
        _in("status", ["active", "inactive"]),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    spa_number: Mapped[str] = mapped_column(String(100))
    customer: Mapped[str | None] = mapped_column(String(200))
    job: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    claim_deadline_days: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")
    notes: Mapped[str] = mapped_column(Text, default="")


class SpaItem(IdMixin, TenantMixin, Base):
    __tablename__ = "spa_items"
    __table_args__ = (UniqueConstraint("spa_id", "sku"),)

    spa_id: Mapped[uuid.UUID] = mapped_column(_fk("spas", "CASCADE"))
    sku: Mapped[str] = mapped_column(String(100))
    book_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    spa_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    quantity_cap: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class SpaClaim(IdMixin, TenantMixin, TimestampMixin, AuthorMixin, VersionedMixin, Base):
    __tablename__ = "spa_claims"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        _in("status", ["draft", "submitted", "paid", "partially_paid", "rejected"]),
    )

    number: Mapped[int] = mapped_column(Integer)
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_count: Mapped[int] = mapped_column(Integer)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    credit_reference: Mapped[str] = mapped_column(String(100), default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")


class SpaMatchRow(TenantMixin, Base):
    """Matcher output per sale line (rebuilt by the spa_match job, except lines in a claim)."""

    __tablename__ = "spa_matches"
    __table_args__ = (
        Index("ix_spa_matches_status", "tenant_id", "supplier_id", "status"),
        Index("ix_spa_matches_claim", "claim_id"),
    )

    sale_line_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{SCHEMA}.sales_lines.id", ondelete="CASCADE"), primary_key=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(_fk("suppliers", "RESTRICT"))
    spa_id: Mapped[uuid.UUID | None] = mapped_column(_fk("spas", "SET NULL"))
    status: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    claimable_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    claimable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    unit_difference: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    deadline: Mapped[date | None] = mapped_column(Date)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(_fk("spa_claims", "SET NULL"))
    engine_version: Mapped[str] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
