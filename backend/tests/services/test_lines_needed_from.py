"""The tier tracker loads only the purchase lines the engine can read (Phase 10 load fix).

A bound that is too late would silently drop the lines a computed growth baseline needs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.engine.models import (
    BaselineSource,
    Component,
    ComponentType,
    Period,
    PriorPeriodOffset,
)
from app.services.agreements import lines_needed_from
from tests.engine.test_properties import version

Q3 = Period(date(2026, 7, 1), date(2026, 9, 30), "2026-Q3")


def test_no_growth_component_reads_only_the_period() -> None:
    snap = version((Component(id="c1", type=ComponentType.FLAT_PERCENT, rate=Decimal("0.02")),))
    assert lines_needed_from(snap, Q3) == Q3.start


def test_same_period_prior_year_baseline_reaches_back_a_year() -> None:
    snap = version(
        (
            Component(
                id="g1",
                type=ComponentType.GROWTH_INCREMENTAL,
                rate=Decimal("0.05"),
                baseline_source=BaselineSource.PRIOR_PERIOD_COMPUTED,
                prior_period_offset=PriorPeriodOffset.SAME_PERIOD_PRIOR_YEAR,
            ),
        )
    )
    assert lines_needed_from(snap, Q3) == date(2025, 7, 1)


def test_previous_period_baseline_reaches_back_one_period() -> None:
    snap = version(
        (
            Component(
                id="g1",
                type=ComponentType.GROWTH_INCREMENTAL,
                rate=Decimal("0.05"),
                baseline_source=BaselineSource.PRIOR_PERIOD_COMPUTED,
                prior_period_offset=PriorPeriodOffset.IMMEDIATELY_PRECEDING,
            ),
        )
    )
    assert lines_needed_from(snap, Q3) == date(2026, 4, 1)


def test_imported_baseline_needs_no_prior_lines() -> None:
    snap = version(
        (
            Component(
                id="g1",
                type=ComponentType.GROWTH_INCREMENTAL,
                rate=Decimal("0.05"),
                baseline_source=BaselineSource.IMPORTED,
            ),
        )
    )
    assert lines_needed_from(snap, Q3) == Q3.start
