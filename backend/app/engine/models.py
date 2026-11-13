"""Immutable value objects for the rebate engine.

Everything here is pure data. Construction validates structure so the
calculation code can assume well-formed inputs. Nothing in this module may do
I/O, read the clock, or touch global state.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class EngineInputError(ValueError):
    """Raised when an engine input is structurally invalid (programming or data error)."""


# --------------------------------------------------------------------------- enums


class PeriodType(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"
    CUSTOM = "custom"


class DateBasis(StrEnum):
    INVOICE_DATE = "invoice_date"
    SHIP_DATE = "ship_date"
    RECEIPT_DATE = "receipt_date"


class Measure(StrEnum):
    SPEND = "spend"
    QUANTITY = "quantity"


class SpendBasis(StrEnum):
    NET_OF_RETURNS = "net_of_returns"
    GROSS = "gross"


class ThresholdComparison(StrEnum):
    GTE = "gte"
    GT = "gt"


class NegativeResult(StrEnum):
    FLOOR_AT_ZERO = "floor_at_zero"
    ALLOW_CLAWBACK = "allow_clawback"


class RoundingMode(StrEnum):
    HALF_UP = "half_up"
    HALF_EVEN = "half_even"


class Stacking(StrEnum):
    EXCLUSIVE = "exclusive"
    STACKABLE = "stackable"


class ZeroBaselinePolicy(StrEnum):
    NEEDS_REVIEW = "needs_review"
    QUALIFIES = "qualifies"
    DOES_NOT_QUALIFY = "does_not_qualify"


class ComponentType(StrEnum):
    FLAT_PERCENT = "flat_percent"
    PER_UNIT = "per_unit"
    TIERED_ALL_UNITS = "tiered_all_units"
    TIERED_INCREMENTAL = "tiered_incremental"
    GROWTH_INCREMENTAL = "growth_incremental"
    GROWTH_THRESHOLD = "growth_threshold"
    FIXED_BONUS = "fixed_bonus"


class BaselineSource(StrEnum):
    IMPORTED = "imported"
    PRIOR_PERIOD_COMPUTED = "prior_period_computed"


class PriorPeriodOffset(StrEnum):
    """Which earlier period a computed baseline is measured over.

    SPEC §4.4.2 says "the corresponding prior period" without defining it, so the
    choice is explicit per component instead of a hidden default (ADR 0010).
    """

    SAME_PERIOD_PRIOR_YEAR = "same_period_prior_year"
    IMMEDIATELY_PRECEDING = "immediately_preceding"


class RuleAction(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


class RuleField(StrEnum):
    SKU = "sku"
    CATEGORY = "category"
    BRANCH = "branch"
    FLAG = "flag"
    MIN_LINE_AMOUNT = "min_line_amount"


class Status(StrEnum):
    OK = "OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PARTIAL_PERIOD = "PARTIAL_PERIOD"
    BELOW_MINIMUM = "BELOW_MINIMUM"
    CAPPED = "CAPPED"
    NOT_EARNED = "NOT_EARNED"


class ReviewReason(StrEnum):
    VERSION_CHANGE_IN_PERIOD = "VERSION_CHANGE_IN_PERIOD"
    BASELINE_MISSING = "BASELINE_MISSING"
    BASELINE_ZERO = "BASELINE_ZERO"
    BASELINE_NEGATIVE = "BASELINE_NEGATIVE"
    BASELINE_AMBIGUOUS = "BASELINE_AMBIGUOUS"
    STACKING_CONFLICT = "STACKING_CONFLICT"
    GROWTH_PARTIAL_PERIOD = "GROWTH_PARTIAL_PERIOD"
    CLAWBACK_WITH_MINIMUM = "CLAWBACK_WITH_MINIMUM"


class ExclusionReason(StrEnum):
    DATE_BASIS_MISSING = "DATE_BASIS_MISSING"
    ATTRIBUTE_MISSING = "ATTRIBUTE_MISSING"
    EXCLUDED_BY_RULE = "EXCLUDED_BY_RULE"
    NOT_INCLUDED = "NOT_INCLUDED"
    BELOW_MIN_LINE_AMOUNT = "BELOW_MIN_LINE_AMOUNT"


class VersionResolution(StrEnum):
    """User decision for a period that contains a version boundary (SPEC §4.4.4)."""

    APPLY_OLD = "apply_old"
    APPLY_NEW = "apply_new"
    SPLIT = "split"


# --------------------------------------------------------------------------- helpers


def _require_decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise EngineInputError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise EngineInputError(f"{name} must be finite")
    return value


def _optional_decimal(name: str, value: object) -> Decimal | None:
    if value is None:
        return None
    return _require_decimal(name, value)


# --------------------------------------------------------------------------- value objects


@dataclass(frozen=True, slots=True)
class Period:
    """Inclusive date range. ``label`` is presentation only and excluded from comparisons."""

    start: date
    end: date
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise EngineInputError("period end is before start")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass(frozen=True, slots=True)
class Tier:
    threshold: Decimal
    rate: Decimal | None = None
    amount_per_unit: Decimal | None = None

    def __post_init__(self) -> None:
        _require_decimal("tier.threshold", self.threshold)
        _optional_decimal("tier.rate", self.rate)
        _optional_decimal("tier.amount_per_unit", self.amount_per_unit)
        if (self.rate is None) == (self.amount_per_unit is None):
            raise EngineInputError("tier needs exactly one of rate or amount_per_unit")
        if self.threshold < 0:
            raise EngineInputError("tier threshold must be >= 0")


@dataclass(frozen=True, slots=True)
class Component:
    id: str
    type: ComponentType
    rate: Decimal | None = None
    amount_per_unit: Decimal | None = None
    tiers: tuple[Tier, ...] = ()
    amount: Decimal | None = None
    threshold: Decimal | None = None
    growth_pct: Decimal | None = None
    baseline_source: BaselineSource | None = None
    prior_period_offset: PriorPeriodOffset | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise EngineInputError("component id is required")
        _optional_decimal("rate", self.rate)
        _optional_decimal("amount_per_unit", self.amount_per_unit)
        _optional_decimal("amount", self.amount)
        _optional_decimal("threshold", self.threshold)
        _optional_decimal("growth_pct", self.growth_pct)
        t = self.type
        if t is ComponentType.FLAT_PERCENT and self.rate is None:
            raise EngineInputError(f"{self.id}: flat_percent needs rate")
        if t is ComponentType.PER_UNIT and self.amount_per_unit is None:
            raise EngineInputError(f"{self.id}: per_unit needs amount_per_unit")
        if t in (ComponentType.TIERED_ALL_UNITS, ComponentType.TIERED_INCREMENTAL):
            if not self.tiers:
                raise EngineInputError(f"{self.id}: tiered component needs tiers")
            for a, b in zip(self.tiers, self.tiers[1:], strict=False):
                if b.threshold <= a.threshold:
                    raise EngineInputError(f"{self.id}: tier thresholds must be strictly ascending")
            kinds = {tier.rate is not None for tier in self.tiers}
            if len(kinds) != 1:
                raise EngineInputError(f"{self.id}: tiers must all use rate or all amount_per_unit")
        if t is ComponentType.GROWTH_INCREMENTAL and self.rate is None:
            raise EngineInputError(f"{self.id}: growth_incremental needs rate")
        if t is ComponentType.GROWTH_THRESHOLD and (self.rate is None or self.growth_pct is None):
            raise EngineInputError(f"{self.id}: growth_threshold needs rate and growth_pct")
        if t in (ComponentType.GROWTH_INCREMENTAL, ComponentType.GROWTH_THRESHOLD):
            if self.baseline_source is None:
                raise EngineInputError(f"{self.id}: growth component needs baseline_source")
            if (
                self.baseline_source is BaselineSource.PRIOR_PERIOD_COMPUTED
                and self.prior_period_offset is None
            ):
                raise EngineInputError(
                    f"{self.id}: prior_period_computed baseline needs prior_period_offset"
                )
        if t is ComponentType.FIXED_BONUS and (self.amount is None or self.threshold is None):
            raise EngineInputError(f"{self.id}: fixed_bonus needs amount and threshold")

    @property
    def is_growth(self) -> bool:
        return self.type in (ComponentType.GROWTH_INCREMENTAL, ComponentType.GROWTH_THRESHOLD)

    @property
    def uses_rate_tiers(self) -> bool:
        return bool(self.tiers) and self.tiers[0].rate is not None


@dataclass(frozen=True, slots=True)
class EligibilityRule:
    id: str
    action: RuleAction
    field: RuleField
    values: frozenset[str] = frozenset()
    flag: str | None = None
    min_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if self.field is RuleField.FLAG and not self.flag:
            raise EngineInputError(f"{self.id}: flag rule needs a flag name")
        if self.field is RuleField.MIN_LINE_AMOUNT:
            if self.action is not RuleAction.INCLUDE:
                raise EngineInputError(f"{self.id}: min_line_amount must be an include rule")
            _require_decimal("min_amount", self.min_amount)
        if self.field in (RuleField.SKU, RuleField.CATEGORY, RuleField.BRANCH) and not self.values:
            raise EngineInputError(f"{self.id}: list rule needs at least one value")


@dataclass(frozen=True, slots=True)
class VersionSnapshot:
    """A frozen copy of one agreement version: everything the engine needs, nothing else."""

    agreement_id: str
    version_id: str
    version_no: int
    supplier_id: str
    effective_from: date
    effective_to: date | None
    period_type: PeriodType
    fiscal_year_start_month: int
    date_basis: DateBasis
    measure: Measure
    spend_basis: SpendBasis
    threshold_comparison: ThresholdComparison
    components: tuple[Component, ...]
    negative_result: NegativeResult
    rounding_mode: RoundingMode
    payment_terms_days: int
    stacking: Stacking
    prorate_thresholds_on_partial_period: bool
    zero_baseline_policy: ZeroBaselinePolicy
    eligibility: tuple[EligibilityRule, ...] = ()
    custom_periods: tuple[Period, ...] = ()
    cap_amount: Decimal | None = None
    minimum_payout: Decimal | None = None
    agreement_name: str = field(default="", compare=False)
    external_reference: str | None = None
    member_supplier_ids: frozenset[str] = field(
        default_factory=frozenset, metadata={"omit_if_empty": True}
    )
    """Buying-group program (v1.1, ADR 0017 §3): purchases from these member suppliers count,
    and ``supplier_id`` is the group (the payer). Empty for a normal supplier agreement; then
    it is left out of the input hash so existing results hash exactly as before."""

    @property
    def line_supplier_ids(self) -> frozenset[str]:
        """Suppliers whose purchase lines this agreement reads."""
        return self.member_supplier_ids or frozenset({self.supplier_id})

    def __post_init__(self) -> None:
        if self.supplier_id in self.member_supplier_ids:
            raise EngineInputError("a buying group cannot be its own member")
        if any(not m for m in self.member_supplier_ids):
            raise EngineInputError("member supplier ids must be non-empty")
        if not 1 <= self.fiscal_year_start_month <= 12:
            raise EngineInputError("fiscal_year_start_month must be 1..12")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise EngineInputError("effective_to is before effective_from")
        if not self.components:
            raise EngineInputError("a version needs at least one component")
        if len({c.id for c in self.components}) != len(self.components):
            raise EngineInputError("component ids must be unique")
        if self.payment_terms_days < 0:
            raise EngineInputError("payment_terms_days must be >= 0")
        for name in ("cap_amount", "minimum_payout"):
            value = _optional_decimal(name, getattr(self, name))
            if value is not None and value < 0:
                raise EngineInputError(f"{name} must be >= 0")
        if self.period_type is PeriodType.CUSTOM:
            if not self.custom_periods:
                raise EngineInputError("custom period type needs custom_periods")
            ordered = sorted(self.custom_periods, key=lambda p: p.start)
            for a, b in itertools.pairwise(ordered):
                if b.start <= a.end:
                    raise EngineInputError("custom periods overlap")
        for c in self.components:
            if c.type is ComponentType.TIERED_INCREMENTAL:
                if self.measure is Measure.SPEND and not c.uses_rate_tiers:
                    raise EngineInputError(
                        f"{c.id}: tiered_incremental with measure=spend needs rate tiers"
                    )
                if self.measure is Measure.QUANTITY and c.uses_rate_tiers:
                    raise EngineInputError(
                        f"{c.id}: tiered_incremental with measure=quantity needs per-unit tiers"
                    )

    @property
    def effective_period(self) -> Period:
        end = self.effective_to if self.effective_to is not None else date.max
        return Period(self.effective_from, end)


@dataclass(frozen=True, slots=True)
class PurchaseLine:
    """One normalised purchase line. Negative quantity/amount means a return."""

    line_id: str
    supplier_id: str
    quantity: Decimal
    amount: Decimal
    sku: str | None = None
    invoice_date: date | None = None
    ship_date: date | None = None
    receipt_date: date | None = None
    branch: str | None = None
    category: str | None = None
    flags: tuple[tuple[str, bool], ...] = ()

    def __post_init__(self) -> None:
        _require_decimal("quantity", self.quantity)
        _require_decimal("amount", self.amount)
        names = [n for n, _ in self.flags]
        if len(set(names)) != len(names):
            raise EngineInputError(f"line {self.line_id}: duplicate flag names")

    def basis_date(self, basis: DateBasis) -> date | None:
        if basis is DateBasis.INVOICE_DATE:
            return self.invoice_date
        if basis is DateBasis.SHIP_DATE:
            return self.ship_date
        return self.receipt_date

    def flag(self, name: str) -> bool | None:
        for n, v in self.flags:
            if n == name:
                return v
        return None

    @staticmethod
    def make_flags(values: Mapping[str, bool]) -> tuple[tuple[str, bool], ...]:
        return tuple(sorted(values.items()))


@dataclass(frozen=True, slots=True)
class Baseline:
    """An imported baseline measure for one agreement-period."""

    agreement_id: str
    period_start: date
    period_end: date
    value: Decimal
    baseline_id: str = ""

    def __post_init__(self) -> None:
        _require_decimal("baseline.value", self.value)


@dataclass(frozen=True, slots=True)
class StackingConflict:
    other_agreement_id: str
    line_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalcOptions:
    """Per-call options. Nothing here defaults from the environment or clock.

    ``data_coverage_start`` is the earliest basis date for which this supplier's
    purchase data is known to be complete. A computed baseline whose period starts
    earlier cannot be trusted and is reported as BASELINE_MISSING.
    """

    data_coverage_start: date | None = None
    stacking_conflicts: tuple[StackingConflict, ...] = ()
    review_reason: ReviewReason | None = None
    review_message: str = ""
    full_period: Period | None = None
    """The un-clipped period, when ``period`` is a clipped or split sub-period."""
    version_resolution: VersionResolution | None = None
    """Set when the user resolved a version boundary inside the full period."""
