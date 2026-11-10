"""Unit tests for engine building blocks not fully exercised by golden fixtures."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine import canonical
from app.engine.calculate import calculate, due_date
from app.engine.models import (
    Baseline,
    BaselineSource,
    CalcOptions,
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
    PurchaseLine,
    ReviewReason,
    RoundingMode,
    RuleAction,
    RuleField,
    SpendBasis,
    Stacking,
    Status,
    ThresholdComparison,
    Tier,
    VersionResolution,
    VersionSnapshot,
    ZeroBaselinePolicy,
)
from app.engine.periods import (
    clip,
    periods_overlapping,
    prior_period,
    shift_years,
    standard_period_containing,
)
from app.engine.planner import plan_agreement, run_jobs

FLAT = Component("base", ComponentType.FLAT_PERCENT, rate=Decimal("0.01"))


def snap(**kw: object) -> VersionSnapshot:
    base: dict[str, object] = {
        "agreement_id": "A1",
        "version_id": "A1-v1",
        "version_no": 1,
        "supplier_id": "S1",
        "effective_from": date(2026, 1, 1),
        "effective_to": None,
        "period_type": PeriodType.QUARTERLY,
        "fiscal_year_start_month": 1,
        "date_basis": DateBasis.INVOICE_DATE,
        "measure": Measure.SPEND,
        "spend_basis": SpendBasis.NET_OF_RETURNS,
        "threshold_comparison": ThresholdComparison.GTE,
        "components": (FLAT,),
        "negative_result": NegativeResult.FLOOR_AT_ZERO,
        "rounding_mode": RoundingMode.HALF_UP,
        "payment_terms_days": 30,
        "stacking": Stacking.STACKABLE,
        "prorate_thresholds_on_partial_period": False,
        "zero_baseline_policy": ZeroBaselinePolicy.NEEDS_REVIEW,
    }
    base.update(kw)
    return VersionSnapshot(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- periods


@pytest.mark.parametrize(
    ("ptype", "fiscal", "d", "start", "end", "label"),
    [
        (PeriodType.MONTHLY, 1, date(2026, 2, 14), date(2026, 2, 1), date(2026, 2, 28), "2026-02"),
        (PeriodType.QUARTERLY, 1, date(2026, 5, 5), date(2026, 4, 1), date(2026, 6, 30), "2026-Q2"),
        (
            PeriodType.QUARTERLY,
            7,
            date(2026, 8, 1),
            date(2026, 7, 1),
            date(2026, 9, 30),
            "FY2027-Q1",
        ),
        (
            PeriodType.QUARTERLY,
            7,
            date(2027, 1, 9),
            date(2027, 1, 1),
            date(2027, 3, 31),
            "FY2027-Q3",
        ),
        (
            PeriodType.SEMIANNUAL,
            1,
            date(2026, 9, 1),
            date(2026, 7, 1),
            date(2026, 12, 31),
            "2026-H2",
        ),
        (
            PeriodType.SEMIANNUAL,
            4,
            date(2026, 2, 1),
            date(2025, 10, 1),
            date(2026, 3, 31),
            "FY2026-H2",
        ),
        (PeriodType.ANNUAL, 1, date(2026, 9, 1), date(2026, 1, 1), date(2026, 12, 31), "2026"),
        (PeriodType.ANNUAL, 10, date(2026, 9, 1), date(2025, 10, 1), date(2026, 9, 30), "FY2026"),
    ],
)
def test_standard_periods(
    ptype: PeriodType, fiscal: int, d: date, start: date, end: date, label: str
) -> None:
    p = standard_period_containing(d, ptype, fiscal)
    assert (p.start, p.end, p.label) == (start, end, label)


def test_standard_period_rejects_custom_and_bad_month() -> None:
    with pytest.raises(EngineInputError):
        standard_period_containing(date(2026, 1, 1), PeriodType.CUSTOM, 1)
    with pytest.raises(EngineInputError):
        standard_period_containing(date(2026, 1, 1), PeriodType.MONTHLY, 13)


def test_periods_overlapping_and_custom() -> None:
    got = periods_overlapping(PeriodType.MONTHLY, 1, date(2026, 1, 15), date(2026, 3, 1))
    assert [p.start.month for p in got] == [1, 2, 3]
    custom = (
        Period(date(2026, 2, 15), date(2026, 3, 31), "B"),
        Period(date(2026, 1, 1), date(2026, 2, 14), "A"),
    )
    got = periods_overlapping(PeriodType.CUSTOM, 1, date(2026, 1, 1), date(2026, 12, 31), custom)
    assert [p.label for p in got] == ["A", "B"]
    with pytest.raises(EngineInputError):
        periods_overlapping(PeriodType.MONTHLY, 1, date(2026, 2, 1), date(2026, 1, 1))


def test_clip_and_period_validation() -> None:
    q1 = Period(date(2026, 1, 1), date(2026, 3, 31))
    assert clip(q1, date(2026, 4, 1), date(2026, 5, 1)) is None
    clipped = clip(q1, date(2026, 2, 1), date(2026, 12, 31))
    assert clipped == Period(date(2026, 2, 1), date(2026, 3, 31))
    with pytest.raises(EngineInputError):
        Period(date(2026, 2, 1), date(2026, 1, 1))


def test_shift_years_handles_leap_days() -> None:
    assert shift_years(date(2028, 2, 29), -1) == date(2027, 2, 28)
    assert shift_years(date(2029, 2, 28), -1) == date(2028, 2, 29)  # month end stays month end
    assert shift_years(date(2026, 3, 15), -1) == date(2025, 3, 15)


def test_prior_period_variants() -> None:
    q1 = Period(date(2026, 1, 1), date(2026, 3, 31))
    yoy = prior_period(q1, PriorPeriodOffset.SAME_PERIOD_PRIOR_YEAR, PeriodType.QUARTERLY, 1)
    assert yoy == Period(date(2025, 1, 1), date(2025, 3, 31))
    prev = prior_period(q1, PriorPeriodOffset.IMMEDIATELY_PRECEDING, PeriodType.QUARTERLY, 1)
    assert prev == Period(date(2025, 10, 1), date(2025, 12, 31))
    custom = (
        Period(date(2026, 1, 1), date(2026, 2, 14)),
        Period(date(2026, 2, 15), date(2026, 3, 31)),
    )
    assert (
        prior_period(
            custom[1], PriorPeriodOffset.IMMEDIATELY_PRECEDING, PeriodType.CUSTOM, 1, custom
        )
        == custom[0]
    )
    assert (
        prior_period(
            custom[0], PriorPeriodOffset.IMMEDIATELY_PRECEDING, PeriodType.CUSTOM, 1, custom
        )
        is None
    )


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": ComponentType.FLAT_PERCENT},
        {"type": ComponentType.PER_UNIT},
        {"type": ComponentType.TIERED_ALL_UNITS},
        {
            "type": ComponentType.TIERED_ALL_UNITS,
            "tiers": (Tier(Decimal(5), rate=Decimal("0.1")), Tier(Decimal(5), rate=Decimal("0.2"))),
        },
        {
            "type": ComponentType.TIERED_ALL_UNITS,
            "tiers": (
                Tier(Decimal(1), rate=Decimal("0.1")),
                Tier(Decimal(5), amount_per_unit=Decimal(1)),
            ),
        },
        {"type": ComponentType.GROWTH_INCREMENTAL, "baseline_source": BaselineSource.IMPORTED},
        {
            "type": ComponentType.GROWTH_THRESHOLD,
            "rate": Decimal(1),
            "baseline_source": BaselineSource.IMPORTED,
        },
        {"type": ComponentType.GROWTH_INCREMENTAL, "rate": Decimal(1)},
        {
            "type": ComponentType.GROWTH_INCREMENTAL,
            "rate": Decimal(1),
            "baseline_source": BaselineSource.PRIOR_PERIOD_COMPUTED,
        },
        {"type": ComponentType.FIXED_BONUS, "amount": Decimal(1)},
        {"type": ComponentType.FLAT_PERCENT, "rate": 0.02},
        {"type": ComponentType.FLAT_PERCENT, "rate": Decimal("NaN")},
    ],
)
def test_invalid_components(kwargs: dict[str, object]) -> None:
    with pytest.raises(EngineInputError):
        Component("c", **kwargs)  # type: ignore[arg-type]


def test_component_requires_id_and_tier_rules() -> None:
    with pytest.raises(EngineInputError):
        Component("", ComponentType.FLAT_PERCENT, rate=Decimal(1))
    with pytest.raises(EngineInputError):
        Tier(Decimal(1))
    with pytest.raises(EngineInputError):
        Tier(Decimal(-1), rate=Decimal(1))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fiscal_year_start_month": 0},
        {"effective_to": date(2025, 1, 1)},
        {"components": ()},
        {"components": (FLAT, FLAT)},
        {"payment_terms_days": -1},
        {"cap_amount": Decimal(-1)},
        {"period_type": PeriodType.CUSTOM},
        {
            "period_type": PeriodType.CUSTOM,
            "custom_periods": (
                Period(date(2026, 1, 1), date(2026, 2, 1)),
                Period(date(2026, 2, 1), date(2026, 3, 1)),
            ),
        },
        {
            "components": (
                Component(
                    "i",
                    ComponentType.TIERED_INCREMENTAL,
                    tiers=(Tier(Decimal(0), amount_per_unit=Decimal(1)),),
                ),
            )
        },
        {
            "measure": Measure.QUANTITY,
            "components": (
                Component(
                    "i",
                    ComponentType.TIERED_INCREMENTAL,
                    tiers=(Tier(Decimal(0), rate=Decimal(1)),),
                ),
            ),
        },
    ],
)
def test_invalid_versions(kwargs: dict[str, object]) -> None:
    with pytest.raises(EngineInputError):
        snap(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"field": RuleField.FLAG},
        {
            "field": RuleField.MIN_LINE_AMOUNT,
            "min_amount": Decimal(1),
            "action": RuleAction.EXCLUDE,
        },
        {"field": RuleField.MIN_LINE_AMOUNT},
        {"field": RuleField.SKU},
    ],
)
def test_invalid_rules(kwargs: dict[str, object]) -> None:
    args: dict[str, object] = {"id": "r", "action": RuleAction.INCLUDE}
    args.update(kwargs)
    with pytest.raises(EngineInputError):
        EligibilityRule(**args)  # type: ignore[arg-type]


def test_purchase_line_rejects_duplicate_flags_and_reads_dates() -> None:
    with pytest.raises(EngineInputError):
        PurchaseLine("L", "S", Decimal(1), Decimal(1), flags=(("a", True), ("a", False)))
    ln = PurchaseLine("L", "S", Decimal(1), Decimal(1), receipt_date=date(2026, 1, 2))
    assert ln.basis_date(DateBasis.RECEIPT_DATE) == date(2026, 1, 2)
    assert ln.flag("missing") is None


# --------------------------------------------------------------------------- calculate guards


def test_window_must_be_inside_full_period_and_version() -> None:
    v = snap(effective_from=date(2026, 2, 1))
    q1 = Period(date(2026, 1, 1), date(2026, 3, 31))
    with pytest.raises(EngineInputError):
        calculate(v, q1, [])
    with pytest.raises(EngineInputError):
        calculate(
            v, q1, [], options=CalcOptions(full_period=Period(date(2026, 2, 1), date(2026, 2, 28)))
        )


def test_trace_lets_a_user_recompute() -> None:
    lines = [
        PurchaseLine("L1", "S1", Decimal(1), Decimal("1234.56"), invoice_date=date(2026, 1, 5))
    ]
    r = calculate(snap(), Period(date(2026, 1, 1), date(2026, 3, 31)), lines)
    steps = [t.step for t in r.trace]
    assert steps == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    component = r.trace[3]
    assert "0.01 × 1234.56 = 12.3456" in component.description
    assert r.trace[8].as_dict()["values"] == {"unrounded": "12.3456", "expected": "12.35"}
    assert due_date(r) == date(2026, 4, 30)


def test_stacking_conflict_message_truncates_long_lists() -> None:
    from app.engine.models import StackingConflict

    ids = tuple(f"L{i:03d}" for i in range(25))
    r = calculate(
        snap(),
        Period(date(2026, 1, 1), date(2026, 3, 31)),
        [],
        options=CalcOptions(stacking_conflicts=(StackingConflict("A2", ids),)),
    )
    assert r.needs_review and "and 5 more" in r.reasons[0].message
    assert r.expected is None and r.tier_reached is None


def test_imported_baseline_duplicates_with_same_value_are_fine() -> None:
    comp = Component(
        "g",
        ComponentType.GROWTH_INCREMENTAL,
        rate=Decimal("0.1"),
        baseline_source=BaselineSource.IMPORTED,
    )
    q1 = Period(date(2026, 1, 1), date(2026, 3, 31))
    bl = [
        Baseline("A1", q1.start, q1.end, Decimal(100), "x"),
        Baseline("A1", q1.start, q1.end, Decimal("100.0"), "y"),
    ]
    lines = [PurchaseLine("L1", "S1", Decimal(1), Decimal(300), invoice_date=date(2026, 1, 5))]
    r = calculate(snap(components=(comp,)), q1, lines, bl)
    assert r.expected == Decimal("20.00")


def test_custom_period_without_predecessor_is_baseline_missing() -> None:
    comp = Component(
        "g",
        ComponentType.GROWTH_INCREMENTAL,
        rate=Decimal("0.1"),
        baseline_source=BaselineSource.PRIOR_PERIOD_COMPUTED,
        prior_period_offset=PriorPeriodOffset.IMMEDIATELY_PRECEDING,
    )
    p = Period(date(2026, 1, 1), date(2026, 3, 31))
    v = snap(components=(comp,), period_type=PeriodType.CUSTOM, custom_periods=(p,))
    r = calculate(v, p, [], options=CalcOptions(data_coverage_start=date(2000, 1, 1)))
    assert [x.code for x in r.reasons] == [ReviewReason.BASELINE_MISSING.value]


# --------------------------------------------------------------------------- planner


def test_plan_rejects_mixed_and_overlapping_versions() -> None:
    assert plan_agreement([], date(2026, 1, 1), date(2026, 3, 31)) == []
    with pytest.raises(EngineInputError):
        plan_agreement([snap(), snap(agreement_id="A2")], date(2026, 1, 1), date(2026, 3, 31))
    with pytest.raises(EngineInputError):
        plan_agreement(
            [snap(), snap(version_no=2, version_id="v2", effective_from=date(2026, 2, 1))],
            date(2026, 1, 1),
            date(2026, 3, 31),
        )


def test_plan_skips_versions_outside_range_and_gaps() -> None:
    v1 = snap(effective_to=date(2025, 12, 31), effective_from=date(2025, 1, 1))
    v2 = snap(version_no=2, version_id="v2", effective_from=date(2026, 1, 1))
    jobs = plan_agreement([v1, v2], date(2026, 1, 1), date(2026, 3, 31))
    assert [(j.version.version_no, j.window.start) for j in jobs] == [(2, date(2026, 1, 1))]


def test_split_resolution_with_gap_between_versions() -> None:
    v1 = snap(effective_to=date(2026, 1, 31))
    v2 = snap(version_no=2, version_id="v2", effective_from=date(2026, 3, 1))
    key = ("A1", date(2026, 1, 1), date(2026, 3, 31))
    jobs = plan_agreement(
        [v1, v2], date(2026, 1, 1), date(2026, 3, 31), {key: VersionResolution.SPLIT}
    )
    assert [(j.window.start, j.window.end) for j in jobs] == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 3, 1), date(2026, 3, 31)),
    ]
    results = run_jobs(jobs, [])
    assert all(Status.PARTIAL_PERIOD in r.statuses for r in results)


def test_mixed_period_types_flag_each_period_once() -> None:
    v1 = snap(effective_to=date(2026, 2, 15), period_type=PeriodType.MONTHLY)
    v2 = snap(version_no=2, version_id="v2", effective_from=date(2026, 2, 16))
    jobs = plan_agreement([v1, v2], date(2026, 1, 1), date(2026, 3, 31))
    reviews = [j for j in jobs if j.review_reason is ReviewReason.VERSION_CHANGE_IN_PERIOD]
    assert {(j.full_period.start, j.full_period.end) for j in reviews} == {
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 1, 1), date(2026, 3, 31)),
    }


# --------------------------------------------------------------------------- canonical


def test_canonical_normalises_decimals_and_rejects_unknown() -> None:
    assert canonical.canonical_json(Decimal("2.0")) == canonical.canonical_json(Decimal("2.00"))
    assert canonical.canonical_json(Decimal("-0.00")) == '"0"'
    assert canonical.canonical_json({"b": {1, 2}, "a": frozenset()}) == '{"a":[],"b":[1,2]}'
    with pytest.raises(TypeError):
        canonical.canonical_json(object())


def test_quantity_measure_with_gross_basis() -> None:
    v = snap(measure=Measure.QUANTITY, spend_basis=SpendBasis.GROSS)
    lines = [
        PurchaseLine("L1", "S1", Decimal(10), Decimal(100), invoice_date=date(2026, 1, 5)),
        PurchaseLine("L2", "S1", Decimal(-4), Decimal(-40), invoice_date=date(2026, 1, 6)),
    ]
    r = calculate(v, Period(date(2026, 1, 1), date(2026, 3, 31)), lines)
    assert (r.measure, r.quantity) == (Decimal(10), Decimal(6))


def test_replace_keeps_validation() -> None:
    with pytest.raises(EngineInputError):
        replace(snap(), payment_terms_days=-5)


# --------------------------------------------------------------------------- isolation

ALLOWED_IMPORTS = {
    "__future__",
    "calendar",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "hashlib",
    "itertools",
    "json",
    "re",
    "typing",
}


def test_engine_imports_nothing_impure() -> None:
    """No web, DB, storage, clock-reading, random or OS modules inside app/engine."""
    engine_dir = Path(__file__).resolve().parents[2] / "app" / "engine"
    for path in engine_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                root = name.split(".")[0]
                assert name.startswith("app.engine") or root in ALLOWED_IMPORTS, (
                    f"{path.name} imports {name}"
                )
        source = path.read_text(encoding="utf-8")
        for banned in ("date.today", "datetime.now", "datetime.utcnow", "time.time", "open("):
            assert banned not in source, f"{path.name} uses {banned}"
