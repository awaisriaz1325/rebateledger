"""Agreements YAML → engine value objects (format documented in docs/pilot-cli.md).

Strict by design: every field that changes money must be stated explicitly, and
decimal values must be quoted strings or integers — an unquoted ``0.02`` is a
YAML float and is rejected so money never passes through binary floating point.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from app.engine.models import (
    BaselineSource,
    Component,
    ComponentType,
    DateBasis,
    EligibilityRule,
    EngineInputError,
    Measure,
    NegativeResult,
    Period,
    PeriodType,
    PriorPeriodOffset,
    RoundingMode,
    RuleAction,
    RuleField,
    SpendBasis,
    Stacking,
    ThresholdComparison,
    Tier,
    VersionSnapshot,
    ZeroBaselinePolicy,
)


class AgreementFormatError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path


@dataclass(frozen=True, slots=True)
class AgreementSpec:
    agreement_id: str
    supplier_id: str
    name: str
    external_reference: str | None
    versions: tuple[VersionSnapshot, ...]


def _get(d: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in d:
        raise AgreementFormatError(path, f"'{key}' is required")
    return d[key]


def _str(value: Any, path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise AgreementFormatError(path, "must be text")
    text = str(value).strip()
    if not text:
        raise AgreementFormatError(path, "must not be empty")
    return text


def decimal_value(value: Any, path: str) -> Decimal:
    if isinstance(value, float):
        raise AgreementFormatError(path, f'write decimals as quoted text, e.g. "{value}"')
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise AgreementFormatError(path, "must be a decimal number in quotes")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise AgreementFormatError(path, f"'{value}' is not a decimal number") from None
    if not d.is_finite():
        raise AgreementFormatError(path, "must be finite")
    return d


def _opt_decimal(d: Mapping[str, Any], key: str, path: str) -> Decimal | None:
    value = d.get(key)
    return None if value is None else decimal_value(value, f"{path}.{key}")


def _date(value: Any, path: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise AgreementFormatError(path, "must be a date in YYYY-MM-DD form")


def _enum[E: StrEnum](cls: type[E], value: Any, path: str) -> E:
    try:
        return cls(value)
    except ValueError:
        allowed = ", ".join(m.value for m in cls)
        raise AgreementFormatError(path, f"'{value}' is not one of: {allowed}") from None


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise AgreementFormatError(path, "must be true or false")
    return value


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgreementFormatError(path, "must be a whole number")
    return value


def _tiers(raw: Any, path: str) -> tuple[Tier, ...]:
    if not isinstance(raw, list) or not raw:
        raise AgreementFormatError(path, "must be a non-empty list")
    tiers: list[Tier] = []
    for i, t in enumerate(raw):
        p = f"{path}[{i}]"
        if not isinstance(t, dict):
            raise AgreementFormatError(p, "must be a mapping")
        tiers.append(
            Tier(
                threshold=decimal_value(_get(t, "threshold", p), f"{p}.threshold"),
                rate=_opt_decimal(t, "rate", p),
                amount_per_unit=_opt_decimal(t, "amount_per_unit", p),
            )
        )
    return tuple(tiers)


def _component(raw: Any, path: str) -> Component:
    if not isinstance(raw, dict):
        raise AgreementFormatError(path, "must be a mapping")
    ctype = _enum(ComponentType, _get(raw, "type", path), f"{path}.type")
    source = raw.get("baseline_source")
    offset = raw.get("prior_period_offset")
    return Component(
        id=_str(_get(raw, "id", path), f"{path}.id"),
        type=ctype,
        rate=_opt_decimal(raw, "rate", path),
        amount_per_unit=_opt_decimal(raw, "amount_per_unit", path),
        tiers=_tiers(raw["tiers"], f"{path}.tiers") if "tiers" in raw else (),
        amount=_opt_decimal(raw, "amount", path),
        threshold=_opt_decimal(raw, "threshold", path),
        growth_pct=_opt_decimal(raw, "growth_pct", path),
        baseline_source=None
        if source is None
        else _enum(BaselineSource, source, f"{path}.baseline_source"),
        prior_period_offset=None
        if offset is None
        else _enum(PriorPeriodOffset, offset, f"{path}.prior_period_offset"),
    )


def _rule(raw: Any, path: str, index: int) -> EligibilityRule:
    if not isinstance(raw, dict):
        raise AgreementFormatError(path, "must be a mapping")
    field = _enum(RuleField, _get(raw, "field", path), f"{path}.field")
    values = raw.get("values", [])
    if not isinstance(values, list):
        raise AgreementFormatError(f"{path}.values", "must be a list")
    return EligibilityRule(
        id=str(raw.get("id") or f"rule{index + 1:02d}"),
        action=_enum(RuleAction, _get(raw, "action", path), f"{path}.action"),
        field=field,
        values=frozenset(_str(v, f"{path}.values") for v in values),
        flag=None if raw.get("flag") is None else _str(raw["flag"], f"{path}.flag"),
        min_amount=_opt_decimal(raw, "min_amount", path),
    )


def _version(
    raw: Any,
    path: str,
    agreement_id: str,
    supplier_id: str,
    name: str,
    ext_ref: str | None,
    members: frozenset[str] = frozenset(),
) -> VersionSnapshot:
    if not isinstance(raw, dict):
        raise AgreementFormatError(path, "must be a mapping")
    period = _get(raw, "period", path)
    if not isinstance(period, dict):
        raise AgreementFormatError(f"{path}.period", "must be a mapping")
    ptype = _enum(PeriodType, _get(period, "type", f"{path}.period"), f"{path}.period.type")
    custom: list[Period] = []
    for i, cp in enumerate(period.get("custom_periods", []) or []):
        p = f"{path}.period.custom_periods[{i}]"
        custom.append(
            Period(
                _date(_get(cp, "start", p), f"{p}.start"),
                _date(_get(cp, "end", p), f"{p}.end"),
                str(cp.get("label", "")),
            )
        )
    components_raw = _get(raw, "components", path)
    if not isinstance(components_raw, list) or not components_raw:
        raise AgreementFormatError(f"{path}.components", "must be a non-empty list")
    rules_raw = raw.get("eligibility", []) or []
    if not isinstance(rules_raw, list):
        raise AgreementFormatError(f"{path}.eligibility", "must be a list")
    eff_to = raw.get("effective_to")
    try:
        return VersionSnapshot(
            agreement_id=agreement_id,
            version_id=str(raw.get("version_id") or f"{agreement_id}-v{raw.get('version_no')}"),
            version_no=_int(_get(raw, "version_no", path), f"{path}.version_no"),
            supplier_id=supplier_id,
            member_supplier_ids=members,
            effective_from=_date(_get(raw, "effective_from", path), f"{path}.effective_from"),
            effective_to=None if eff_to is None else _date(eff_to, f"{path}.effective_to"),
            period_type=ptype,
            fiscal_year_start_month=_int(
                _get(period, "fiscal_year_start_month", f"{path}.period"),
                f"{path}.period.fiscal_year_start_month",
            ),
            date_basis=_enum(DateBasis, _get(raw, "date_basis", path), f"{path}.date_basis"),
            measure=_enum(Measure, _get(raw, "measure", path), f"{path}.measure"),
            spend_basis=_enum(SpendBasis, _get(raw, "spend_basis", path), f"{path}.spend_basis"),
            threshold_comparison=_enum(
                ThresholdComparison,
                _get(raw, "threshold_comparison", path),
                f"{path}.threshold_comparison",
            ),
            components=tuple(
                _component(c, f"{path}.components[{i}]") for i, c in enumerate(components_raw)
            ),
            negative_result=_enum(
                NegativeResult, _get(raw, "negative_result", path), f"{path}.negative_result"
            ),
            rounding_mode=_enum(
                RoundingMode, _get(raw, "rounding_mode", path), f"{path}.rounding_mode"
            ),
            payment_terms_days=_int(
                _get(raw, "payment_terms_days", path), f"{path}.payment_terms_days"
            ),
            stacking=_enum(Stacking, _get(raw, "stacking", path), f"{path}.stacking"),
            prorate_thresholds_on_partial_period=_bool(
                _get(raw, "prorate_thresholds_on_partial_period", path),
                f"{path}.prorate_thresholds_on_partial_period",
            ),
            zero_baseline_policy=_enum(
                ZeroBaselinePolicy,
                _get(raw, "zero_baseline_policy", path),
                f"{path}.zero_baseline_policy",
            ),
            eligibility=tuple(
                _rule(r, f"{path}.eligibility[{i}]", i) for i, r in enumerate(rules_raw)
            ),
            custom_periods=tuple(custom),
            cap_amount=_opt_decimal(raw, "cap_amount", path),
            minimum_payout=_opt_decimal(raw, "minimum_payout", path),
            agreement_name=name,
            external_reference=ext_ref,
        )
    except EngineInputError as exc:
        raise AgreementFormatError(path, str(exc)) from None


def parse_agreements(data: Any) -> list[AgreementSpec]:
    """Parse the top-level ``{"agreements": [...]}`` document."""
    if not isinstance(data, dict):
        raise AgreementFormatError("$", "top level must be a mapping with 'agreements'")
    raw_list = _get(data, "agreements", "$")
    if not isinstance(raw_list, list) or not raw_list:
        raise AgreementFormatError("$.agreements", "must be a non-empty list")
    specs: list[AgreementSpec] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_list):
        path = f"$.agreements[{i}]"
        if not isinstance(raw, dict):
            raise AgreementFormatError(path, "must be a mapping")
        agreement_id = _str(_get(raw, "id", path), f"{path}.id")
        if agreement_id in seen:
            raise AgreementFormatError(f"{path}.id", f"duplicate agreement id '{agreement_id}'")
        seen.add(agreement_id)
        supplier = _str(_get(raw, "supplier", path), f"{path}.supplier")
        name = str(raw.get("name") or agreement_id)
        ext = raw.get("external_reference")
        ext_ref = None if ext is None else _str(ext, f"{path}.external_reference")
        members_raw = raw.get("members", []) or []
        if not isinstance(members_raw, list):
            raise AgreementFormatError(f"{path}.members", "must be a list of supplier ids")
        members = frozenset(
            _str(m, f"{path}.members[{k}]") for k, m in enumerate(members_raw)
        )  # buying-group program: 'supplier' is the group, these suppliers' lines count
        versions_raw = _get(raw, "versions", path)
        if not isinstance(versions_raw, list) or not versions_raw:
            raise AgreementFormatError(f"{path}.versions", "must be a non-empty list")
        versions = tuple(
            _version(v, f"{path}.versions[{j}]", agreement_id, supplier, name, ext_ref, members)
            for j, v in enumerate(versions_raw)
        )
        specs.append(AgreementSpec(agreement_id, supplier, name, ext_ref, versions))
    return specs
