# RebateLedger v1.1 — feature phases (PLAN, awaiting founder approval)

Source: competitor and market research of 2026-11-13 (summary in `docs/research/2026-11-market.md`).
Founder instruction: "build all". Same rules as `docs/PHASES.md`: one phase at a time, full
check suite green, end-of-phase report, stop and ask before the next phase.

Phase 11 (deployment) stays open and waits for the hosting answer. These phases do not
depend on it and do not touch infrastructure.

| Phase | Feature | SPEC change | Engine change | Size |
|---|---|---|---|---|
| 12 | ERP import template packs | §4.5 addition | No | S |
| 13 | Deal modelling (what-if before signing) | §4.4 addition | No (reuses preview) | M |
| 14 | Weekly buyer digest + cross-supplier opportunity ranking | §4.9, §4.11 additions | No | S |
| 15 | Month-end accrual journal export (file, not GL posting) | §4.9, §4.10 additions; §14 wording clarified | No | M |
| 16 | Buying-group programs (multi-supplier agreements) | §4.3, §4.4, §5 | **Yes** (engine version bump) | L |
| 17 | Ship-and-debit / SPA claims (sales-line imports) | New §4.17, §5, §9 | New pure module beside the engine | XL |

Order: smallest and lowest-risk first; each phase ships on its own.

---

## Phase 12 — ERP import template packs

**Goal:** a customer picks their ERP and report, and the column mapping is already done.

**Do:**
1. `backend/app/import_presets/` — versioned, read-only preset definitions (YAML in the
   repo, validated by a Pydantic model at startup) for purchase-line and credit reports of:
   Epicor Prophet 21, Epicor Eclipse, Infor SX.e / CloudSuite Distribution, NetSuite,
   Acumatica, QuickBooks Online / Desktop, plus "Generic CSV".
2. Each preset: header aliases per field, date and number formats, sign convention for
   returns and credit memos, which columns to ignore. No code per ERP.
3. Upload flow: header fingerprinting suggests a preset ("Looks like a Prophet 21 purchase
   history report") — the user confirms; nothing is auto-applied silently.
4. "Copy preset to my templates" so a customer can adjust it; edits never change the preset.
5. UI: preset picker on the mapping step; settings page lists presets with the source
   report name and a download of the expected header row.

**Tests:** preset schema validation; a synthetic sample file per preset imports with zero
mapping changes; fingerprint picks the right preset and refuses to guess on ties;
authorization matrix for new endpoints; E2E: upload a P21-shaped file, accept suggestion.

**Risks:** no public vendor documentation of these report layouts was found and the
reports are customisable, so header names are best guesses with several aliases per field → every preset is marked **UNVERIFIED** in the UI until a
pilot customer's real file confirms it.

## Phase 13 — Deal modelling

**Goal:** before signing, compare proposed terms against real past purchases.

**Do:**
1. "Scenario" = up to 4 draft term sets for one supplier (reuses the agreement terms
   schema and validation; never activatable; separate table `deal_scenarios`).
2. Evaluate each against a chosen historical window using the existing preview path
   (pure engine, no persistence of results beyond the scenario cache).
3. Side-by-side: expected rebate per period, effective rate, tier reached, spend needed for
   the next tier, and sensitivity (+/-10% and +/-20% spend), all labelled **estimate**.
4. "Turn into agreement draft" copies the chosen terms into a normal draft version.
5. PDF/CSV export of the comparison (existing export pipeline, formula-safe).

**Tests:** scenario totals equal a real run over the same lines (golden check);
sensitivity is computed by scaling input lines, not by extrapolating results; limits
(4 scenarios, window ≤ 24 months); cross-tenant tests; E2E journey + axe.

## Phase 14 — Weekly buyer digest

**Goal:** buyers see every week where extra purchases unlock more rebate.

**Do:**
1. Opportunity ranking across all open periods: gap to next tier, extra rebate if reached
   (incremental, including retroactive tiers), days left, required daily run-rate vs the
   current one; ranked by extra rebate per dollar of extra spend.
2. New role-neutral notification type `weekly_digest` (opt-in per user, default on for
   buyers and managers; unsubscribe link; existing notification preferences).
3. Scheduled job, Mondays 07:00 in the organization's time zone; idempotent per user/week.
4. Dashboard card "Top opportunities" using the same service.

**Tests:** ranking order on fixtures; retroactive vs incremental tiers; no email when
nothing qualifies; idempotency; unsubscribe; email contains no raw purchase rows.

## Phase 15 — Month-end accrual journal export

**Goal:** finance imports the month's rebate accrual into their own ledger.

**Do:**
1. Settings: GL account codes (rebate receivable; offset account) per organization with
   optional per-supplier override; journal format (generic CSV, QuickBooks IIF/CSV,
   NetSuite CSV, Sage Intacct CSV — templates only, no API).
2. Journal for a closing date: one line pair per agreement period, amount = accrued to date
   at the current tier (existing accrual service), method per founder decision below.
3. Lock: an exported month is recorded (who, when, hash of file); re-export shows a diff.
4. Clear labels: **estimate**, "data as of", and a reviewer sign-off before export.
5. SPEC §14 wording: "general-ledger posting" stays out of scope; a downloadable file is not
   posting.

**Tests:** journal balances (debits = credits) to the cent; Decimal only; reversing vs
incremental method on fixtures; lock and diff; formula-injection safe; cross-tenant.

**Risks:** accounting treatment (ASC 705-20: vendor consideration reduces inventory cost
until the goods are sold, then cost of sales) — the export must not claim compliance.
Accountant review required before marketing it.

## Phase 16 — Buying-group programs

**Goal:** track rebates a buying group pays on purchases across many member suppliers.

**Do:**
1. New entity `payer` on agreements: supplier (today) or buying group. Buying groups are
   tenant-scoped records with a list of participating suppliers.
2. Engine: eligibility accepts a set of supplier ids for group agreements. Engine version
   bump; all existing golden fixtures must produce byte-identical output; new golden
   fixtures for group programs; property test: group with one supplier ≡ supplier agreement.
3. Credits and claims can be from the group (payer), matched to group agreements only.
4. Stacking: a line may count toward a supplier agreement and a group program at once
   (founder decision below).
5. UI: buying groups page; agreement form "Paid by"; results and reports group by payer.

**Tests:** golden fixtures (hand-worked); engine coverage stays ≥ 95%; reconciliation of
group credits; cross-tenant; migration on large tables reviewed for locking.

## Phase 17 — Ship-and-debit / SPA claims

**Goal:** for electrical, HVAC and plumbing distributors, find every SPA claim not yet
paid.

**Do:**
1. New import type **sales lines** (invoice no., date, customer, job/project, SKU, qty,
   sell price, cost at time of sale) with the same pipeline (validation, dedupe, void).
2. SPA records: supplier, SPA number, customer and/or job, SKU list with book (into-stock)
   cost and SPA net cost, quantity cap, valid from/to, claim deadline.
3. Pure, deterministic matcher module `backend/app/engine/spa.py`: sales line × SPA →
   claimable amount = (book cost − SPA cost) × qty, within dates and caps; ambiguous
   matches (two SPAs, missing customer, cost mismatch) → `NEEDS_REVIEW` with reason.
4. Reconciliation against supplier SPA credits; discrepancies and claims reuse Phase 4/7
   flows; evidence pack lists the matched sales lines.
5. Deadline alerts for unclaimed lines near the claim deadline.

**Tests:** golden fixtures; property tests (cap never exceeded, deterministic order);
coverage ≥ 95% for the matcher; 1M sales lines load test; cross-tenant; E2E + axe.

**Risks:** new data type with customer data (customer names, prices) → data-protection
review, retention and export coverage; largest phase; real SPA documents from a pilot
customer are needed to validate.

---

## Decisions needed before Phase 12 starts
See the questions asked on 2026-11-13 (recorded in ADR 0017 once answered).
