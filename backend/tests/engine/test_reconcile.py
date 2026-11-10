"""Reconciliation status, matching and allocation (SPEC §4.7, §9 cases 31–36)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.engine.models import EngineInputError, Period
from app.engine.reconcile import (
    Allocation,
    Credit,
    MatchTarget,
    Outstanding,
    ReconFlag,
    ReconStatus,
    Tolerance,
    allocation_remainder,
    auto_match,
    reconcile_item,
    suggest,
)

Q1 = Period(date(2026, 1, 1), date(2026, 3, 31), "2026-Q1")
Q2 = Period(date(2026, 4, 1), date(2026, 6, 30), "2026-Q2")
Q3 = Period(date(2026, 7, 1), date(2026, 9, 30), "2026-Q3")
TOL = Tolerance()
DUE = date(2026, 4, 30)  # Q1 end + 30 days


def alloc(amount: str, credit: str = "C1", period: Period = Q1) -> Allocation:
    return Allocation(credit, "A1", period.start, period.end, Decimal(amount))


def status(
    expected: str | None,
    allocs: list[Allocation],
    today: date,
    review: bool = False,
    credit_dates: dict[str, date] | None = None,
) -> tuple[ReconStatus, tuple[ReconFlag, ...], Decimal]:
    item = reconcile_item(
        agreement_id="A1",
        period=Q1,
        expected=None if expected is None else Decimal(expected),
        engine_needs_review=review,
        allocations=allocs,
        credit_dates=credit_dates or {},
        payment_terms_days=30,
        today=today,
        tolerance=TOL,
    )
    assert item.due_date == DUE
    return item.status, item.flags, item.received


def test_needs_review_takes_precedence() -> None:
    assert status("100", [], date(2027, 1, 1), review=True)[0] is ReconStatus.NEEDS_REVIEW
    assert status(None, [], date(2027, 1, 1))[0] is ReconStatus.NEEDS_REVIEW


def test_not_earned_matched_overpaid() -> None:
    assert status("0.00", [], date(2027, 1, 1))[0] is ReconStatus.NOT_EARNED
    # Case 35: T = max(1.00, 0.005 × 1000) = 5.00 ; V = −4.99 → MATCHED
    assert status("1000.00", [alloc("995.01")], date(2027, 1, 1))[0] is ReconStatus.MATCHED
    assert status("1000.00", [alloc("1005.01")], date(2027, 1, 1))[0] is ReconStatus.OVERPAID
    assert status("0.00", [alloc("10")], date(2027, 1, 1))[0] is ReconStatus.OVERPAID


def test_due_date_boundary() -> None:
    """Case 36: PENDING through the due date, MISSING/SHORT_PAID from the next day."""
    assert status("1000", [], DUE)[0] is ReconStatus.PENDING
    assert status("1000", [], date(2026, 5, 1))[0] is ReconStatus.MISSING
    assert status("1000", [alloc("500")], DUE)[0] is ReconStatus.PENDING
    assert status("1000", [alloc("500")], date(2026, 5, 1))[0] is ReconStatus.SHORT_PAID


def test_two_credits_sum_and_reversal_flag() -> None:
    """Case 32 (two credits summed) and case 34 (negative credit reduces C, flagged)."""
    st, flags, received = status("1000", [alloc("600", "C1"), alloc("400", "C2")], date(2027, 1, 1))
    assert (st, received) == (ReconStatus.MATCHED, Decimal(1000))
    st, flags, received = status(
        "1000", [alloc("1000", "C1"), alloc("-300", "C2")], date(2027, 1, 1)
    )
    assert (st, received, flags) == (ReconStatus.SHORT_PAID, Decimal(700), (ReconFlag.REVERSAL,))
    st, _, _ = status("1000", [alloc("-50", "C2")], date(2027, 1, 1))
    assert st is ReconStatus.SHORT_PAID


def test_early_credit_flag() -> None:
    """Case 33: a credit dated before period end is allowed and flagged."""
    _, flags, _ = status(
        "100", [alloc("100")], date(2027, 1, 1), credit_dates={"C1": date(2026, 3, 1)}
    )
    assert flags == (ReconFlag.EARLY_CREDIT,)


def test_allocations_for_other_periods_are_ignored() -> None:
    st, _, received = status("100", [alloc("100", period=Q2)], date(2027, 1, 1))
    assert (st, received) == (ReconStatus.MISSING, Decimal(0))


def test_split_one_credit_across_three_quarters() -> None:
    """Case 31: one credit pays three quarters; remainder tracked."""
    credit = Credit("C1", "S1", date(2026, 10, 15), Decimal("1000.00"), "CR-1")
    parts = [alloc("300", period=Q1), alloc("300", period=Q2), alloc("250", period=Q3)]
    assert allocation_remainder(credit, parts) == Decimal("150.00")
    with pytest.raises(EngineInputError):
        allocation_remainder(credit, [*parts, alloc("151", period=Q3)])
    with pytest.raises(EngineInputError):
        allocation_remainder(credit, [alloc("-1")])


def test_reversal_allocation_rules() -> None:
    credit = Credit("C1", "S1", date(2026, 10, 15), Decimal("-100"), "R-1")
    assert allocation_remainder(credit, [alloc("-60")]) == Decimal("-40")
    with pytest.raises(EngineInputError):
        allocation_remainder(credit, [alloc("10")])
    with pytest.raises(EngineInputError):
        allocation_remainder(credit, [alloc("-101")])


def test_tolerance_validation() -> None:
    with pytest.raises(EngineInputError):
        Tolerance(Decimal(-1))
    assert Tolerance().for_expected(Decimal(10000)) == Decimal("50.000")


TARGETS = [
    MatchTarget("A1", "S1", "VOL-2026", Q1),
    MatchTarget("A1", "S1", "VOL-2026", Q2),
    MatchTarget("A2", "S1", "GROWTH", Q1),
]


def test_auto_match_by_reference_and_dates_or_label() -> None:
    credits = [
        Credit("C1", "S1", date(2026, 5, 1), Decimal(100), "R1", " vol-2026 ", Q1.start, Q1.end),
        Credit(
            "C2", "S1", date(2026, 8, 1), Decimal(200), "R2", "VOL-2026", period_label="q2 2026"
        ),
        Credit(
            "C3", "S1", date(2026, 8, 1), Decimal(300), "R3", "VOL-2026", period_label="2026/Q2"
        ),
        Credit("C4", "S1", date(2026, 8, 1), Decimal(1), "R4", None, Q1.start, Q1.end),  # no ref
        Credit("C5", "S1", date(2026, 8, 1), Decimal(1), "R5", "VOL-2026", period_label="2026-Q4"),
        Credit("C6", "S2", date(2026, 8, 1), Decimal(1), "R6", "VOL-2026", Q1.start, Q1.end),
        Credit("C7", "S1", date(2026, 8, 1), Decimal(1), "R7", "VOL-2026"),  # no period
    ]
    allocations, unmatched = auto_match(credits, TARGETS)
    assert [(a.credit_id, a.period_start, a.method) for a in allocations] == [
        ("C1", Q1.start, "auto"),
        ("C2", Q2.start, "auto"),
        ("C3", Q2.start, "auto"),
    ]
    assert [c.credit_id for c in unmatched] == ["C4", "C5", "C6", "C7"]


def test_auto_match_ambiguous_label_is_not_matched() -> None:
    dup = [*TARGETS, MatchTarget("A3", "S1", "VOL-2026", Q1)]
    credit = Credit(
        "C1", "S1", date(2026, 5, 1), Decimal(100), "R1", "VOL-2026", period_label="2026-Q1"
    )
    allocations, unmatched = auto_match([credit], dup)
    assert allocations == [] and unmatched == [credit]


def test_suggestions_window_and_tolerance() -> None:
    outstanding = [
        Outstanding("A1", "S1", Q1, Decimal("1000.00"), 30),
        Outstanding("A2", "S1", Q1, Decimal("998.00"), 30),
        Outstanding("A3", "S1", Q1, Decimal("5000.00"), 30),  # amount too far
        Outstanding("A4", "S2", Q1, Decimal("1000.00"), 30),  # other supplier
        Outstanding("A5", "S1", Q1, Decimal("0"), 30),  # nothing outstanding
        Outstanding("A6", "S1", Q3, Decimal("1000.00"), 30),  # credit before period end
    ]
    credit = Credit("C1", "S1", date(2026, 6, 29), Decimal("1000.00"), "R1")
    got = suggest(credit, outstanding, TOL)
    assert [s.agreement_id for s in got] == ["A1", "A2"]
    assert "payment terms 30 days + 60 days" in got[0].explanation
    late = Credit("C2", "S1", date(2026, 6, 30), Decimal("1000.00"), "R2")
    assert suggest(late, outstanding, TOL) == []  # Mar 31 + 90 days = Jun 29
