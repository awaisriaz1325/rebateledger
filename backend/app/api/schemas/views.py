"""Typed response models for aggregate/view endpoints (so the frontend client is generated)."""

from __future__ import annotations

import uuid
from datetime import date

from app.api.schemas.common import DecimalStr, Out


class LinkedAmount(Out):
    amount: str
    link: str


class AgingBucket(Out):
    count: int
    amount: str


class OpenClaims(Out):
    count: int
    amount: str
    aging: dict[str, AgingBucket]
    link: str


class LinkedCount(Out):
    count: int
    link: str


class SupplierAmount(Out):
    supplier_name: str
    amount: str


class FreshnessRow(Out):
    supplier_id: str
    supplier_name: str
    latest_purchase_date: str | None
    days_old: int | None
    stale: bool


class Freshness(Out):
    threshold_days: int
    suppliers: list[FreshnessRow]
    link: str


class OpportunityOut(Out):
    agreement_id: uuid.UUID
    agreement_name: str
    supplier_name: str
    period_end: date
    days_remaining: int
    measure_kind: str
    next_tier: int
    gap: DecimalStr
    potential_additional: DecimalStr | None
    return_per_unit: DecimalStr | None
    required_daily: DecimalStr
    current_daily: DecimalStr
    projected_reaches_next: bool
    data_as_of: date | None


class DashboardOut(Out):
    as_of: str
    identified_open_variance: LinkedAmount
    recovered_this_year: LinkedAmount
    open_claims: OpenClaims
    needs_review: LinkedCount
    top_suppliers_by_open_variance: list[SupplierAmount]
    tier_opportunities: LinkedCount
    top_opportunities: list[OpportunityOut]
    data_freshness: Freshness
    has_results: bool


class FieldSpecOut(Out):
    name: str
    label: str
    required: bool
    kind: str


class PresetSuggestionOut(Out):
    id: str
    erp: str
    report: str
    verified: bool


class ImportPreviewOut(Out):
    header: list[str]
    sample_rows: list[list[str]]
    suggested_columns: dict[str, str]
    date_format_candidates: dict[str, list[str]]
    fields: list[FieldSpecOut]
    supports_flags: bool
    preset_suggestion: PresetSuggestionOut | None
    applied_preset_id: str | None


class RowIssueOut(Out):
    row: int
    column: str
    value: str
    code: str
    message: str
    severity: str


class PreviewRowOut(Out):
    row: int
    cells: list[str]
    ok: bool
    issues: list[RowIssueOut]


class ValidatePreviewOut(Out):
    config_problems: list[str]
    rows: list[PreviewRowOut]


class ErrorPageOut(Out):
    items: list[RowIssueOut]
    total: int


class ResultChange(Out):
    agreement_id: str
    period_start: str
    period_end: str
    before: str | None
    after: str | None
    before_version: int | None
    after_version: int | None
    before_statuses: list[str]
    after_statuses: list[str]
    inputs_changed: bool


class RunDiffOut(Out):
    from_run: int
    to_run: int
    results_changed: list[ResultChange]
    batches_added: list[str]
    batches_removed: list[str]
    versions_added: list[str]
    versions_removed: list[str]
    tolerance_changed: bool
    engine_version_changed: bool


class TraceStepOut(Out):
    step: int
    name: str
    description: str
    values: dict[str, str]


class ReasonOut(Out):
    code: str
    message: str


class ComponentValueOut(Out):
    component_id: str
    type: str
    value: str | None
    formula: str
    tier_reached: int | None
    baseline: str | None = None
