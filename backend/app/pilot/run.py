"""Pilot reconciliation: agreements + CSVs in, CSV/HTML reports out (PHASES §1 item 5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from app.engine.calculate import PeriodResult
from app.engine.models import Baseline, EngineInputError, PurchaseLine, VersionResolution
from app.engine.planner import PeriodKey, plan_agreement, run_jobs
from app.engine.reconcile import (
    Allocation,
    Credit,
    MatchTarget,
    Outstanding,
    ReconItem,
    ReconStatus,
    Suggestion,
    allocation_remainder,
    auto_match,
    reconcile_item,
    suggest,
)
from app.engine.version import ENGINE_VERSION
from app.pilot.agreements import AgreementFormatError, AgreementSpec, parse_agreements
from app.pilot.loaders import (
    Loaded,
    MappingConfig,
    RowIssue,
    load_allocations,
    load_baselines,
    load_credits,
    load_purchases,
    parse_mapping,
)

DISCREPANCY_STATUSES = (ReconStatus.SHORT_PAID, ReconStatus.MISSING, ReconStatus.OVERPAID)


class PilotError(Exception):
    """A problem with the inputs that stops the run; message is user-facing."""


@dataclass(frozen=True)
class PilotInputs:
    agreements: Path
    purchases: Path
    credits: Path
    mapping: Path
    range_start: date
    range_end: date
    as_of: date
    baselines: Path | None = None
    allocations: Path | None = None
    resolutions: Path | None = None
    coverage_overrides: Mapping[str, date] = field(default_factory=dict)
    skip_invalid: bool = False


@dataclass(frozen=True)
class ResultRow:
    result: PeriodResult
    agreement: AgreementSpec
    recon: ReconItem


@dataclass(frozen=True)
class UnmatchedCredit:
    credit: Credit
    remainder: Decimal
    suggestions: tuple[Suggestion, ...]


@dataclass
class PilotOutcome:
    rows: list[ResultRow]
    unmatched: list[UnmatchedCredit]
    issues: list[RowIssue]
    coverage: dict[str, tuple[date, str]]
    """supplier → (coverage start, 'override' | 'earliest date in file')."""
    counts: dict[str, int]
    as_of: date
    range_start: date
    range_end: date
    engine_version: str = ENGINE_VERSION


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PilotError(f"cannot read {path}: {exc}") from None


def _resolutions(path: Path | None) -> dict[PeriodKey, VersionResolution]:
    if path is None:
        return {}
    data = _yaml(path) or {}
    out: dict[PeriodKey, VersionResolution] = {}
    for i, item in enumerate(data.get("resolutions", []) or []):
        try:
            key = (
                str(item["agreement"]),
                date.fromisoformat(str(item["start"])),
                date.fromisoformat(str(item["end"])),
            )
            out[key] = VersionResolution(item["choice"])
        except KeyError, ValueError, TypeError:
            raise PilotError(
                f"{path}: resolutions[{i}] needs agreement, start, end and choice "
                "(apply_old | apply_new | split)"
            ) from None
    return out


def _coverage(
    lines: list[PurchaseLine], overrides: Mapping[str, date]
) -> dict[str, tuple[date, str]]:
    out: dict[str, tuple[date, str]] = {}
    for ln in lines:
        dates = [d for d in (ln.invoice_date, ln.ship_date, ln.receipt_date) if d is not None]
        if not dates:
            continue
        earliest = min(dates)
        current = out.get(ln.supplier_id)
        if current is None or earliest < current[0]:
            out[ln.supplier_id] = (earliest, "earliest date in file")
    for supplier, d in overrides.items():
        out[supplier] = (d, "override")
    return out


def _check(loaded: Loaded[Any], skip_invalid: bool, label: str) -> None:
    if loaded.errors and not skip_invalid:
        raise PilotError(
            f"{label}: {len(loaded.errors)} row error(s). Fix them or pass --skip-invalid "
            "(skipped rows are listed in issues.csv)."
        )


def run_pilot(inputs: PilotInputs) -> PilotOutcome:
    if inputs.range_end < inputs.range_start:
        raise PilotError("--to is before --from")
    try:
        specs = parse_agreements(_yaml(inputs.agreements))
        cfg: MappingConfig = parse_mapping(_yaml(inputs.mapping))
    except AgreementFormatError as exc:
        raise PilotError(str(exc)) from None

    by_ref: dict[str, str] = {}
    for spec in specs:
        by_ref[spec.agreement_id.casefold()] = spec.agreement_id
        if spec.external_reference:
            by_ref[spec.external_reference.casefold()] = spec.agreement_id

    try:
        purchases = load_purchases(inputs.purchases, cfg)
        credits = load_credits(inputs.credits, cfg)
        baselines: Loaded[Baseline] = Loaded()
        if inputs.baselines is not None:
            if cfg.baselines is None:
                raise PilotError("baselines file given but the mapping has no 'baselines' section")
            baselines = load_baselines(inputs.baselines, cfg, by_ref)
        manual: Loaded[Allocation] = Loaded()
        if inputs.allocations is not None:
            if cfg.allocations is None:
                raise PilotError(
                    "allocations file given but the mapping has no 'allocations' section"
                )
            manual = load_allocations(inputs.allocations, cfg, by_ref)
    except AgreementFormatError as exc:
        raise PilotError(str(exc)) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise PilotError(f"cannot read input file: {exc}") from None

    for loaded, label in (
        (purchases, "purchases"),
        (credits, "credits"),
        (baselines, "baselines"),
        (manual, "allocations"),
    ):
        _check(loaded, inputs.skip_invalid, label)

    resolutions = _resolutions(inputs.resolutions)
    coverage = _coverage(purchases.items, inputs.coverage_overrides)
    jobs = []
    try:
        for spec in specs:
            jobs.extend(
                plan_agreement(spec.versions, inputs.range_start, inputs.range_end, resolutions)
            )
        results = run_jobs(
            jobs, purchases.items, baselines.items, {k: v[0] for k, v in coverage.items()}
        )
    except EngineInputError as exc:
        raise PilotError(f"agreement problem: {exc}") from None

    issues = [*purchases.issues, *credits.issues, *baselines.issues, *manual.issues]
    spec_by_id = {s.agreement_id: s for s in specs}
    credit_by_id = {c.credit_id: c for c in credits.items}

    # Manual allocations first; credits with any manual allocation are not auto-matched.
    manual_items = [a for a in manual.items if a.credit_id in credit_by_id]
    for a in manual.items:
        if a.credit_id not in credit_by_id:
            issues.append(
                RowIssue(
                    "allocations",
                    0,
                    "credit_reference",
                    a.credit_id,
                    "UNKNOWN_CREDIT",
                    "allocation refers to a credit not in the credits file",
                )
            )
    manually_allocated = {a.credit_id for a in manual_items}
    targets = [
        MatchTarget(
            r.agreement_id, r.supplier_id, spec_by_id[r.agreement_id].external_reference, r.period
        )
        for r in results
    ]
    auto, _ = auto_match(
        [c for c in credits.items if c.credit_id not in manually_allocated], targets
    )
    allocations = [*manual_items, *auto]

    result_keys = {(r.agreement_id, r.period.start, r.period.end) for r in results}
    for a in manual_items:
        if (a.agreement_id, a.period_start, a.period_end) not in result_keys:
            issues.append(
                RowIssue(
                    "allocations",
                    0,
                    "period",
                    f"{a.period_start}..{a.period_end}",
                    "UNKNOWN_PERIOD",
                    f"no calculated period of {a.agreement_id} has exactly these dates",
                    "warning",
                )
            )

    remainders: dict[str, Decimal] = {}
    for credit in credits.items:
        try:
            remainders[credit.credit_id] = allocation_remainder(credit, allocations)
        except EngineInputError as exc:
            raise PilotError(f"allocations for credit {credit.reference}: {exc}") from None

    credit_dates = {c.credit_id: c.credit_date for c in credits.items}
    rows: list[ResultRow] = []
    for r in results:
        item = reconcile_item(
            agreement_id=r.agreement_id,
            period=r.period,
            expected=r.expected,
            engine_needs_review=r.needs_review,
            allocations=allocations,
            credit_dates=credit_dates,
            payment_terms_days=r.payment_terms_days,
            today=inputs.as_of,
            tolerance=cfg.tolerance,
        )
        rows.append(ResultRow(r, spec_by_id[r.agreement_id], item))

    outstanding = [
        Outstanding(
            row.result.agreement_id,
            row.result.supplier_id,
            row.result.period,
            row.recon.expected - row.recon.received,
            row.result.payment_terms_days,
        )
        for row in rows
        if row.recon.expected is not None
    ]
    unmatched = [
        UnmatchedCredit(c, remainders[c.credit_id], tuple(suggest(c, outstanding, cfg.tolerance)))
        for c in credits.items
        if remainders[c.credit_id] != 0
    ]

    counts: dict[str, int] = {s.value: 0 for s in ReconStatus}
    for row in rows:
        counts[row.recon.status.value] += 1
    counts["purchase_rows_read"] = purchases.rows_read
    counts["purchase_lines_used"] = len(purchases.items)
    counts["purchase_duplicates"] = purchases.duplicates
    counts["credit_rows_read"] = credits.rows_read
    counts["credits_used"] = len(credits.items)
    counts["row_errors"] = sum(1 for i in issues if i.severity == "error")
    counts["row_warnings"] = sum(1 for i in issues if i.severity == "warning")
    return PilotOutcome(
        rows,
        unmatched,
        issues,
        coverage,
        counts,
        inputs.as_of,
        inputs.range_start,
        inputs.range_end,
    )
