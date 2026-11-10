"""Loader/runner for golden fixtures in tests/engine/fixtures/*.yaml.

Fixture layout (each file starts with a comment block holding the hand calculation):

    name: ...
    defaults: {...}              # merged under every version (test convenience only)
    agreements: [...]            # pilot agreements format, see docs/pilot-cli.md
    purchases: [{id, supplier, qty, amount, invoice_date?, ship_date?, receipt_date?,
                 sku?, branch?, category?, flags?}]
    baselines: [{agreement, start, end, value}]
    coverage: {SUPPLIER: YYYY-MM-DD}
    range: {start, end}
    resolutions: [{agreement, start, end, choice}]
    expected: [{agreement, period: "start..end", expected, unrounded?, statuses,
                reasons?, S?, Q?, M?, tier_reached?, excluded?, components?}]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from app.engine.calculate import PeriodResult
from app.engine.models import Baseline, PurchaseLine, VersionResolution
from app.engine.planner import PeriodKey, plan_agreement, run_jobs
from app.pilot.agreements import decimal_value, parse_agreements

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class Fixture:
    path: Path
    raw: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.raw.get("name", self.path.stem))


def load_all() -> list[Fixture]:
    return [
        Fixture(p, yaml.safe_load(p.read_text(encoding="utf-8")))
        for p in sorted(FIXTURES.glob("*.yaml"))
    ]


def _d(value: Any) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def purchases(raw: dict[str, Any]) -> list[PurchaseLine]:
    out = []
    for p in raw.get("purchases", []) or []:
        out.append(
            PurchaseLine(
                line_id=str(p["id"]),
                supplier_id=str(p["supplier"]),
                quantity=decimal_value(p.get("qty", "0"), "qty"),
                amount=decimal_value(p["amount"], "amount"),
                sku=None if p.get("sku") is None else str(p["sku"]),
                invoice_date=_d(p.get("invoice_date")),
                ship_date=_d(p.get("ship_date")),
                receipt_date=_d(p.get("receipt_date")),
                branch=p.get("branch"),
                category=p.get("category"),
                flags=PurchaseLine.make_flags(p.get("flags", {}) or {}),
            )
        )
    return out


def run_fixture(fx: Fixture) -> list[PeriodResult]:
    raw = fx.raw
    defaults = raw.get("defaults", {}) or {}
    doc = {
        "agreements": [
            {**a, "versions": [{**defaults, **v} for v in a["versions"]]} for a in raw["agreements"]
        ]
    }
    specs = parse_agreements(doc)
    lines = purchases(raw)
    baselines = [
        Baseline(
            str(b["agreement"]),
            _d(b["start"]),  # type: ignore[arg-type]
            _d(b["end"]),  # type: ignore[arg-type]
            decimal_value(b["value"], "baseline"),
            f"B:{b['agreement']}:{b['start']}:{b['value']}",
        )
        for b in raw.get("baselines", []) or []
    ]
    coverage = {str(k): _d(v) for k, v in (raw.get("coverage", {}) or {}).items()}
    resolutions: dict[PeriodKey, VersionResolution] = {
        (str(r["agreement"]), _d(r["start"]), _d(r["end"])): VersionResolution(r["choice"])  # type: ignore[misc]
        for r in raw.get("resolutions", []) or []
    }
    rng = raw["range"]
    jobs = []
    for spec in specs:
        jobs.extend(
            plan_agreement(spec.versions, _d(rng["start"]), _d(rng["end"]), resolutions)  # type: ignore[arg-type]
        )
    return run_jobs(jobs, lines, baselines, coverage)  # type: ignore[arg-type]


def period_key(result: PeriodResult) -> str:
    return f"{result.period.start}..{result.period.end}"


def _dec_or_none(value: Any) -> Decimal | None:
    return None if value is None else decimal_value(value, "expected")


def check(fx: Fixture, results: list[PeriodResult]) -> list[str]:
    """Return a list of mismatch descriptions (empty means pass)."""
    problems: list[str] = []
    expected = fx.raw["expected"]
    by_key = {(r.agreement_id, period_key(r)): r for r in results}
    if len(by_key) != len(results):
        problems.append("duplicate result keys")
    wanted_keys = {(str(e["agreement"]), str(e["period"])) for e in expected}
    extra = set(by_key) - wanted_keys
    if extra:
        problems.append(f"unexpected results: {sorted(extra)}")
    for e in expected:
        key = (str(e["agreement"]), str(e["period"]))
        r = by_key.get(key)
        if r is None:
            problems.append(f"missing result {key}")
            continue
        want = _dec_or_none(e["expected"])
        if r.expected != want or (want is not None and str(r.expected) != str(want)):
            problems.append(f"{key} expected {want} got {r.expected}")
        if "unrounded" in e and r.expected_unrounded != _dec_or_none(e["unrounded"]):
            problems.append(f"{key} unrounded {e['unrounded']} got {r.expected_unrounded}")
        got_status = sorted(s.value for s in r.statuses)
        if got_status != sorted(e["statuses"]):
            problems.append(f"{key} statuses {sorted(e['statuses'])} got {got_status}")
        got_reasons = sorted(x.code for x in r.reasons)
        if sorted(e.get("reasons", [])) != got_reasons:
            problems.append(f"{key} reasons {sorted(e.get('reasons', []))} got {got_reasons}")
        for field, attr in (("S", "spend"), ("Q", "quantity"), ("M", "measure")):
            if field in e and getattr(r, attr) != decimal_value(e[field], field):
                problems.append(f"{key} {field} {e[field]} got {getattr(r, attr)}")
        if "tier_reached" in e and r.tier_reached != e["tier_reached"]:
            problems.append(f"{key} tier {e['tier_reached']} got {r.tier_reached}")
        if "excluded" in e and dict(r.excluded_counts) != e["excluded"]:
            problems.append(f"{key} excluded {e['excluded']} got {dict(r.excluded_counts)}")
        if "eligible" in e and r.eligible_count != e["eligible"]:
            problems.append(f"{key} eligible {e['eligible']} got {r.eligible_count}")
        for cid, cval in (e.get("components") or {}).items():
            comp = next((c for c in r.components if c.component_id == cid), None)
            if comp is None or comp.value != _dec_or_none(cval):
                problems.append(f"{key} component {cid} {cval} got {comp and comp.value}")
    return problems
