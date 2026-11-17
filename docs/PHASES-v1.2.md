# RebateLedger v1.2: feature phases (PLAN, awaiting founder approval)

Source: `docs/research/2026-11-17-feature-review.md` (§5 recommendations, §6 Top 5).
Same rules as `docs/PHASES.md`:
- one phase at a time
- the full check suite must be green
- each phase ends with the end-of-phase report, then I stop and ask before the next phase

Phase 11 (production deploy) stays open and waits for domains and the email provider. These
phases do not touch infrastructure. Nothing here adds a paid service.

| Phase | Feature | SPEC change | Engine change | Size | Blocked by |
|---|---|---|---|---|---|
| 18 | Positioning and focus: ERP-migration page, SPA labelled beta, deal modelling moved under Agreements | §4.16, §10 | No | S | — |
| 19 | Accrual export formats: NetSuite and Acumatica journal import | §4.9 addition | No | S | — |
| 20 | Look-back recovery audit | New §4.18 | No (reuses runs) | M | Decision D1 |
| 21 | Bulk agreement import (CSV → Draft → approval) | §4.4, §4.5 additions | No | M | — |
| 22 | Supplier statement compare | §4.5, §4.7, §4.8 additions | No | M | — |
| 23 | Buying-group payout reconciliation | §4.7, §4.3 | No (reconciliation only) | M | Decision D3 |
| Track A | ERP preset verification with real files (continuous, not a phase) | — | No | S per file | Pilot files (D2) |

Order: quick and safe first, then the work that produces money numbers. Money phases (20–23)
each need golden fixtures with hand-worked expected values before they ship.

---

## Phase 18: positioning and focus

**Goal:** sell the "independent of your ERP" edge, and stop rarely used features from
crowding the main navigation.

**Do:**
1. Marketing page "Changing ERP?" in `frontend/app/(site)/`. It covers:
   - Epicor's on-prem end dates, with the source link and the date we accessed it
   - why rebate history held outside the ERP survives a migration
   - the existing "Request a pilot" call to action

   No customer names, no outcome claims, no certifications. Unverified statements get
   `[PLACEHOLDER]`.
2. SPA page: show a "Beta" badge and a short note on the page; no logic changes.
3. Deal modelling: remove it from the main navigation and link it from the Agreements list
   ("Model a deal"). The route stays the same.
4. Add the new page to the sitemap and page metadata.

**Tests:**
- axe accessibility checks on the new page
- navigation snapshot or E2E updated
- the deal model is still reachable from Agreements (E2E)
- the SPA badge renders

**Risks:** Low. Marketing copy must not overstate anything (CLAUDE.md §3).

## Phase 19: accrual export formats for NetSuite and Acumatica

**Goal:** the Controller imports the month-end accrual journal straight into their
accounting system. `generic` and `qbo` already exist in `backend/app/services/accruals.py`.

**Do:**
1. Add `netsuite` and `acumatica` formats beside `qbo`, built from each vendor's official
   journal-import documentation (I check the docs first and cite them in code comments).
   Anything I cannot confirm is marked UNVERIFIED in the UI.
2. Map the GL account columns we already store to each format; reversing entries follow
   ADR 0017.
3. Format picker on the Accruals page; the CSV stays formula-safe.

**Tests:**
- golden CSV per format from a fixed accrual fixture
- debit = credit per journal
- formula-injection check
- 422 for an unknown format
- authorization matrix unchanged

**Risks:** Medium. Import templates can be customised per account, so the files stay
labelled UNVERIFIED until a pilot imports one successfully.

## Phase 20: look-back recovery audit

**Goal:** a new customer uploads 2–3 years of history and gets a report of rebates earned
but apparently not received, with evidence ready to claim. This is the sales hook against
contingency auditors.

**Do:**
1. "Recovery audit" wizard:
   - choose suppliers and a date range of up to 36 months
   - check that agreements cover the range; gaps are listed, never guessed
   - run with the existing engine and reconciliation
2. Audit report (PDF and CSV), using the existing export pipeline:
   - **identified** shortfall per supplier and agreement-period, with ageing
   - NEEDS_REVIEW items listed separately and not added to totals
   - a fixed disclaimer: "identified, not recovered" (SPEC §1.4.5)
3. Bulk "create claims" from the selected shortfalls. Each claim gets its normal evidence
   pack.
4. A field for the supplier's claim deadline on the agreement (optional). Periods past the
   deadline are flagged "may be time-barred, check the contract", never dropped silently.
5. Check plan limits on rows per import and history depth. Large audits run as a background
   job and show progress.

**Tests:**
- golden fixture: 3 years, 3 suppliers, hand-worked shortfalls
- a coverage gap produces a listed gap and no number
- NEEDS_REVIEW is excluded from totals
- the deadline flag
- bulk claim creation is idempotent
- cross-tenant tests and the authorization matrix
- E2E for the wizard
- load test with 3 years at the plan's maximum number of rows

**Risks:**
- High, if a projected amount is read as money owed. Mitigation: wording, separate
  totals, and the disclaimer on every page of the PDF.
- Medium: old agreements are often incomplete, so expect many NEEDS_REVIEW items; that is
  correct behaviour.

**Decision D1 (needed first):** sold as a paid one-off audit (price?), or free as part of a
pilot? This changes the plan catalogue (SPEC §4.14).

## Phase 21: bulk agreement import

**Goal:** onboarding 50 supplier programmes takes an afternoon, not a week.

**Do:**
1. New import type `agreements`. The CSV template has one row per component or tier, grouped
   by an agreement key, and is downloadable from the Agreements page.
2. Each row is checked with the same terms schema and validation as the editor (no second
   rulebook). Errors are reported per row, using the existing import error UI.
3. Valid groups become **Draft** agreement versions. Nothing becomes active directly:
   activation uses the normal flow, including the four-eyes check when an org has turned
   it on.
4. Re-importing the same file is idempotent: it matches on the agreement key and creates a
   new draft version, never edits an active one.
5. A preview before commit lists the agreements, components and tiers parsed, with clear
   wording ("12 agreements will be created as drafts").

**Tests:**
- round-trip: export an agreement as template rows, re-import it, and get equal terms
- each validation rule gets a failing row
- duplicate keys
- formula injection in text cells
- tenant isolation
- golden: imported terms produce the same engine output as editor-built terms
- E2E

**Risks:** Medium. Wrong terms at scale lead to wrong numbers. Mitigations: drafts only,
the preview, and the existing explain drawer on the first run.

## Phase 22: supplier statement compare

**Goal:** when a supplier sends their own statement of rebates earned, show line by line
where it disagrees with our calculation. That difference is the claim.

**Do:**
1. New import type `supplier_statement`: supplier, period, programme or agreement
   reference, purchases the supplier counted, and the rebate the supplier calculated.
   CSV/XLSX through the existing import pipeline and mapping templates.
2. Match statement rows to agreement-periods. When more than one match is possible, the
   row is a suggestion with a confidence explanation, like credit matching (SPEC §4.7.1),
   never applied silently.
3. Compare view per agreement-period:
   - our measure against theirs
   - our rebate against theirs
   - the difference, with a reason: purchases missing on their side, rate or tier
     different, or unmatched
4. A new discrepancy type, "statement differs", that can become a claim. The evidence pack
   includes both sides.

**Tests:**
- golden fixtures for each reason
- an unmatched statement row
- rounding tolerance uses the existing rule
- tenant isolation and the authorization matrix
- E2E for import → compare → claim

**Risks:** Medium. Statement layouts vary by supplier, so v1 supports a mapped CSV only;
no PDF reading.

## Phase 23: buying-group payout reconciliation

**Goal:** members of a buying group (e.g. AD/IMARK) can see whether the group passed through
what their suppliers' programmes earned.

**Do:**
1. A credit can be paid by a buying group instead of a supplier: the payer is a
   `suppliers.kind = 'buying_group'` record (already exists in migration 0009).
2. Allocate a group payout across the member suppliers' agreement-periods, using the same
   matching rules as the suggestion and confirm flow.
3. Reconciliation shows "paid via group" separately, and the group's retained share
   (admin fee) is an explicit field on the group record. It is never inferred.
4. Reports: per group, earned against paid through, by supplier.

**Tests:**
- golden fixtures with a group fee, a partial payout, and a payout covering several periods
- allocation never exceeds the payout
- existing supplier-paid reconciliation is unchanged (regression)
- tenant isolation and the authorization matrix

**Risks:** Medium. Group statement formats and fee rules are UNVERIFIED.

**Decision D3 (needed first):** how is the group's retained fee expressed? Is it a % of
rebate, a % of purchases, or does it vary by supplier? It needs a sample statement from a
pilot who is a group member.

## Track A: ERP preset verification (continuous)

When a pilot sends an anonymised export:
1. Add it as a test fixture, with personal and pricing data removed.
2. Adjust the preset.
3. Remove UNVERIFIED for that preset only.

Each file is a small commit with its own test. **D2:** can pilots provide these files?

---

## Not planned (needs a decision first)
These are listed in the review as "later":
- customer (payable) rebates: doubles the engine scope
- scheduled SFTP or email imports: close to the SPEC §14 "no live integration" line
- supplier portal
- SSO
- public API
- any AI/LLM feature: CLAUDE.md §4

## Decisions needed before starting
- **D1:** price model for the recovery audit (before Phase 20).
- **D2:** pilot ERP export files (Track A; doesn't block other phases).
- **D3:** buying-group fee rules and a sample statement (before Phase 23).
- Approval of this plan and of starting Phase 18.
