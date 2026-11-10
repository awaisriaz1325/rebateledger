"""Turns agreement versions + a run range into agreement-period jobs, then runs them.

Handles (SPEC §4.4.4):
- partial periods (version starts/ends mid-period) → clipped, PARTIAL_PERIOD;
- version boundaries inside a period → NEEDS_REVIEW VERSION_CHANGE_IN_PERIOD unless
  the user supplied a resolution (apply old / apply new / split);
- exclusive stacking conflicts across agreements of the same supplier.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.engine.calculate import PeriodResult, calculate, select_lines
from app.engine.models import (
    Baseline,
    CalcOptions,
    EngineInputError,
    Period,
    PurchaseLine,
    ReviewReason,
    Stacking,
    StackingConflict,
    VersionResolution,
    VersionSnapshot,
)
from app.engine.periods import clip, periods_overlapping

PeriodKey = tuple[str, date, date]
"""(agreement_id, full period start, full period end)."""


@dataclass(frozen=True, slots=True)
class PeriodJob:
    version: VersionSnapshot
    window: Period
    full_period: Period
    review_reason: ReviewReason | None = None
    review_message: str = ""
    resolution: VersionResolution | None = None


def _overlaps(a: Period, b: Period) -> bool:
    return a.start <= b.end and b.start <= a.end


def plan_agreement(
    versions: Sequence[VersionSnapshot],
    range_start: date,
    range_end: date,
    resolutions: Mapping[PeriodKey, VersionResolution] | None = None,
) -> list[PeriodJob]:
    """Jobs for one agreement's active/superseded/expired versions over a run range."""
    if not versions:
        return []
    agreement_ids = {v.agreement_id for v in versions}
    if len(agreement_ids) != 1:
        raise EngineInputError("plan_agreement takes versions of exactly one agreement")
    ordered = sorted(versions, key=lambda v: (v.effective_from, v.version_no))
    for a, b in itertools.pairwise(ordered):
        if _overlaps(a.effective_period, b.effective_period):
            raise EngineInputError(
                f"versions {a.version_no} and {b.version_no} have overlapping effective ranges"
            )
    res = resolutions or {}
    jobs: list[PeriodJob] = []
    emitted_reviews: set[tuple[date, date]] = set()
    for v in ordered:
        eff = v.effective_period
        lo = max(range_start, eff.start)
        hi = min(range_end, eff.end)
        if hi < lo:
            continue
        for full in periods_overlapping(
            v.period_type, v.fiscal_year_start_month, lo, hi, v.custom_periods
        ):
            window = clip(full, eff.start, eff.end)
            assert window is not None
            touching = [w for w in ordered if _overlaps(w.effective_period, full)]
            if len(touching) == 1:
                jobs.append(PeriodJob(v, window, full))
                continue
            key = (v.agreement_id, full.start, full.end)
            choice = res.get(key)
            if choice is None:
                if (full.start, full.end) in emitted_reviews:
                    continue
                emitted_reviews.add((full.start, full.end))
                nos = ", ".join(str(w.version_no) for w in touching)
                msg = (
                    f"versions {nos} both apply inside {full.start}..{full.end}. Choose: apply "
                    "the old version, apply the new version, or split the period at the boundary."
                )
                newest = touching[-1]
                jobs.append(
                    PeriodJob(
                        newest,
                        full,
                        full,
                        ReviewReason.VERSION_CHANGE_IN_PERIOD,
                        msg,
                    )
                )
            elif choice is VersionResolution.SPLIT:
                jobs.append(PeriodJob(v, window, full, resolution=choice))
            else:
                chosen = touching[0] if choice is VersionResolution.APPLY_OLD else touching[-1]
                if chosen is not v:
                    continue
                span_start = max(full.start, touching[0].effective_from)
                last_end = touching[-1].effective_period.end
                span_end = min(full.end, last_end)
                jobs.append(
                    PeriodJob(v, Period(span_start, span_end, full.label), full, None, "", choice)
                )
    return jobs


def find_stacking_conflicts(
    jobs: Sequence[PeriodJob], lines: Sequence[PurchaseLine]
) -> dict[int, tuple[StackingConflict, ...]]:
    """Index of job → conflicts. A line eligible for two agreements of the same supplier
    conflicts when at least one of them is exclusive (an exclusive agreement says its
    lines may not count elsewhere)."""
    by_supplier: dict[str, list[PurchaseLine]] = {}
    for ln in lines:
        by_supplier.setdefault(ln.supplier_id, []).append(ln)
    eligible: list[frozenset[str]] = []
    for job in jobs:
        sel = select_lines(job.version, job.window, by_supplier.get(job.version.supplier_id, []))
        eligible.append(frozenset(ln.line_id for ln in sel.eligible))
    found: dict[int, dict[str, set[str]]] = {}
    for i, a in enumerate(jobs):
        for j in range(i + 1, len(jobs)):
            b = jobs[j]
            if a.version.supplier_id != b.version.supplier_id:
                continue
            if a.version.agreement_id == b.version.agreement_id:
                continue
            if Stacking.EXCLUSIVE not in (a.version.stacking, b.version.stacking):
                continue
            shared = eligible[i] & eligible[j]
            if not shared:
                continue
            found.setdefault(i, {}).setdefault(b.version.agreement_id, set()).update(shared)
            found.setdefault(j, {}).setdefault(a.version.agreement_id, set()).update(shared)
    return {
        idx: tuple(
            StackingConflict(other, tuple(sorted(ids))) for other, ids in sorted(conflicts.items())
        )
        for idx, conflicts in found.items()
    }


def run_jobs(
    jobs: Sequence[PeriodJob],
    lines: Sequence[PurchaseLine],
    baselines: Sequence[Baseline] = (),
    data_coverage_start: Mapping[str, date] | None = None,
) -> list[PeriodResult]:
    """Calculate every job. Output order follows (agreement, period start, version)."""
    coverage = data_coverage_start or {}
    conflicts = find_stacking_conflicts(jobs, lines)
    by_supplier: dict[str, list[PurchaseLine]] = {}
    for ln in lines:
        by_supplier.setdefault(ln.supplier_id, []).append(ln)
    results: list[PeriodResult] = []
    for idx, job in enumerate(jobs):
        opts = CalcOptions(
            data_coverage_start=coverage.get(job.version.supplier_id),
            stacking_conflicts=conflicts.get(idx, ()),
            review_reason=job.review_reason,
            review_message=job.review_message,
            full_period=job.full_period,
            version_resolution=job.resolution,
        )
        results.append(
            calculate(
                job.version,
                job.window,
                by_supplier.get(job.version.supplier_id, []),
                baselines,
                opts,
            )
        )
    results.sort(key=lambda r: (r.agreement_id, r.period.start, r.version_no))
    return results
