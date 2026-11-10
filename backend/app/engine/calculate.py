"""The rebate calculation for one agreement-period (SPEC §4.4.2 order of operations).

Steps (implemented exactly, each recorded in the trace):
 1. Select lines whose basis date falls in the measurement period.
 2. Apply eligibility filters; record exclusions with reason codes.
 3. Compute S, Q, M at full precision (returns handled per spend_basis).
 4. Compute each component at full precision.
 5. Sum components.
 6. Apply negative_result policy.
 7. Apply cap_amount.
 8. Apply minimum_payout.
 9. Round once to 2 dp with the agreement's rounding mode.
10. Emit the result with the trace.

``spend_basis`` affects only M (the measure tiers are tested against). S and Q
are always net of returns, per their SPEC §3 definitions (ADR 0010).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

from app.engine import eligibility
from app.engine.canonical import sha256_hex
from app.engine.models import (
    Baseline,
    BaselineSource,
    CalcOptions,
    Component,
    ComponentType,
    EngineInputError,
    ExclusionReason,
    Measure,
    NegativeResult,
    Period,
    PurchaseLine,
    ReviewReason,
    RoundingMode,
    SpendBasis,
    Status,
    ThresholdComparison,
    VersionResolution,
    VersionSnapshot,
    ZeroBaselinePolicy,
)
from app.engine.periods import prior_period
from app.engine.version import ENGINE_VERSION

ZERO = Decimal(0)
ONE = Decimal(1)
CENT = Decimal("0.01")


def engine_context() -> Context:
    """A fresh local context: 60 significant digits, every dangerous signal trapped."""
    return Context(
        prec=60,
        rounding=ROUND_HALF_EVEN,
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def _fmt(d: Decimal | None) -> str:
    if d is None:
        return "n/a"
    return str(d)


# --------------------------------------------------------------------------- result types


@dataclass(frozen=True, slots=True)
class TraceStep:
    step: int
    name: str
    description: str
    values: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "name": self.name,
            "description": self.description,
            "values": dict(self.values),
        }


@dataclass(frozen=True, slots=True)
class Reason:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ComponentResult:
    component_id: str
    type: ComponentType
    value: Decimal | None
    formula: str
    tier_reached: int | None = None
    """1-based tier index reached, None if not tiered or no tier met."""
    baseline: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PeriodResult:
    agreement_id: str
    version_id: str
    version_no: int
    supplier_id: str
    period: Period
    full_period: Period
    expected: Decimal | None
    expected_unrounded: Decimal | None
    spend: Decimal
    quantity: Decimal
    measure: Decimal
    components: tuple[ComponentResult, ...]
    eligible_count: int
    excluded_counts: tuple[tuple[str, int], ...]
    statuses: tuple[Status, ...]
    reasons: tuple[Reason, ...]
    trace: tuple[TraceStep, ...]
    engine_version: str
    input_hash: str
    eligible_line_ids: tuple[str, ...]
    payment_terms_days: int

    @property
    def needs_review(self) -> bool:
        return Status.NEEDS_REVIEW in self.statuses

    @property
    def tier_reached(self) -> int | None:
        tiers = [c.tier_reached for c in self.components if c.tier_reached is not None]
        return max(tiers) if tiers else None


# --------------------------------------------------------------------------- selection


@dataclass(frozen=True, slots=True)
class Selection:
    eligible: tuple[PurchaseLine, ...]
    excluded: dict[ExclusionReason, int]
    excluded_by_rule: dict[str, int]
    considered: tuple[PurchaseLine, ...]
    """Lines that entered step 1 (in period or missing the basis date); part of input_hash."""


def select_lines(
    version: VersionSnapshot, window: Period, lines: Iterable[PurchaseLine]
) -> Selection:
    """Steps 1 and 2. Output is sorted by line_id so it is independent of input order."""
    eligible: list[PurchaseLine] = []
    considered: list[PurchaseLine] = []
    excluded: dict[ExclusionReason, int] = {}
    by_rule: dict[str, int] = {}
    for line in lines:
        if line.supplier_id != version.supplier_id:
            continue
        basis = line.basis_date(version.date_basis)
        if basis is None:
            considered.append(line)
            excluded[ExclusionReason.DATE_BASIS_MISSING] = (
                excluded.get(ExclusionReason.DATE_BASIS_MISSING, 0) + 1
            )
            continue
        if not window.contains(basis):
            continue
        considered.append(line)
        decision = eligibility.evaluate(line, version.eligibility)
        if decision.eligible:
            eligible.append(line)
        else:
            assert decision.reason is not None
            assert decision.rule_id is not None
            excluded[decision.reason] = excluded.get(decision.reason, 0) + 1
            by_rule[decision.rule_id] = by_rule.get(decision.rule_id, 0) + 1
    key = _line_sort_key
    return Selection(
        tuple(sorted(eligible, key=key)),
        excluded,
        by_rule,
        tuple(sorted(considered, key=key)),
    )


def _line_sort_key(line: PurchaseLine) -> tuple[str, str]:
    return (line.line_id, sha256_hex(line))


@dataclass(frozen=True, slots=True)
class Measures:
    spend: Decimal
    quantity: Decimal
    measure: Decimal
    returns_excluded_from_measure: int


def compute_measures(version: VersionSnapshot, eligible: Sequence[PurchaseLine]) -> Measures:
    """Step 3. Summation happens over line_id-sorted input, but Decimal addition at
    60 digits is exact for NUMERIC(18,4) inputs, so order cannot change the result."""
    spend = sum((ln.amount for ln in eligible), ZERO)
    quantity = sum((ln.quantity for ln in eligible), ZERO)
    if version.measure is Measure.SPEND:
        values = [ln.amount for ln in eligible]
    else:
        values = [ln.quantity for ln in eligible]
    if version.spend_basis is SpendBasis.GROSS:
        kept = [v for v in values if v > 0]
        measure = sum(kept, ZERO)
        dropped = len(values) - len(kept)
    else:
        measure = sum(values, ZERO)
        dropped = 0
    return Measures(spend, quantity, measure, dropped)


# --------------------------------------------------------------------------- components


def _meets(m: Decimal, threshold: Decimal, cmp: ThresholdComparison) -> bool:
    return m >= threshold if cmp is ThresholdComparison.GTE else m > threshold


def _cmp_symbol(cmp: ThresholdComparison) -> str:
    return "≥" if cmp is ThresholdComparison.GTE else ">"


@dataclass(frozen=True, slots=True)
class _Ctx:
    version: VersionSnapshot
    s: Decimal
    q: Decimal
    m: Decimal
    factor: Decimal
    """Threshold proration factor (1 unless prorating a partial period)."""


@dataclass(frozen=True, slots=True)
class _BaselineOutcome:
    value: Decimal | None
    reason: ReviewReason | None = None
    message: str = ""
    description: str = ""


def _component_value(
    c: Component, ctx: _Ctx, baseline: _BaselineOutcome | None
) -> tuple[ComponentResult, Reason | None]:
    v = ctx.version
    cmp = v.threshold_comparison
    sym = _cmp_symbol(cmp)
    t = c.type
    if t is ComponentType.FLAT_PERCENT:
        assert c.rate is not None
        val = c.rate * ctx.s
        return ComponentResult(c.id, t, val, f"rate × S = {c.rate} × {ctx.s} = {val}"), None
    if t is ComponentType.PER_UNIT:
        assert c.amount_per_unit is not None
        val = c.amount_per_unit * ctx.q
        formula = f"amount_per_unit × Q = {c.amount_per_unit} × {ctx.q} = {val}"
        return ComponentResult(c.id, t, val, formula), None
    if t is ComponentType.TIERED_ALL_UNITS:
        reached: int | None = None
        for i, tier in enumerate(c.tiers):
            if _meets(ctx.m, tier.threshold * ctx.factor, cmp):
                reached = i
        if reached is None:
            first = c.tiers[0].threshold * ctx.factor
            formula = f"no tier met: M = {ctx.m} is not {sym} lowest threshold {first}; value = 0"
            return ComponentResult(c.id, t, ZERO, formula, None), None
        tier = c.tiers[reached]
        thr = tier.threshold * ctx.factor
        if tier.rate is not None:
            val = tier.rate * ctx.s
            pay = f"tier rate × S = {tier.rate} × {ctx.s} = {val}"
        else:
            assert tier.amount_per_unit is not None
            val = tier.amount_per_unit * ctx.q
            pay = f"tier amount_per_unit × Q = {tier.amount_per_unit} × {ctx.q} = {val}"
        formula = f"tier {reached + 1} reached (M = {ctx.m} {sym} {thr}); all-units: {pay}"
        return ComponentResult(c.id, t, val, formula, reached + 1), None
    if t is ComponentType.TIERED_INCREMENTAL:
        total = ZERO
        parts: list[str] = []
        reached = None
        for i, tier in enumerate(c.tiers):
            lo = tier.threshold * ctx.factor
            hi = c.tiers[i + 1].threshold * ctx.factor if i + 1 < len(c.tiers) else None
            top = ctx.m if hi is None else min(ctx.m, hi)
            portion = max(ZERO, top - lo)
            unit = tier.rate if tier.rate is not None else tier.amount_per_unit
            assert unit is not None
            amount = unit * portion
            total += amount
            if _meets(ctx.m, lo, cmp):
                reached = i
            band = f"[{lo}, {hi if hi is not None else '∞'})"
            parts.append(f"tier {i + 1} {band}: {unit} × {portion} = {amount}")
        formula = "incremental: " + "; ".join(parts) + f"; total = {total}"
        return ComponentResult(c.id, t, total, formula, None if reached is None else reached + 1), (
            None
        )
    if t is ComponentType.FIXED_BONUS:
        assert c.amount is not None
        assert c.threshold is not None
        thr = c.threshold * ctx.factor
        if _meets(ctx.m, thr, cmp):
            return ComponentResult(
                c.id, t, c.amount, f"M = {ctx.m} {sym} {thr}: pays {c.amount}"
            ), (None)
        return ComponentResult(c.id, t, ZERO, f"M = {ctx.m} not {sym} {thr}: pays 0"), None

    # Growth components.
    assert baseline is not None
    assert c.rate is not None
    if baseline.reason is not None:
        res = ComponentResult(c.id, t, None, f"cannot compute: {baseline.message}")
        return res, Reason(baseline.reason.value, f"{c.id}: {baseline.message}")
    b = baseline.value
    assert b is not None
    if b < 0:
        msg = f"baseline {b} is negative; confirm the baseline before calculating"
        res = ComponentResult(c.id, t, None, f"cannot compute: {msg}", baseline=b)
        return res, Reason(ReviewReason.BASELINE_NEGATIVE.value, f"{c.id}: {msg}")
    if b == 0:
        policy = v.zero_baseline_policy
        if policy is ZeroBaselinePolicy.NEEDS_REVIEW:
            msg = "baseline is zero and zero_baseline_policy is needs_review"
            res = ComponentResult(c.id, t, None, f"cannot compute: {msg}", baseline=b)
            return res, Reason(ReviewReason.BASELINE_ZERO.value, f"{c.id}: {msg}")
        if policy is ZeroBaselinePolicy.DOES_NOT_QUALIFY:
            formula = "baseline is zero; zero_baseline_policy = does_not_qualify: pays 0"
            return ComponentResult(c.id, t, ZERO, formula, baseline=b), None
        # QUALIFIES falls through to the normal formula.
    if t is ComponentType.GROWTH_INCREMENTAL:
        growth = max(ZERO, ctx.m - b)
        val = c.rate * growth
        formula = f"rate × max(0, M − B) = {c.rate} × max(0, {ctx.m} − {b}) = {val}"
        return ComponentResult(c.id, t, val, formula, baseline=b), None
    # GROWTH_THRESHOLD
    assert c.growth_pct is not None
    if b == 0:
        val = c.rate * ctx.s
        formula = (
            "baseline is zero; zero_baseline_policy = qualifies: "
            f"rate × S = {c.rate} × {ctx.s} = {val}"
        )
        return ComponentResult(c.id, t, val, formula, baseline=b), None
    # (M ÷ B − 1) ⋛ g  ⇔  M ⋛ B × (1 + g) for B > 0: compared exactly, no division.
    target = b * (ONE + c.growth_pct)
    growth_ratio = ctx.m / b - ONE
    if _meets(ctx.m, target, cmp):
        val = c.rate * ctx.s
        formula = (
            f"growth = M ÷ B − 1 = {ctx.m} ÷ {b} − 1 = {growth_ratio} {sym} {c.growth_pct} "
            f"(M {sym} B × (1 + g) = {target}): rate × S = {c.rate} × {ctx.s} = {val}"
        )
        return ComponentResult(c.id, t, val, formula, baseline=b), None
    formula = (
        f"growth = M ÷ B − 1 = {ctx.m} ÷ {b} − 1 = {growth_ratio} not {sym} {c.growth_pct}: pays 0"
    )
    return ComponentResult(c.id, t, ZERO, formula, baseline=b), None


def _resolve_baseline(
    c: Component,
    version: VersionSnapshot,
    full: Period,
    lines: Sequence[PurchaseLine],
    baselines: Sequence[Baseline],
    options: CalcOptions,
) -> tuple[_BaselineOutcome, tuple[PurchaseLine, ...], tuple[Baseline, ...]]:
    """Returns the outcome plus the inputs it used (for input_hash)."""
    if c.baseline_source is BaselineSource.IMPORTED:
        found = tuple(
            sorted(
                (
                    b
                    for b in baselines
                    if b.agreement_id == version.agreement_id
                    and b.period_start == full.start
                    and b.period_end == full.end
                ),
                key=lambda b: (b.baseline_id, str(b.value)),
            )
        )
        if not found:
            msg = f"no imported baseline for {full.start}..{full.end}"
            return _BaselineOutcome(None, ReviewReason.BASELINE_MISSING, msg), (), ()
        if len({b.value for b in found}) > 1:
            msg = f"{len(found)} different imported baselines for {full.start}..{full.end}"
            return _BaselineOutcome(None, ReviewReason.BASELINE_AMBIGUOUS, msg), (), found
        desc = f"imported baseline for {full.start}..{full.end} = {found[0].value}"
        return _BaselineOutcome(found[0].value, description=desc), (), found

    assert c.prior_period_offset is not None
    prior = prior_period(
        full,
        c.prior_period_offset,
        version.period_type,
        version.fiscal_year_start_month,
        version.custom_periods,
    )
    if prior is None:
        msg = "no earlier custom period exists to compute the baseline from"
        return _BaselineOutcome(None, ReviewReason.BASELINE_MISSING, msg), (), ()
    coverage = options.data_coverage_start
    if coverage is None or prior.start < coverage:
        have = "unknown" if coverage is None else str(coverage)
        msg = (
            f"baseline period {prior.start}..{prior.end} starts before purchase data "
            f"coverage ({have}); import that period's purchases"
        )
        return _BaselineOutcome(None, ReviewReason.BASELINE_MISSING, msg), (), ()
    sel = select_lines(version, prior, lines)
    measures = compute_measures(version, sel.eligible)
    desc = (
        f"computed baseline over {prior.start}..{prior.end} with this version's eligibility: "
        f"M = {measures.measure} from {len(sel.eligible)} eligible lines"
    )
    return _BaselineOutcome(measures.measure, description=desc), sel.considered, ()


# --------------------------------------------------------------------------- entry point


def calculate(
    version: VersionSnapshot,
    period: Period,
    lines: Sequence[PurchaseLine],
    baselines: Sequence[Baseline] = (),
    options: CalcOptions | None = None,
) -> PeriodResult:
    """Calculate the expected rebate for one agreement-period.

    ``period`` is the measurement window. When it is a clipped or split part of a
    longer period, ``options.full_period`` carries the whole period.
    """
    opts = options or CalcOptions()
    with localcontext(engine_context()):
        return _calculate(version, period, lines, baselines, opts)


def _calculate(
    version: VersionSnapshot,
    window: Period,
    lines: Sequence[PurchaseLine],
    baselines: Sequence[Baseline],
    opts: CalcOptions,
) -> PeriodResult:
    full = opts.full_period or window
    if window.start < full.start or window.end > full.end:
        raise EngineInputError("measurement period must lie inside the full period")
    eff = version.effective_period
    may_span_versions = opts.review_reason is not None or opts.version_resolution in (
        VersionResolution.APPLY_OLD,
        VersionResolution.APPLY_NEW,
    )
    if not may_span_versions and (window.start < eff.start or window.end > eff.end):
        raise EngineInputError(
            "measurement period extends outside the version's effective range; "
            "clip it or pass a version resolution"
        )

    trace: list[TraceStep] = []
    reasons: list[Reason] = []
    statuses: set[Status] = set()
    partial = window.start != full.start or window.end != full.end
    if partial:
        statuses.add(Status.PARTIAL_PERIOD)

    if opts.review_reason is not None:
        reasons.append(Reason(opts.review_reason.value, opts.review_message))
    for conflict in opts.stacking_conflicts:
        shown = ", ".join(conflict.line_ids[:20])
        more = len(conflict.line_ids) - 20
        suffix = f" and {more} more" if more > 0 else ""
        reasons.append(
            Reason(
                ReviewReason.STACKING_CONFLICT.value,
                f"{len(conflict.line_ids)} line(s) are also eligible for exclusive-stacking "
                f"agreement {conflict.other_agreement_id}: {shown}{suffix}",
            )
        )

    # Step 1 + 2
    sel = select_lines(version, window, lines)
    note = ""
    if opts.version_resolution is not None:
        note = f" Version boundary resolved by user: {opts.version_resolution.value}."
    trace.append(
        TraceStep(
            1,
            "select_lines",
            f"Lines of supplier {version.supplier_id} whose {version.date_basis.value} falls in "
            f"{window.start}..{window.end}.{note}",
            (
                ("full_period", f"{full.start}..{full.end}"),
                ("measurement_period", f"{window.start}..{window.end}"),
                ("partial_period", str(partial).lower()),
                ("lines_considered", str(len(sel.considered))),
            ),
        )
    )
    excluded_sorted = tuple(sorted((r.value, n) for r, n in sel.excluded.items()))
    trace.append(
        TraceStep(
            2,
            "eligibility",
            "Exclude rules win over include rules; lines missing a filtered attribute are "
            "excluded as ATTRIBUTE_MISSING.",
            (
                ("eligible_lines", str(len(sel.eligible))),
                *((f"excluded:{r}", str(n)) for r, n in excluded_sorted),
                *(
                    (f"excluded_by_rule:{k}", str(v))
                    for k, v in sorted(sel.excluded_by_rule.items())
                ),
            ),
        )
    )

    # Step 3
    meas = compute_measures(version, sel.eligible)
    trace.append(
        TraceStep(
            3,
            "measures",
            f"S = net eligible spend, Q = net eligible quantity, M = {version.measure.value} "
            f"measure on a {version.spend_basis.value} basis.",
            (
                ("S", str(meas.spend)),
                ("Q", str(meas.quantity)),
                ("M", str(meas.measure)),
                ("returns_excluded_from_M", str(meas.returns_excluded_from_measure)),
            ),
        )
    )

    factor = ONE
    if partial and version.prorate_thresholds_on_partial_period:
        factor = Decimal(window.days) / Decimal(full.days)
    ctx = _Ctx(version, meas.spend, meas.quantity, meas.measure, factor)

    # Step 4
    comp_results: list[ComponentResult] = []
    hashed_prior_lines: list[PurchaseLine] = []
    hashed_baselines: list[Baseline] = []
    for comp in version.components:
        baseline: _BaselineOutcome | None = None
        if comp.is_growth:
            if partial:
                msg = (
                    f"{comp.id}: growth component in a partial period; the baseline covers a "
                    "different length of time. Decide how to compare before calculating."
                )
                reasons.append(Reason(ReviewReason.GROWTH_PARTIAL_PERIOD.value, msg))
            baseline, used_lines, used_baselines = _resolve_baseline(
                comp, version, full, lines, baselines, opts
            )
            hashed_prior_lines.extend(used_lines)
            hashed_baselines.extend(used_baselines)
        result, reason = _component_value(comp, ctx, baseline)
        comp_results.append(result)
        if reason is not None:
            reasons.append(reason)
        values: list[tuple[str, str]] = [("type", comp.type.value), ("value", _fmt(result.value))]
        if baseline is not None and baseline.description:
            values.append(("baseline", baseline.description))
        if factor != ONE:
            values.append(("threshold_proration_factor", f"{window.days}/{full.days} = {factor}"))
        trace.append(TraceStep(4, f"component:{comp.id}", result.formula, tuple(values)))

    needs_review = bool(reasons)
    expected_unrounded: Decimal | None = None
    expected: Decimal | None = None

    if needs_review:
        statuses.add(Status.NEEDS_REVIEW)
        trace.append(
            TraceStep(
                5,
                "needs_review",
                "Calculation stopped: a decision is needed before an expected amount can be "
                "stated. Steps 5–9 were not applied.",
                tuple((r.code, r.message) for r in reasons),
            )
        )
    else:
        # Step 5
        total = sum((r.value for r in comp_results if r.value is not None), ZERO)
        trace.append(
            TraceStep(
                5,
                "sum_components",
                " + ".join(_fmt(r.value) for r in comp_results) + f" = {total}",
                (("sum", str(total)),),
            )
        )
        # Step 6
        after_negative = total
        if total < 0 and version.negative_result is NegativeResult.FLOOR_AT_ZERO:
            after_negative = ZERO
        trace.append(
            TraceStep(
                6,
                "negative_result",
                f"policy {version.negative_result.value}: {total} → {after_negative}",
                (("value", str(after_negative)),),
            )
        )
        # Step 7
        after_cap = after_negative
        if version.cap_amount is not None and after_negative > version.cap_amount:
            after_cap = version.cap_amount
            statuses.add(Status.CAPPED)
        trace.append(
            TraceStep(
                7,
                "cap",
                f"cap {_fmt(version.cap_amount)}: {after_negative} → {after_cap}",
                (("value", str(after_cap)),),
            )
        )
        # Step 8
        after_min = after_cap
        if version.minimum_payout is not None and after_cap < 0:
            reasons.append(
                Reason(
                    ReviewReason.CLAWBACK_WITH_MINIMUM.value,
                    f"result {after_cap} is a clawback and a minimum payout of "
                    f"{version.minimum_payout} is set; the spec does not say whether the "
                    "minimum applies to clawbacks",
                )
            )
            statuses.add(Status.NEEDS_REVIEW)
            needs_review = True
        elif version.minimum_payout is not None and 0 < after_cap < version.minimum_payout:
            after_min = ZERO
            statuses.add(Status.BELOW_MINIMUM)
        trace.append(
            TraceStep(
                8,
                "minimum_payout",
                f"minimum {_fmt(version.minimum_payout)}: {after_cap} → {after_min}",
                (("value", str(after_min)),),
            )
        )
        if not needs_review:
            # Step 9
            rounding = (
                ROUND_HALF_UP if version.rounding_mode is RoundingMode.HALF_UP else ROUND_HALF_EVEN
            )
            expected_unrounded = after_min
            expected = after_min.quantize(CENT, rounding=rounding)
            if expected == 0:
                expected = Decimal("0.00")  # never emit "-0.00"
            trace.append(
                TraceStep(
                    9,
                    "round",
                    f"round {after_min} to 2 dp ({version.rounding_mode.value}) = {expected}",
                    (("unrounded", str(after_min)), ("expected", str(expected))),
                )
            )
            if expected_unrounded == 0 and Status.BELOW_MINIMUM not in statuses:
                statuses.add(Status.NOT_EARNED)
            if not statuses & {Status.BELOW_MINIMUM, Status.NOT_EARNED}:
                statuses.add(Status.OK)

    input_hash = sha256_hex(
        {
            "version": version,
            "period": window,
            "full_period": full,
            "lines": list(sel.considered),
            "prior_lines": sorted(hashed_prior_lines, key=_line_sort_key),
            "baselines": hashed_baselines,
            "options": {
                "data_coverage_start": opts.data_coverage_start,
                "stacking_conflicts": sorted(
                    opts.stacking_conflicts, key=lambda c: c.other_agreement_id
                ),
                "review_reason": opts.review_reason,
                "version_resolution": opts.version_resolution,
            },
        }
    )
    trace.append(
        TraceStep(
            10,
            "emit",
            "Result emitted. Recompute by following steps 1–9 with the listed values.",
            (("engine_version", ENGINE_VERSION), ("input_hash", input_hash)),
        )
    )

    return PeriodResult(
        agreement_id=version.agreement_id,
        version_id=version.version_id,
        version_no=version.version_no,
        supplier_id=version.supplier_id,
        period=window,
        full_period=full,
        expected=expected if not needs_review else None,
        expected_unrounded=expected_unrounded if not needs_review else None,
        spend=meas.spend,
        quantity=meas.quantity,
        measure=meas.measure,
        components=tuple(comp_results),
        eligible_count=len(sel.eligible),
        excluded_counts=excluded_sorted,
        statuses=tuple(sorted(statuses)),
        reasons=tuple(reasons),
        trace=tuple(trace),
        engine_version=ENGINE_VERSION,
        input_hash=input_hash,
        eligible_line_ids=tuple(ln.line_id for ln in sel.eligible),
        payment_terms_days=version.payment_terms_days,
    )


def due_date(result: PeriodResult) -> date:
    """Credits are expected within payment_terms_days after the measured period ends.

    For a split or clipped period this is the end of the measured window, matching
    ``reconcile.reconcile_item``.
    """
    return result.period.end + timedelta(days=result.payment_terms_days)
