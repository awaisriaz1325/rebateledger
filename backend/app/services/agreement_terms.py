"""Agreement version terms: API schema ⇄ DB rows ⇄ engine snapshot, plus the
deterministic plain-English summary (SPEC §4.4.5 — template code, never AI)."""

from __future__ import annotations

import itertools
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas.common import In, MoneyIn, Name, RateIn
from app.core.errors import AppError
from app.db.models.business import (
    Agreement,
    AgreementComponent,
    AgreementTier,
    AgreementVersion,
    EligibilityRuleRow,
)
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

Key = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")]
Value = Annotated[str, Field(min_length=1, max_length=100)]


class TierIn(In):
    threshold: MoneyIn
    rate: RateIn | None = None
    amount_per_unit: MoneyIn | None = None


class ComponentIn(In):
    key: Key
    type: ComponentType
    rate: RateIn | None = None
    amount_per_unit: MoneyIn | None = None
    amount: MoneyIn | None = None
    threshold: MoneyIn | None = None
    growth_pct: RateIn | None = None
    baseline_source: BaselineSource | None = None
    prior_period_offset: PriorPeriodOffset | None = None
    tiers: Annotated[list[TierIn], Field(default_factory=list, max_length=20)]


class RuleIn(In):
    key: Key | None = None
    action: RuleAction
    field: RuleField
    values: Annotated[list[Value], Field(default_factory=list, max_length=1000)]
    flag: Annotated[str | None, Field(max_length=60)] = None
    min_amount: MoneyIn | None = None


class CustomPeriodIn(In):
    start: date
    end: date
    label: Annotated[str, Field(max_length=40)] = ""


class VersionTermsIn(In):
    """Every money-affecting field is required: no hidden defaults."""

    effective_from: date
    effective_to: date | None
    period_type: PeriodType
    fiscal_aligned: bool
    custom_periods: Annotated[list[CustomPeriodIn], Field(default_factory=list, max_length=60)]
    date_basis: DateBasis
    measure: Measure
    spend_basis: SpendBasis
    threshold_comparison: ThresholdComparison
    negative_result: NegativeResult
    rounding_mode: RoundingMode
    payment_terms_days: Annotated[int, Field(ge=0, le=730)]
    stacking: Stacking
    prorate_thresholds_on_partial_period: bool
    zero_baseline_policy: ZeroBaselinePolicy
    cap_amount: MoneyIn | None = None
    minimum_payout: MoneyIn | None = None
    eligibility: Annotated[list[RuleIn], Field(default_factory=list, max_length=50)]
    components: Annotated[list[ComponentIn], Field(min_length=1, max_length=10)]


class AgreementCreateIn(In):
    supplier_id: uuid.UUID
    name: Name
    external_reference: Annotated[str | None, Field(max_length=100)] = None
    notes: Annotated[str, Field(max_length=5000)] = ""
    terms: VersionTermsIn


# --------------------------------------------------------------------------- snapshot


def to_snapshot(
    terms: VersionTermsIn,
    *,
    agreement_id: str,
    version_id: str,
    version_no: int,
    supplier_id: str,
    fiscal_start: int,
    name: str = "",
    external_reference: str | None = None,
) -> VersionSnapshot:
    """Engine validation is the single source of truth for structural rules."""
    try:
        return VersionSnapshot(
            agreement_id=agreement_id,
            version_id=version_id,
            version_no=version_no,
            supplier_id=supplier_id,
            effective_from=terms.effective_from,
            effective_to=terms.effective_to,
            period_type=terms.period_type,
            fiscal_year_start_month=fiscal_start if terms.fiscal_aligned else 1,
            date_basis=terms.date_basis,
            measure=terms.measure,
            spend_basis=terms.spend_basis,
            threshold_comparison=terms.threshold_comparison,
            components=tuple(
                Component(
                    id=c.key,
                    type=c.type,
                    rate=c.rate,
                    amount_per_unit=c.amount_per_unit,
                    tiers=tuple(Tier(t.threshold, t.rate, t.amount_per_unit) for t in c.tiers),
                    amount=c.amount,
                    threshold=c.threshold,
                    growth_pct=c.growth_pct,
                    baseline_source=c.baseline_source,
                    prior_period_offset=c.prior_period_offset,
                )
                for c in terms.components
            ),
            negative_result=terms.negative_result,
            rounding_mode=terms.rounding_mode,
            payment_terms_days=terms.payment_terms_days,
            stacking=terms.stacking,
            prorate_thresholds_on_partial_period=terms.prorate_thresholds_on_partial_period,
            zero_baseline_policy=terms.zero_baseline_policy,
            eligibility=tuple(
                EligibilityRule(
                    id=r.key or f"rule{i + 1:02d}",
                    action=r.action,
                    field=r.field,
                    values=frozenset(v.strip() for v in r.values),
                    flag=r.flag,
                    min_amount=r.min_amount,
                )
                for i, r in enumerate(terms.eligibility)
            ),
            custom_periods=tuple(Period(p.start, p.end, p.label) for p in terms.custom_periods),
            cap_amount=terms.cap_amount,
            minimum_payout=terms.minimum_payout,
            agreement_name=name,
            external_reference=external_reference,
        )
    except EngineInputError as exc:
        raise AppError(422, "TERMS_INVALID", "Agreement terms are invalid", str(exc)) from None


def warnings_for(terms: VersionTermsIn) -> list[str]:
    """Non-blocking warnings (SPEC §4.4.2: decreasing tier rates are allowed with a warning)."""
    out = []
    for c in terms.components:
        rates = [t.rate if t.rate is not None else t.amount_per_unit for t in c.tiers]
        if any(b is not None and a is not None and b < a for a, b in itertools.pairwise(rates)):
            out.append(f"Component {c.key}: tier rates decrease as tiers rise.")
    return out


def write_rows(
    db: Session, version: AgreementVersion, terms: VersionTermsIn, snapshot: VersionSnapshot
) -> None:
    """Replace a draft version's terms (children rows recreated)."""
    tid = version.tenant_id
    for model in (EligibilityRuleRow, AgreementComponent):
        db.execute(delete(model).where(model.version_id == version.id))
    version.effective_from = terms.effective_from
    version.effective_to = terms.effective_to
    version.period_type = terms.period_type.value
    version.fiscal_aligned = terms.fiscal_aligned
    version.fiscal_year_start_month = snapshot.fiscal_year_start_month
    version.custom_periods = [
        {"start": p.start.isoformat(), "end": p.end.isoformat(), "label": p.label}
        for p in terms.custom_periods
    ]
    for f in (
        "date_basis",
        "measure",
        "spend_basis",
        "threshold_comparison",
        "negative_result",
        "rounding_mode",
        "stacking",
        "zero_baseline_policy",
    ):
        setattr(version, f, getattr(terms, f).value)
    version.payment_terms_days = terms.payment_terms_days
    version.prorate_thresholds_on_partial_period = terms.prorate_thresholds_on_partial_period
    version.cap_amount = terms.cap_amount
    version.minimum_payout = terms.minimum_payout
    version.summary = summarize(snapshot)
    db.flush()
    for pos, c in enumerate(terms.components):
        comp = AgreementComponent(
            tenant_id=tid,
            version_id=version.id,
            position=pos,
            component_key=c.key,
            type=c.type.value,
            rate=c.rate,
            amount_per_unit=c.amount_per_unit,
            amount=c.amount,
            threshold=c.threshold,
            growth_pct=c.growth_pct,
            baseline_source=c.baseline_source.value if c.baseline_source else None,
            prior_period_offset=c.prior_period_offset.value if c.prior_period_offset else None,
        )
        db.add(comp)
        db.flush()
        for tpos, t in enumerate(c.tiers):
            db.add(
                AgreementTier(
                    tenant_id=tid,
                    component_id=comp.id,
                    position=tpos,
                    threshold=t.threshold,
                    rate=t.rate,
                    amount_per_unit=t.amount_per_unit,
                )
            )
    for rule in snapshot.eligibility:
        db.add(
            EligibilityRuleRow(
                tenant_id=tid,
                version_id=version.id,
                rule_key=rule.id,
                action=rule.action.value,
                field=rule.field.value,
                values=sorted(rule.values),
                flag=rule.flag,
                min_amount=rule.min_amount,
            )
        )
    db.flush()


def terms_from_rows(db: Session, version: AgreementVersion) -> VersionTermsIn:
    comps = list(
        db.execute(
            select(AgreementComponent)
            .where(AgreementComponent.version_id == version.id)
            .order_by(AgreementComponent.position)
        ).scalars()
    )
    tiers: dict[uuid.UUID, list[AgreementTier]] = {}
    if comps:
        for t in db.execute(
            select(AgreementTier)
            .where(AgreementTier.component_id.in_([c.id for c in comps]))
            .order_by(AgreementTier.position)
        ).scalars():
            tiers.setdefault(t.component_id, []).append(t)
    rules = list(
        db.execute(
            select(EligibilityRuleRow)
            .where(EligibilityRuleRow.version_id == version.id)
            .order_by(EligibilityRuleRow.rule_key)
        ).scalars()
    )
    return VersionTermsIn.model_validate(
        {
            "effective_from": version.effective_from,
            "effective_to": version.effective_to,
            "period_type": version.period_type,
            "fiscal_aligned": version.fiscal_aligned,
            "custom_periods": version.custom_periods,
            "date_basis": version.date_basis,
            "measure": version.measure,
            "spend_basis": version.spend_basis,
            "threshold_comparison": version.threshold_comparison,
            "negative_result": version.negative_result,
            "rounding_mode": version.rounding_mode,
            "payment_terms_days": version.payment_terms_days,
            "stacking": version.stacking,
            "prorate_thresholds_on_partial_period": version.prorate_thresholds_on_partial_period,
            "zero_baseline_policy": version.zero_baseline_policy,
            "cap_amount": _s(version.cap_amount),
            "minimum_payout": _s(version.minimum_payout),
            "eligibility": [
                {
                    "key": r.rule_key,
                    "action": r.action,
                    "field": r.field,
                    "values": r.values,
                    "flag": r.flag,
                    "min_amount": _s(r.min_amount),
                }
                for r in rules
            ],
            "components": [
                {
                    "key": c.component_key,
                    "type": c.type,
                    "rate": _s(c.rate),
                    "amount_per_unit": _s(c.amount_per_unit),
                    "amount": _s(c.amount),
                    "threshold": _s(c.threshold),
                    "growth_pct": _s(c.growth_pct),
                    "baseline_source": c.baseline_source,
                    "prior_period_offset": c.prior_period_offset,
                    "tiers": [
                        {
                            "threshold": _s(t.threshold),
                            "rate": _s(t.rate),
                            "amount_per_unit": _s(t.amount_per_unit),
                        }
                        for t in tiers.get(c.id, [])
                    ],
                }
                for c in comps
            ],
        }
    )


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def snapshot_for(db: Session, version: AgreementVersion, agreement: Agreement) -> VersionSnapshot:
    """Rebuild the engine snapshot from stored rows (fiscal month was frozen at save time)."""
    return to_snapshot(
        terms_from_rows(db, version),
        agreement_id=str(agreement.id),
        version_id=str(version.id),
        version_no=version.version_no,
        supplier_id=str(agreement.supplier_id),
        fiscal_start=version.fiscal_year_start_month,
        name=agreement.name,
        external_reference=agreement.external_reference,
    )


# --------------------------------------------------------------------------- summary

PERIOD_WORD = {
    PeriodType.MONTHLY: "monthly",
    PeriodType.QUARTERLY: "quarterly",
    PeriodType.SEMIANNUAL: "half-yearly",
    PeriodType.ANNUAL: "annual",
    PeriodType.CUSTOM: "per custom period",
}


def _money(d: Decimal) -> str:
    return f"${d.quantize(Decimal('0.01')):,}"


def _pct(d: Decimal) -> str:
    text = format((d * 100).normalize(), "f")
    if "." not in text:
        text += ".00"
    elif len(text.split(".")[1]) < 2:
        text += "0"
    return f"{text}%"


def _measure_amount(v: VersionSnapshot, d: Decimal) -> str:
    return _money(d) if v.measure is Measure.SPEND else f"{format(d.normalize(), ',f')} units"


def summarize(v: VersionSnapshot) -> str:
    """Deterministic English summary of the rules, e.g. "Pays 2.00% on eligible net spend…"."""
    period = PERIOD_WORD[v.period_type]
    measure = "eligible spend" if v.measure is Measure.SPEND else "eligible units"
    cmp = "at least" if v.threshold_comparison is ThresholdComparison.GTE else "more than"
    sentences: list[str] = []
    for c in v.components:
        t = c.type
        if t is ComponentType.FLAT_PERCENT:
            assert c.rate is not None
            sentences.append(f"Pays {_pct(c.rate)} on eligible net spend.")
        elif t is ComponentType.PER_UNIT:
            assert c.amount_per_unit is not None
            sentences.append(f"Pays {_money(c.amount_per_unit)} per eligible net unit.")
        elif t in (ComponentType.TIERED_ALL_UNITS, ComponentType.TIERED_INCREMENTAL):
            parts = []
            for tier in c.tiers:
                pay = (
                    f"{_pct(tier.rate)}"
                    if tier.rate is not None
                    else f"{_money(tier.amount_per_unit or Decimal(0))} per unit"
                )
                parts.append(
                    f"{pay} once {period} {measure} is {cmp} {_measure_amount(v, tier.threshold)}"
                )
            how = (
                "Applies the reached tier to all eligible volume (all-units)."
                if t is ComponentType.TIERED_ALL_UNITS
                else "Each tier's rate applies only to volume within that tier (incremental)."
            )
            sentences.append("Pays " + "; ".join(parts) + ". " + how)
        elif t is ComponentType.GROWTH_INCREMENTAL:
            assert c.rate is not None
            sentences.append(
                f"Pays {_pct(c.rate)} on {measure} above the baseline ({_baseline(c)})."
            )
        elif t is ComponentType.GROWTH_THRESHOLD:
            assert c.rate is not None and c.growth_pct is not None
            sentences.append(
                f"Pays {_pct(c.rate)} on eligible net spend when {period} {measure} grows by {cmp} {_pct(c.growth_pct)} over the baseline ({_baseline(c)})."
            )
        elif t is ComponentType.FIXED_BONUS:
            assert c.amount is not None and c.threshold is not None
            sentences.append(
                f"Pays a {_money(c.amount)} bonus when {period} {measure} is {cmp} {_measure_amount(v, c.threshold)}."
            )
    if len(v.components) > 1:
        sentences.append("Components are added together.")
    for rule in sorted(v.eligibility, key=lambda r: r.id):
        verb = "Excludes" if rule.action is RuleAction.EXCLUDE else "Only includes"
        if rule.field is RuleField.FLAG:
            label = (rule.flag or "").replace("_", " ")
            sentences.append(f"{verb} {label} lines.")
        elif rule.field is RuleField.MIN_LINE_AMOUNT:
            assert rule.min_amount is not None
            sentences.append(
                f"Only counts lines of at least {_money(rule.min_amount)} (absolute amount)."
            )
        else:
            values = ", ".join(sorted(rule.values)[:5]) + (
                f" and {len(rule.values) - 5} more" if len(rule.values) > 5 else ""
            )
            sentences.append(f"{verb} {rule.field.value}s: {values}.")
    if v.spend_basis is SpendBasis.GROSS:
        sentences.append("Returns do not reduce the measure used for tiers.")
    if v.cap_amount is not None:
        sentences.append(f"Capped at {_money(v.cap_amount)} per period.")
    if v.minimum_payout is not None:
        sentences.append(f"Pays nothing if the result is below {_money(v.minimum_payout)}.")
    if v.negative_result is NegativeResult.ALLOW_CLAWBACK:
        sentences.append("A negative result is owed back to the supplier (clawback).")
    basis = v.date_basis.value.replace("_", " ")
    sentences.append(
        f"Measured {period} by {basis}; credits are due within {v.payment_terms_days} days after each period ends."
    )
    return " ".join(sentences)


def _baseline(c: Component) -> str:
    if c.baseline_source is BaselineSource.IMPORTED:
        return "imported baseline"
    if c.prior_period_offset is PriorPeriodOffset.SAME_PERIOD_PRIOR_YEAR:
        return "same period last year"
    return "previous period"
