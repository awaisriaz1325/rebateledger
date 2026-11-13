# Pilot CLI — reconcile rebates from files

The pilot CLI runs the production rebate engine on a customer's exports so you
can deliver paid concierge pilots before the web app is live. Nothing leaves your
machine; there is no database, network access or AI involved.

```bash
cd backend
uv run rebateledger pilot \
  --agreements ../docs/pilot-samples/agreements.yaml \
  --purchases  ../docs/pilot-samples/purchases.csv \
  --credits    ../docs/pilot-samples/credits.csv \
  --mapping    ../docs/pilot-samples/mapping.yaml \
  --baselines  ../docs/pilot-samples/baselines.csv \
  --allocations ../docs/pilot-samples/allocations.csv \
  --resolutions ../docs/pilot-samples/resolutions.yaml \
  --from 2026-01-01 --to 2026-06-30 --as-of 2026-09-15 \
  --out ../var/pilot-sample
```
(`make pilot-sample` runs exactly this.)

| Option | Meaning |
|---|---|
| `--from/--to` | Every agreement period that overlaps this range is calculated (whole periods) |
| `--as-of` | The date statuses are judged on, **in the customer's timezone** (PENDING through the due date, SHORT_PAID/MISSING after) |
| `--baselines` | Imported baselines for growth agreements |
| `--allocations` | Manual credit allocations (split one credit across periods) |
| `--resolutions` | Decisions for periods where an agreement's terms changed mid-period |
| `--coverage-start SUPPLIER=DATE` | Purchase data for that supplier is complete from DATE (repeatable). Default: earliest date in the file, printed in the summary |
| `--skip-invalid` | Skip rows with errors instead of stopping (they are listed in `issues.csv`) |

## Outputs (in `--out`)

| File | Contents |
|---|---|
| `results.csv` | One row per agreement-period: expected (rounded + unrounded), S/Q/M, tier, received, variance, tolerance, reconciliation status, due date, review reasons, input hash, engine version |
| `discrepancies.csv` | Short-paid, missing, overpaid and needs-review rows with the next action |
| `unmatched_credits.csv` | Credits not (fully) allocated, with suggestions (never auto-applied) |
| `issues.csv` | Row errors and warnings from the input files |
| `report.html` | Human-readable report with every calculation trace |

All CSV cells starting with `=`, `+`, `-`, `@`, tab or CR are prefixed with `'`
(spreadsheet formula-injection protection), so negative amounts appear as `'-4629.78`.

## Agreements YAML format

Every field that changes money must be written explicitly; there are no hidden
defaults. **Decimals must be quoted** (`rate: "0.02"`): an unquoted `0.02` is a
binary float in YAML and is rejected.

```yaml
agreements:
  - id: ACME-VOL                     # your id for the agreement (unique)
    supplier: ACME-ELEC              # supplier code exactly as in the purchases file
    # members: [ACME-ELEC, BETA-ELEC] # optional: buying-group program; 'supplier' is then the group
    name: ACME Electrical 2026 volume rebate
    external_reference: ACME-VOL-2026   # what the supplier writes on credit memos
    versions:
      - version_no: 1
        effective_from: 2026-01-01
        effective_to: 2026-12-31     # or null
        period: {type: quarterly, fiscal_year_start_month: 1}  # monthly|quarterly|semiannual|annual|custom
        date_basis: invoice_date     # invoice_date | ship_date | receipt_date
        measure: spend               # spend | quantity — what tiers are tested against
        spend_basis: net_of_returns  # net_of_returns | gross — do returns reduce M?
        threshold_comparison: gte    # gte | gt
        negative_result: floor_at_zero   # floor_at_zero | allow_clawback
        rounding_mode: half_up       # half_up | half_even (always 2 dp, once, at the end)
        payment_terms_days: 45       # credit expected within N days after period end
        stacking: exclusive          # exclusive | stackable
        prorate_thresholds_on_partial_period: false
        zero_baseline_policy: needs_review   # needs_review | qualifies | does_not_qualify
        cap_amount: "50000"          # optional
        minimum_payout: "100"        # optional
        eligibility:                 # optional; exclude wins over include
          - {id: no-spa, action: exclude, field: flag, flag: special_pricing}
          - {action: include, field: category, values: [WIRE, BREAKER]}
          - {action: include, field: min_line_amount, min_amount: "50"}
        components:                  # summed
          - id: volume
            type: tiered_all_units
            tiers:
              - {threshold: "250000", rate: "0.02"}
              - {threshold: "500000", rate: "0.03"}
```

Custom periods: `period: {type: custom, fiscal_year_start_month: 1, custom_periods: [{start: 2026-01-01, end: 2026-02-14, label: P1}, …]}`.

### Component types

| `type` | Fields | Pays |
|---|---|---|
| `flat_percent` | `rate` | `rate × S` |
| `per_unit` | `amount_per_unit` | `amount_per_unit × Q` |
| `tiered_all_units` | `tiers[{threshold, rate \| amount_per_unit}]` | highest tier met: its rate × S (or amount × Q) on **all** volume |
| `tiered_incremental` | same | each tier's rate on the part of M inside its band; rate tiers need `measure: spend`, per-unit tiers need `measure: quantity` |
| `growth_incremental` | `rate`, `baseline_source` | `rate × max(0, M − B)` |
| `growth_threshold` | `rate`, `growth_pct`, `baseline_source` | `rate × S` if `M ÷ B − 1` meets `growth_pct` |
| `fixed_bonus` | `amount`, `threshold` | `amount` if M meets `threshold` |

`baseline_source: imported` reads `--baselines`; `prior_period_computed` measures
the same eligibility over an earlier period and **also needs**
`prior_period_offset: same_period_prior_year | immediately_preceding`.

### Mapping file

`mapping.yaml` names the columns of each CSV and the formats used. Dates are never
guessed — `date_format` is required (`YYYY-MM-DD`, `MM/DD/YYYY`, `DD/MM/YYYY`,
`M/D/YY`, `D/M/YY`, `DD.MM.YYYY`, `YYYYMMDD`, `DD-MMM-YYYY`, `MM-DD-YYYY`).
Number formats: `decimal_separator`, `thousands_separator`, `negative_style`
(`minus`, `parentheses`, `trailing_minus`), `currency_symbols`, and for credits
`credit_sign: positive | negative` (negative means credits are written as negative
numbers in the file). See `docs/pilot-samples/mapping.yaml`.

Purchase rows: required `supplier_code, sku, quantity, amount, invoice_number`
and at least one date; optional `line_number, unit_price, ship_date, receipt_date,
branch, category, currency` and boolean `flags`. Duplicate rows (same supplier,
invoice and line number) are skipped and reported. Non-USD rows are errors.

Credit rows: required `supplier_code, credit_date, amount, credit_reference`;
optional `agreement_reference` and `period_start/period_end` or `period_label`
(`Q1 2026`, `2026-Q1`, `2026-03`, `2026-H1`, `FY2027-Q2`…). A credit is
**auto-matched** only when it has an agreement reference AND a period that maps
to exactly one agreement-period.

## Worked example 1 — tiered volume rebate (ACME, Q1 2026)

Trace from `report.html` (agreement ACME-VOL, 2026-01-01 – 2026-03-31):

| Step | Value |
|---|---|
| 1. Lines with invoice date in Q1 | 252 |
| 2. Eligibility | 228 eligible; 24 excluded by rule `no-spa` (special pricing) |
| 3. Measures | S = 623,582.16 ; M = 623,582.16 |
| 4. Tiers | M ≥ 500,000 → tier 2 (3%), all-units: 0.03 × 623,582.16 = 18,707.4648 |
| 5–8 | no clawback, no cap, no minimum → 18,707.4648 |
| 9. Round half-up | **18,707.46** |

**Reproduce by hand:** open `purchases.csv` in a spreadsheet, filter
`Vendor No = ACME-ELEC`, `Invoice Date` between 01/01/2026 and 03/31/2026 and
`SPA = N`, sum `Ext Cost` → 623,582.16. It is ≥ 500,000, so multiply by 0.03 →
18,707.4648 → 18,707.46. Credit memo `ACM-CM-10421` (18,707.46, program
ACME-VOL-2026, period "Q1 2026") auto-matches → **MATCHED**.

## Worked example 2 — growth program with a cap (CoolAir, Q1 2026)

| Step | Value |
|---|---|
| 1–3 | 297 lines by **ship date**, all eligible; S = M = 877,079.44 |
| 4. base | 0.01 × 877,079.44 = 8,770.7944 |
| 4. growth | baseline B = 790,000.00 (imported); 0.04 × (877,079.44 − 790,000.00) = 3,483.1776 |
| 5. Sum | 12,253.9720 |
| 7. Cap 40,000 | not reached |
| 9. Round | **12,253.97** |

No credit was allocated and the due date (Mar 31 + 90 days = Jun 29) has passed →
**MISSING**. `unmatched_credits.csv` suggests credit `CA-CM-2290` (12,250.00, no
program reference) for this period because it is within tolerance
(max($1.00, 0.5% × 12,253.97) = 61.27) and dated inside the payment window. You
confirm it by adding a line to `allocations.csv`.

## Worked example 3 — per-unit rebate with a mid-quarter change (PipeWorks, Q2)

Version 1 ($0.15/unit, $1,000 bonus) ends Apr 30; version 2 ($0.18/unit, $1,500
bonus) starts May 1. Without a decision, Q2 is **NEEDS_REVIEW
`VERSION_CHANGE_IN_PERIOD`** (the engine never picks a version). With
`resolutions.yaml` choosing `split`, Q2 becomes two partial periods. For
May 1 – Jun 30 (61 of 91 days, thresholds prorated because the agreement says so):

| Step | Value |
|---|---|
| 2. Eligibility | 91 PEX lines eligible; 86 other categories `NOT_INCLUDED` |
| 3. Measure | Q = M = 7,245 units |
| 4. per-unit | 0.18 × 7,245 = 1,304.10 |
| 4. bonus | threshold 10,000 × 61/91 = 6,703.30; M = 7,245 ≥ 6,703.30 → 1,500 |
| 9. Round half-even | **2,804.10** |

## Where the engine asks a human (NEEDS_REVIEW)

| Reason | When | Ask the customer |
|---|---|---|
| `VERSION_CHANGE_IN_PERIOD` | Terms change inside a period | Apply old terms, new terms, or split at the change date? |
| `BASELINE_MISSING` | No imported baseline, or purchase history too short | What is the baseline for this period? |
| `BASELINE_ZERO` | Baseline is 0 and policy is needs_review | Does any purchase count as growth when last year was zero? |
| `BASELINE_NEGATIVE` / `BASELINE_AMBIGUOUS` | Bad or conflicting baselines | Which baseline is correct? |
| `GROWTH_PARTIAL_PERIOD` | Growth component in a partial period | How should a partial period be compared to a full baseline? |
| `STACKING_CONFLICT` | A line qualifies for two agreements of the same supplier and one is exclusive | Which program does this purchase count toward? |
| `CLAWBACK_WITH_MINIMUM` | Negative result with a minimum payout | Does the minimum apply to clawbacks? |
