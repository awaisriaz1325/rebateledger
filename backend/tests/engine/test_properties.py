"""Property-based tests required by SPEC §11."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.engine.calculate import calculate
from app.engine.models import (
    CalcOptions,
    Component,
    ComponentType,
    DateBasis,
    EligibilityRule,
    Measure,
    NegativeResult,
    Period,
    PeriodType,
    PurchaseLine,
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

Q1 = Period(date(2026, 1, 1), date(2026, 3, 31))
SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])

money = st.decimals(
    min_value=Decimal("-50000"), max_value=Decimal("200000"), places=2, allow_nan=False
)
positive_money = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("200000"), places=2, allow_nan=False
)
qty = st.decimals(min_value=Decimal("-100"), max_value=Decimal("1000"), places=2, allow_nan=False)
rates = st.decimals(min_value=Decimal("0"), max_value=Decimal("0.1"), places=4, allow_nan=False)
day = st.integers(min_value=0, max_value=89)


def version(
    components: tuple[Component, ...],
    *,
    cap: Decimal | None = None,
    measure: Measure = Measure.SPEND,
    rules: tuple[EligibilityRule, ...] = (),
    negative: NegativeResult = NegativeResult.FLOOR_AT_ZERO,
) -> VersionSnapshot:
    return VersionSnapshot(
        agreement_id="A1",
        version_id="A1-v1",
        version_no=1,
        supplier_id="S1",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        period_type=PeriodType.QUARTERLY,
        fiscal_year_start_month=1,
        date_basis=DateBasis.INVOICE_DATE,
        measure=measure,
        spend_basis=SpendBasis.NET_OF_RETURNS,
        threshold_comparison=ThresholdComparison.GTE,
        components=components,
        negative_result=negative,
        rounding_mode=RoundingMode.HALF_UP,
        payment_terms_days=30,
        stacking=Stacking.STACKABLE,
        prorate_thresholds_on_partial_period=False,
        zero_baseline_policy=ZeroBaselinePolicy.NEEDS_REVIEW,
        eligibility=rules,
        cap_amount=cap,
    )


@st.composite
def lines_strategy(
    draw: st.DrawFn, min_size: int = 0, positive: bool = False
) -> list[PurchaseLine]:
    n = draw(st.integers(min_value=min_size, max_value=25))
    out = []
    for i in range(n):
        out.append(
            PurchaseLine(
                line_id=f"L{i:03d}",
                supplier_id="S1",
                quantity=draw(
                    qty
                    if not positive
                    else st.decimals(min_value=Decimal("0.01"), max_value=Decimal("1000"), places=2)
                ),
                amount=draw(positive_money if positive else money),
                sku=draw(st.sampled_from(["A", "B", "C"])),
                invoice_date=date(2026, 1, 1) + timedelta(days=draw(day)),
                flags=PurchaseLine.make_flags({"promo": draw(st.booleans())}),
            )
        )
    return out


@st.composite
def ascending_tiers(draw: st.DrawFn, non_decreasing_rates: bool = False) -> tuple[Tier, ...]:
    n = draw(st.integers(min_value=1, max_value=4))
    thresholds = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=500000), min_size=n, max_size=n, unique=True
            )
        )
    )
    rs = draw(st.lists(rates, min_size=n, max_size=n))
    if non_decreasing_rates:
        rs = sorted(rs)
    return tuple(Tier(Decimal(t), rate=r) for t, r in zip(thresholds, rs, strict=True))


component_strategy = st.one_of(
    rates.map(lambda r: Component("c", ComponentType.FLAT_PERCENT, rate=r)),
    rates.map(lambda r: Component("c", ComponentType.PER_UNIT, amount_per_unit=r)),
    ascending_tiers().map(lambda t: Component("c", ComponentType.TIERED_ALL_UNITS, tiers=t)),
    ascending_tiers().map(lambda t: Component("c", ComponentType.TIERED_INCREMENTAL, tiers=t)),
    st.tuples(positive_money, st.integers(0, 300000)).map(
        lambda a: Component("c", ComponentType.FIXED_BONUS, amount=a[0], threshold=Decimal(a[1]))
    ),
)


@SETTINGS
@given(component_strategy, lines_strategy(), st.randoms(use_true_random=False))
def test_order_invariance(comp: Component, lines: list[PurchaseLine], rnd: random.Random) -> None:
    v = version((comp,))
    shuffled = list(lines)
    rnd.shuffle(shuffled)
    a = calculate(v, Q1, lines)
    b = calculate(v, Q1, shuffled)
    assert a == b
    assert a.input_hash == b.input_hash


@SETTINGS
@given(component_strategy, lines_strategy(min_size=1), st.data())
def test_line_split_invariance(
    comp: Component, lines: list[PurchaseLine], data: st.DataObject
) -> None:
    """Splitting one line into two with the same attributes cannot change the result."""
    v = version((comp,))
    idx = data.draw(st.integers(0, len(lines) - 1))
    target = lines[idx]
    part = (target.amount / 3).quantize(Decimal("0.01"))
    qpart = (target.quantity / 3).quantize(Decimal("0.01"))
    a_line = replace(target, line_id=target.line_id + "a", amount=part, quantity=qpart)
    b_line = replace(
        target,
        line_id=target.line_id + "b",
        amount=target.amount - part,
        quantity=target.quantity - qpart,
    )
    split = [*lines[:idx], a_line, b_line, *lines[idx + 1 :]]
    before = calculate(v, Q1, lines)
    after = calculate(v, Q1, split)
    assert before.expected == after.expected
    assert (before.spend, before.quantity, before.measure) == (
        after.spend,
        after.quantity,
        after.measure,
    )


@SETTINGS
@given(component_strategy, lines_strategy(), lines_strategy())
def test_ineligible_line_invariance(
    comp: Component, lines: list[PurchaseLine], noise: list[PurchaseLine]
) -> None:
    """Lines of other suppliers, outside the period, or excluded by a rule change nothing."""
    rules = (EligibilityRule("x", RuleAction.EXCLUDE, RuleField.SKU, frozenset({"Z"})),)
    v = version((comp,), rules=rules)
    extra: list[PurchaseLine] = []
    for i, ln in enumerate(noise):
        kind = i % 3
        if kind == 0:
            extra.append(replace(ln, line_id=f"N{i}", supplier_id="OTHER"))
        elif kind == 1:
            extra.append(replace(ln, line_id=f"N{i}", invoice_date=date(2026, 4, 1)))
        else:
            extra.append(replace(ln, line_id=f"N{i}", sku="Z"))
    base = calculate(v, Q1, lines)
    noisy = calculate(v, Q1, [*lines, *extra])
    assert base.expected == noisy.expected
    assert base.measure == noisy.measure


@SETTINGS
@given(component_strategy, lines_strategy(), st.decimals(min_value=0, max_value=5000, places=2))
def test_cap_respected(comp: Component, lines: list[PurchaseLine], cap: Decimal) -> None:
    result = calculate(version((comp,), cap=cap), Q1, lines)
    assert result.expected is not None
    assert result.expected <= cap


@SETTINGS
@given(ascending_tiers(non_decreasing_rates=True), lines_strategy(positive=True), positive_money)
def test_monotonic_in_measure(
    tiers: tuple[Tier, ...], lines: list[PurchaseLine], extra: Decimal
) -> None:
    """With non-decreasing tier rates, more eligible spend never lowers the expected rebate."""
    for ctype in (ComponentType.TIERED_ALL_UNITS, ComponentType.TIERED_INCREMENTAL):
        v = version((Component("c", ctype, tiers=tiers),))
        more = [*lines, PurchaseLine("ZZZ", "S1", Decimal(1), extra, invoice_date=date(2026, 2, 1))]
        a = calculate(v, Q1, lines)
        b = calculate(v, Q1, more)
        assert a.expected is not None and b.expected is not None
        assert b.expected >= a.expected


@SETTINGS
@given(ascending_tiers(non_decreasing_rates=True), lines_strategy(positive=True))
def test_incremental_not_above_all_units(
    tiers: tuple[Tier, ...], lines: list[PurchaseLine]
) -> None:
    inc = calculate(
        version((Component("c", ComponentType.TIERED_INCREMENTAL, tiers=tiers),)), Q1, lines
    )
    allu = calculate(
        version((Component("c", ComponentType.TIERED_ALL_UNITS, tiers=tiers),)), Q1, lines
    )
    assert inc.expected_unrounded is not None and allu.expected_unrounded is not None
    assert inc.expected_unrounded <= allu.expected_unrounded


@SETTINGS
@given(component_strategy, lines_strategy())
def test_rounded_once_from_unrounded(comp: Component, lines: list[PurchaseLine]) -> None:
    r = calculate(version((comp,), negative=NegativeResult.ALLOW_CLAWBACK), Q1, lines)
    assert r.expected is not None and r.expected_unrounded is not None
    assert abs(r.expected - r.expected_unrounded) <= Decimal("0.005")
    assert r.expected.as_tuple().exponent == -2


def test_options_are_part_of_hash() -> None:
    v = version((Component("c", ComponentType.FLAT_PERCENT, rate=Decimal("0.01")),))
    a = calculate(v, Q1, [])
    b = calculate(v, Q1, [], options=CalcOptions(data_coverage_start=date(2020, 1, 1)))
    assert a.input_hash != b.input_hash


# --------------------------------------------------------------------------- buying groups (1.1.0)


def _as_group(v: VersionSnapshot, members: frozenset[str]) -> VersionSnapshot:
    return replace(v, supplier_id="G1", member_supplier_ids=members)


@SETTINGS
@given(component_strategy, lines_strategy())
def test_one_member_group_equals_the_supplier_agreement(
    comp: Component, lines: list[PurchaseLine]
) -> None:
    """A group whose only member is S1 pays exactly what an S1 agreement pays."""
    v = version((comp,))
    a = calculate(v, Q1, lines)
    g = calculate(_as_group(v, frozenset({"S1"})), Q1, lines)
    assert (g.expected, g.expected_unrounded, g.measure, g.statuses, g.eligible_count) == (
        a.expected,
        a.expected_unrounded,
        a.measure,
        a.statuses,
        a.eligible_count,
    )


@SETTINGS
@given(component_strategy, lines_strategy(), lines_strategy(), st.randoms(use_true_random=False))
def test_group_reads_all_members_in_any_order(
    comp: Component, s1: list[PurchaseLine], s2: list[PurchaseLine], rnd: random.Random
) -> None:
    """Group over S1+S2 = the same lines all re-labelled S1; independent of line order."""
    s2 = [replace(ln, line_id=f"M{ln.line_id}", supplier_id="S2") for ln in s2]
    outsider = [replace(ln, line_id=f"X{ln.line_id}", supplier_id="S9") for ln in s1]
    v = version((comp,))
    group = _as_group(v, frozenset({"S1", "S2"}))
    mixed = s1 + s2 + outsider
    rnd.shuffle(mixed)
    g = calculate(group, Q1, mixed)
    merged = calculate(v, Q1, s1 + [replace(ln, supplier_id="S1") for ln in s2])
    assert (g.expected, g.measure, g.eligible_count) == (
        merged.expected,
        merged.measure,
        merged.eligible_count,
    )
    assert calculate(group, Q1, list(reversed(mixed))).input_hash == g.input_hash


def test_empty_member_set_is_not_part_of_the_hash_but_members_are() -> None:
    from app.engine.canonical import to_canonical

    v = version((Component("c", ComponentType.FLAT_PERCENT, rate=Decimal("0.02")),))
    assert "member_supplier_ids" not in to_canonical(v)  # type: ignore[operator]
    g = _as_group(v, frozenset({"S2", "S1"}))
    assert to_canonical(g)["member_supplier_ids"] == ["S1", "S2"]  # type: ignore[index]


def test_group_cannot_be_its_own_member() -> None:
    import pytest

    from app.engine.models import EngineInputError

    v = version((Component("c", ComponentType.FLAT_PERCENT, rate=Decimal("0.02")),))
    with pytest.raises(EngineInputError):
        replace(v, supplier_id="G1", member_supplier_ids=frozenset({"G1"}))
    with pytest.raises(EngineInputError):
        replace(v, supplier_id="G1", member_supplier_ids=frozenset({""}))


# Input hashes of existing results, computed with engine 1.0.0 before buying groups were
# added. A supplier agreement must hash exactly as before (stored results stay comparable).
PINNED_1_0_0 = {
    ("01_flat_percent", "A1"): "6e24f1c995a66638bbaa297ce9f5da4146949d3a8d0522f41707250173ff6417",
    ("13_growth_zero_baseline_policies", "A3"): (
        "b7613eab178a6434e55ae9a7efdd3a246c9fcd3a4187a3473e2ec1552a71992e"
    ),
    ("25_stackable_no_conflict", "A2"): (
        "a03d94b2fbbdd1451e140b284da8c8db347511a427115aec39e0672c98940155"
    ),
}


def test_supplier_agreement_hashes_are_unchanged_from_1_0_0() -> None:
    from tests.engine.golden import load_all, run_fixture

    seen: dict[tuple[str, str], str] = {}
    for fx in load_all():
        for r in run_fixture(fx):
            if r.period.start == date(2026, 1, 1):
                seen.setdefault((fx.path.stem, r.agreement_id), r.input_hash)
    for key, want in PINNED_1_0_0.items():
        assert seen[key] == want, key
