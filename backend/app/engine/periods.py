"""Period arithmetic. Pure date math, no clock."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.engine.models import EngineInputError, Period, PeriodType, PriorPeriodOffset

_MONTHS_PER_PERIOD = {
    PeriodType.MONTHLY: 1,
    PeriodType.QUARTERLY: 3,
    PeriodType.SEMIANNUAL: 6,
    PeriodType.ANNUAL: 12,
}


def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def _first_of(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _label(period_type: PeriodType, start: date, fiscal_start: int) -> str:
    if period_type is PeriodType.MONTHLY:
        return f"{start:%Y-%m}"
    # Fiscal year is named after the calendar year in which it ends (common US usage).
    fy_offset = (start.month - fiscal_start) % 12
    fy_end_year = start.year + (1 if fiscal_start != 1 and start.month >= fiscal_start else 0)
    fy = f"FY{fy_end_year}" if fiscal_start != 1 else f"{start.year}"
    if period_type is PeriodType.QUARTERLY:
        return f"{fy}-Q{fy_offset // 3 + 1}"
    if period_type is PeriodType.SEMIANNUAL:
        return f"{fy}-H{fy_offset // 6 + 1}"
    return fy


def standard_period_containing(d: date, period_type: PeriodType, fiscal_start: int) -> Period:
    """The monthly/quarterly/semiannual/annual period that contains ``d``."""
    if period_type is PeriodType.CUSTOM:
        raise EngineInputError("custom periods are not generated from a date")
    if not 1 <= fiscal_start <= 12:
        raise EngineInputError("fiscal start month must be 1..12")
    n = _MONTHS_PER_PERIOD[period_type]
    idx = _month_index(d)
    anchor = fiscal_start - 1
    start_idx = idx - ((idx - anchor) % n)
    start = _first_of(start_idx)
    end = _first_of(start_idx + n) - timedelta(days=1)
    return Period(start, end, _label(period_type, start, fiscal_start))


def periods_overlapping(
    period_type: PeriodType,
    fiscal_start: int,
    range_start: date,
    range_end: date,
    custom_periods: tuple[Period, ...] = (),
) -> list[Period]:
    """All whole periods that overlap the inclusive range, in ascending order."""
    if range_end < range_start:
        raise EngineInputError("range end is before start")
    if period_type is PeriodType.CUSTOM:
        return sorted(
            (p for p in custom_periods if p.start <= range_end and p.end >= range_start),
            key=lambda p: p.start,
        )
    out: list[Period] = []
    current = standard_period_containing(range_start, period_type, fiscal_start)
    while current.start <= range_end:
        out.append(current)
        current = standard_period_containing(
            current.end + timedelta(days=1), period_type, fiscal_start
        )
    return out


def clip(period: Period, start: date, end: date) -> Period | None:
    """Intersection of ``period`` with ``[start, end]``; None if empty."""
    s = max(period.start, start)
    e = min(period.end, end)
    if e < s:
        return None
    return Period(s, e, period.label)


def shift_years(d: date, years: int) -> date:
    """Shift by whole years. Month-end stays month-end (handles Feb 29 both ways)."""
    y = d.year + years
    if d.day == _last_day(d.year, d.month):
        return date(y, d.month, _last_day(y, d.month))
    return date(y, d.month, min(d.day, _last_day(y, d.month)))


def prior_period(
    period: Period,
    offset: PriorPeriodOffset,
    period_type: PeriodType,
    fiscal_start: int,
    custom_periods: tuple[Period, ...] = (),
) -> Period | None:
    """The baseline period for ``period``; None when it cannot be determined unambiguously."""
    if offset is PriorPeriodOffset.SAME_PERIOD_PRIOR_YEAR:
        return Period(shift_years(period.start, -1), shift_years(period.end, -1), "prior year")
    if period_type is PeriodType.CUSTOM:
        earlier = [p for p in custom_periods if p.end < period.start]
        if not earlier:
            return None
        return max(earlier, key=lambda p: p.start)
    previous_end = period.start - timedelta(days=1)
    return standard_period_containing(previous_end, period_type, fiscal_start)
