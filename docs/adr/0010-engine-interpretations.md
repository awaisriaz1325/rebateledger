# ADR 0010 — Engine interpretations where SPEC §4.4 is silent

Status: accepted for v1 — each item is listed in the Phase 1 report for founder review

Where the spec does not define behaviour, the engine either makes the rule an
explicit agreement field (no hidden default) or returns `NEEDS_REVIEW`.

| Topic | Decision | Why |
|---|---|---|
| `spend_basis` | Affects only `M`. `S`/`Q` are always net of returns (their §3 definitions). `gross` drops return lines (negative amount/qty) from `M`. | §4.4.1 says "does a return reduce M?" |
| Corresponding prior period | New explicit field `prior_period_offset`: `same_period_prior_year` or `immediately_preceding` (required for computed baselines). | §4.4.2 doesn't define "corresponding" |
| Computed baseline data completeness | Baseline is `BASELINE_MISSING` if its period starts before the supplier's known data-coverage start. | Can't tell "no purchases" from "not imported" |
| Growth component in a partial/split period | `NEEDS_REVIEW` `GROWTH_PARTIAL_PERIOD`. | Comparing a partial measure to a full baseline is a business decision |
| Negative baseline | `NEEDS_REVIEW` `BASELINE_NEGATIVE`. | Growth % is meaningless |
| Two different imported baselines for one period | `NEEDS_REVIEW` `BASELINE_AMBIGUOUS`. | Never pick one silently |
| Minimum payout vs clawback | `NEEDS_REVIEW` `CLAWBACK_WITH_MINIMUM`. | §4.4.2 step 8 would erase a clawback |
| `BELOW_MINIMUM` | Only when 0 < result < minimum; a zero result is `NOT_EARNED`. | Distinguishes "earned too little" from "earned nothing" |
| `min_line_amount` | Compares the absolute line amount, so returns of qualifying purchases still net. | Otherwise every return would be excluded |
| Stacking conflict | Flagged when a line is eligible for two agreements of the same supplier and **at least one** is exclusive. | Exclusive means "may not count elsewhere" |
| Expected amount when NEEDS_REVIEW | `null` (no number shown); trace still lists what was computed. | Never show a number that may be wrong |
| Threshold proration | `threshold × measured days / full-period days` (full precision). | §4.4.4 |
| Due date for split/clipped periods | End of the measured window + payment terms. | Credits for the old terms are due after its window |
| `C < 0` past due (net reversals) | `SHORT_PAID` with `REVERSAL` flag. | §4.7.2 table has no row for it |
| Fiscal period labels | `FY{year the fiscal year ends}-Q{n}`; calendar years plain `2026-Q1`. | Common US usage |
| Precision | 60-significant-digit local Decimal context; growth test uses `M ⋛ B×(1+g)` (no division). | Exact for NUMERIC(18,4)/(9,6) inputs |
