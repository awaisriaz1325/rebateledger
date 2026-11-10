"""Pilot outputs: results.csv, discrepancies.csv, unmatched_credits.csv, issues.csv,
report.html and a terminal summary. All CSVs are formula-injection safe."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, select_autoescape

from app.core.csv_safe import write_csv
from app.engine.reconcile import ReconStatus
from app.pilot.run import DISCREPANCY_STATUSES, PilotOutcome, ResultRow

RESULT_HEADER = [
    "agreement_id",
    "agreement_name",
    "external_reference",
    "supplier",
    "version_no",
    "period_start",
    "period_end",
    "engine_statuses",
    "expected",
    "expected_unrounded",
    "eligible_spend_S",
    "eligible_quantity_Q",
    "measure_M",
    "tier_reached",
    "eligible_lines",
    "excluded_lines",
    "received",
    "variance",
    "tolerance",
    "recon_status",
    "due_date",
    "flags",
    "review_reasons",
    "input_hash",
    "engine_version",
]


def _s(value: Decimal | int | None) -> str:
    return "" if value is None else str(value)


def _result_cells(row: ResultRow) -> list[object]:
    r, rc = row.result, row.recon
    return [
        r.agreement_id,
        row.agreement.name,
        row.agreement.external_reference or "",
        r.supplier_id,
        r.version_no,
        r.period.start,
        r.period.end,
        " ".join(s.value for s in r.statuses),
        _s(r.expected),
        _s(r.expected_unrounded),
        r.spend,
        r.quantity,
        r.measure,
        _s(r.tier_reached),
        r.eligible_count,
        sum(n for _, n in r.excluded_counts),
        rc.received,
        _s(rc.variance),
        _s(rc.tolerance),
        rc.status.value,
        rc.due_date,
        " ".join(f.value for f in rc.flags),
        " | ".join(f"{x.code}: {x.message}" for x in r.reasons),
        r.input_hash,
        r.engine_version,
    ]


def write_outputs(outcome: PilotOutcome, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def csv_file(name: str, header: list[str], rows: Iterable[list[object]]) -> None:
        path = out_dir / name
        with path.open("w", encoding="utf-8", newline="") as fh:
            write_csv(fh, header, rows)
        written.append(path)

    csv_file("results.csv", RESULT_HEADER, (_result_cells(r) for r in outcome.rows))
    discrepancies = [
        r
        for r in outcome.rows
        if r.recon.status in (*DISCREPANCY_STATUSES, ReconStatus.NEEDS_REVIEW)
    ]
    csv_file(
        "discrepancies.csv",
        ["type", "action", *RESULT_HEADER],
        (
            [
                r.recon.status.value,
                "Decide the open question, then re-run"
                if r.recon.status is ReconStatus.NEEDS_REVIEW
                else "Raise a claim with the supplier"
                if r.recon.status is not ReconStatus.OVERPAID
                else "Confirm with the supplier; may be repayable",
                *_result_cells(r),
            ]
            for r in discrepancies
        ),
    )
    csv_file(
        "unmatched_credits.csv",
        [
            "supplier",
            "credit_reference",
            "credit_date",
            "amount",
            "unallocated",
            "agreement_reference",
            "suggestions",
        ],
        (
            [
                u.credit.supplier_id,
                u.credit.reference,
                u.credit.credit_date,
                u.credit.amount,
                u.remainder,
                u.credit.agreement_reference or "",
                " | ".join(
                    f"{s.agreement_id} {s.period_start}..{s.period_end}: {s.explanation}"
                    for s in u.suggestions
                ),
            ]
            for u in outcome.unmatched
        ),
    )
    csv_file(
        "issues.csv",
        ["file", "row", "column", "value", "severity", "code", "message"],
        ([i.file, i.row, i.column, i.value, i.severity, i.code, i.message] for i in outcome.issues),
    )
    html = out_dir / "report.html"
    html.write_text(render_html(outcome), encoding="utf-8")
    written.append(html)
    return written


def totals(outcome: PilotOutcome) -> dict[str, Decimal]:
    zero = Decimal("0.00")
    t = {"expected": zero, "received": zero, "short_or_missing": zero, "overpaid": zero}
    for r in outcome.rows:
        rc = r.recon
        t["received"] += rc.received
        if rc.expected is not None:
            t["expected"] += rc.expected
        if rc.status in (ReconStatus.SHORT_PAID, ReconStatus.MISSING) and rc.variance is not None:
            t["short_or_missing"] += -rc.variance
        if rc.status is ReconStatus.OVERPAID and rc.variance is not None:
            t["overpaid"] += rc.variance
    return t


def summary_text(outcome: PilotOutcome) -> str:
    t = totals(outcome)
    c = outcome.counts
    lines = [
        f"RebateLedger pilot run — periods {outcome.range_start}..{outcome.range_end}, as of {outcome.as_of}, engine {outcome.engine_version}",
        f"Inputs: {c['purchase_lines_used']}/{c['purchase_rows_read']} purchase rows used "
        f"({c['purchase_duplicates']} duplicates), {c['credits_used']}/{c['credit_rows_read']} credits, "
        f"{c['row_errors']} row errors, {c['row_warnings']} warnings",
        f"Agreement-periods: {len(outcome.rows)}",
    ]
    for status in ReconStatus:
        if c.get(status.value):
            lines.append(f"  {status.value:<13} {c[status.value]}")
    lines += [
        f"Expected (excl. needs-review): ${t['expected']:,}",
        f"Received (allocated):          ${t['received']:,}",
        f"Short-paid + missing (identified, NOT recovered): ${t['short_or_missing']:,}",
        f"Overpaid:                      ${t['overpaid']:,}",
        f"Unmatched credits: {len(outcome.unmatched)}",
    ]
    for supplier, (d, source) in sorted(outcome.coverage.items()):
        lines.append(f"Purchase data for {supplier} treated as complete from {d} ({source}).")
    return "\n".join(lines)


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RebateLedger pilot report {{ o.range_start }} – {{ o.range_end }}</title>
<style>
:root{--ink:#14211c;--muted:#5b6b64;--line:#d9e0dc;--bg:#fbfcfb;--card:#fff;--bad:#a12c1f;--ok:#1d6b45;--warn:#8a5a00}
body{font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);background:var(--bg);margin:0;padding:24px;max-width:1200px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 8px}h3{font-size:15px;margin:0}
.muted{color:var(--muted)}table{border-collapse:collapse;width:100%;background:var(--card)}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin:12px 0}
.badge{display:inline-block;border:1px solid currentColor;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.SHORT_PAID,.MISSING,.NEEDS_REVIEW{color:var(--bad)}.MATCHED,.NOT_EARNED{color:var(--ok)}.OVERPAID,.PENDING{color:var(--warn)}
code{font-size:12px;word-break:break-all}details summary{cursor:pointer;font-weight:600}
.notice{border-left:4px solid var(--warn);padding:8px 12px;background:#fff8e6}
</style></head><body>
<h1>Rebate reconciliation — pilot report</h1>
<p class="muted">Periods {{ o.range_start }} to {{ o.range_end }} · statuses as of {{ o.as_of }} · engine {{ o.engine_version }}</p>
<p class="notice">Amounts marked short-paid or missing are <strong>identified</strong>, not recovered. Each figure below can be recomputed by hand from its trace.</p>
<h2>Summary</h2>
<table><tbody>
<tr><th>Expected (excluding needs-review)</th><td class="num">${{ "{:,}".format(t.expected) }}</td></tr>
<tr><th>Received (allocated credits)</th><td class="num">${{ "{:,}".format(t.received) }}</td></tr>
<tr><th>Short-paid + missing</th><td class="num">${{ "{:,}".format(t.short_or_missing) }}</td></tr>
<tr><th>Overpaid</th><td class="num">${{ "{:,}".format(t.overpaid) }}</td></tr>
<tr><th>Unmatched credits</th><td class="num">{{ o.unmatched|length }}</td></tr>
<tr><th>Row errors / warnings</th><td class="num">{{ o.counts.row_errors }} / {{ o.counts.row_warnings }}</td></tr>
</tbody></table>
{% if o.coverage %}<p class="muted">{% for s, c in o.coverage|dictsort %}Purchase data for {{ s }} treated as complete from {{ c[0] }} ({{ c[1] }}). {% endfor %}</p>{% endif %}
<h2>Agreement-periods</h2>
<table><thead><tr><th>Agreement</th><th>Period</th><th class="num">Expected</th><th class="num">Received</th><th class="num">Variance</th><th>Status</th><th>Due</th></tr></thead><tbody>
{% for row in o.rows %}<tr>
<td><a href="#r{{ loop.index }}">{{ row.agreement.name }}</a><br><span class="muted">{{ row.result.agreement_id }} · v{{ row.result.version_no }} · {{ row.result.supplier_id }}</span></td>
<td>{{ row.result.period.start }} – {{ row.result.period.end }}</td>
<td class="num">{{ row.result.expected if row.result.expected is not none else "—" }}</td>
<td class="num">{{ row.recon.received }}</td>
<td class="num">{{ row.recon.variance if row.recon.variance is not none else "—" }}</td>
<td><span class="badge {{ row.recon.status.value }}">{{ row.recon.status.value }}</span></td>
<td>{{ row.recon.due_date }}</td></tr>{% endfor %}
</tbody></table>
<h2>Traces</h2>
{% for row in o.rows %}{% set r = row.result %}
<section class="card" id="r{{ loop.index }}">
<h3>{{ row.agreement.name }} — {{ r.period.start }} to {{ r.period.end }}</h3>
<p class="muted">Statuses: {{ r.statuses|map(attribute="value")|join(", ") }} · reconciliation <span class="badge {{ row.recon.status.value }}">{{ row.recon.status.value }}</span>{% for f in row.recon.flags %} · {{ f.value }}{% endfor %}</p>
{% if r.reasons %}<ul>{% for x in r.reasons %}<li><strong>{{ x.code }}</strong>: {{ x.message }}</li>{% endfor %}</ul>{% endif %}
<table><thead><tr><th>Step</th><th>What happened</th><th>Values</th></tr></thead><tbody>
{% for s in r.trace %}<tr><td>{{ s.step }}. {{ s.name }}</td><td>{{ s.description }}</td><td>{% for k, v in s.values %}<div><code>{{ k }} = {{ v }}</code></div>{% endfor %}</td></tr>{% endfor %}
</tbody></table>
<p class="muted">Received {{ row.recon.received }}{% if row.recon.tolerance is not none %} · tolerance {{ row.recon.tolerance }}{% endif %} · due {{ row.recon.due_date }} · input hash <code>{{ r.input_hash }}</code></p>
</section>{% endfor %}
{% if o.unmatched %}<h2>Unmatched credits</h2>
<table><thead><tr><th>Supplier</th><th>Reference</th><th>Date</th><th class="num">Amount</th><th class="num">Unallocated</th><th>Suggestions (never auto-applied)</th></tr></thead><tbody>
{% for u in o.unmatched %}<tr><td>{{ u.credit.supplier_id }}</td><td>{{ u.credit.reference }}</td><td>{{ u.credit.credit_date }}</td><td class="num">{{ u.credit.amount }}</td><td class="num">{{ u.remainder }}</td>
<td>{% for s in u.suggestions %}<div>{{ s.agreement_id }} {{ s.period_start }}–{{ s.period_end }}: {{ s.explanation }}</div>{% else %}—{% endfor %}</td></tr>{% endfor %}
</tbody></table>{% endif %}
{% if o.issues %}<h2>Input issues</h2><details><summary>{{ o.issues|length }} issue(s)</summary>
<table><thead><tr><th>File</th><th>Row</th><th>Column</th><th>Severity</th><th>Code</th><th>Message</th></tr></thead><tbody>
{% for i in o.issues %}<tr><td>{{ i.file }}</td><td>{{ i.row }}</td><td>{{ i.column }}</td><td>{{ i.severity }}</td><td>{{ i.code }}</td><td>{{ i.message }}</td></tr>{% endfor %}
</tbody></table></details>{% endif %}
</body></html>
"""


def render_html(outcome: PilotOutcome) -> str:
    env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
    return env.from_string(_TEMPLATE).render(o=outcome, t=totals(outcome))
