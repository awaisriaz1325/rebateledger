# Feature, competitor and market review (2026-11-17)

Desk research (web search, all sources accessed 2026-11-17) plus a read of the shipped code.
Most sources are vendor marketing or directories. **Nothing here is a sales claim.** Prices
and survey numbers are labelled with their source; anything I could not confirm says
UNVERIFIED. My own estimates are marked **[estimate]**.

---

## 1. Feature inventory (what ships today)

Core = the reason someone buys. Supporting = needed to trust or run the core.
Rarely needed = most small customers won't use it in month one.

| # | Feature | Proof (path) | Class |
|---|---|---|---|
| 1 | Supplier master, aliases, buying-group members | `frontend/app/app/suppliers/`, `backend/app/services/suppliers.py` | Supporting |
| 2 | Versioned agreements: volume, tiered, growth, per-unit, bonus components; eligibility rules | `frontend/app/app/agreements/`, `backend/app/engine/calculate.py` | Core |
| 3 | Agreement templates | `frontend/app/app/settings/templates/` | Supporting |
| 4 | Deal modelling (what-if before signing) | `frontend/app/app/agreements/model/`, `backend/app/services/deal_models.py` | Rarely needed |
| 5 | CSV/XLSX imports: purchases, credits, sales lines; validation, duplicates, voiding | `frontend/app/app/imports/`, `backend/app/imports/` | Core |
| 6 | ERP import presets (P21, Eclipse, Infor CSD, NetSuite, Acumatica, QBO, QBD), UNVERIFIED against real files | `backend/app/imports/presets.py` | Supporting |
| 7 | Deterministic engine, reproducible runs, explain drawer | `backend/app/engine/`, `frontend/app/app/runs/`, `frontend/app/app/results/` | Core |
| 8 | Reconciliation: earned vs received; credit matching and allocation | `backend/app/services/reconciliation.py`, `frontend/app/app/credits/` | Core |
| 9 | Discrepancies (short-paid, missing, overpaid, unmatched) | `frontend/app/app/discrepancies/` | Core |
| 10 | Claims with evidence pack (PDF) | `frontend/app/app/claims/`, `backend/app/exports/evidence.py` | Core |
| 11 | Tier tracker / opportunities ("$X to next tier") | `frontend/app/app/tiers/`, `backend/app/services/tiers.py` | Core |
| 12 | Month-end reversing accrual journal export | `frontend/app/app/accruals/`, `backend/app/services/accruals.py` | Supporting |
| 13 | Buying-group programs across member suppliers | `backend/app/services/agreements.py` (engine 1.1.0) | Supporting |
| 14 | SPA / ship-and-debit claims from sales lines | `frontend/app/app/spa/`, `backend/app/engine/spa.py` | Rarely needed (outside electrical/HVAC) |
| 15 | Approvals (maker-checker) | `frontend/app/app/approvals/`, `frontend/app/app/settings/approvals/` | Supporting |
| 16 | Dashboard, reports, full export, supplier statement, claims register | `frontend/app/app/page.tsx`, `frontend/app/app/reports/`, `backend/app/exports/` | Core |
| 17 | Notifications + weekly digest email | `frontend/app/app/settings/notifications/`, `backend/app/services/notifications.py` | Supporting |
| 18 | Members, roles, MFA, sessions, audit log | `frontend/app/app/settings/{members,security,audit}/` | Supporting |
| 19 | One user in several orgs (advisors) | `backend/app/services/org.py` | Supporting |
| 20 | Plans, usage, in-app invoices | `frontend/app/app/settings/plan/`, `backend/app/services/billing.py` | Supporting |
| 21 | Operator console | `frontend/app/ops/`, `backend/app/services/ops.py` | Internal |
| 22 | Marketing site, "Request a pilot" | `frontend/app/(site)/` | Supporting |

---

## 2. Competitors

| Competitor | Target size | Public price | Main rebate features | Known weaknesses for independents |
|---|---|---|---|---|
| **Enable** (incl. Flintfox, DealTrack) | Large and enterprise; listed as "Enterprise" by company size [1][2] | None. Quote based on rebate value under management and number of trading partners [1] | Agreement management, calculations, analytics, partner collaboration; used by Affiliated Distributors (a buying group) [3] | Price and implementation effort aimed at large firms. Weaknesses UNVERIFIED (no independent reviews found) |
| **Vistex**, **Vendavo**, **Pricefx** | Enterprise | None found | Pricing + rebates suites | Too big for a 20–200-person distributor [estimate]; one directory lists a $50,000 starting price for an unnamed rebate listing, UNVERIFIED [4] |
| **Phocas Rebates** | Mid-market distributors (BI first) | None found | Payable and receivable rebates, pro-rata forecasting, claim validation at transaction level, growth rebates [5][6] | A BI purchase first; rebates are a module. Cost UNVERIFIED |
| **Epicor Eclipse** (native) | Electrical/plumbing/HVAC distributors on Eclipse | Bundled with ERP | Vendor rebate management, SPA handling, recorded through to GL [7][8] | One blog says larger houses add a dedicated tool for complex programmes, and puts specialised tools at $1,000–$5,000/month, UNVERIFIED single source [9] |
| **Epicor Prophet 21** (native) + Epicor Data Analytics Rebates | P21 customers | Bundled / add-on | Rebates via price pages and contracts; separate analytics product with pro-rata and near-miss analysis [10][11] | A third-party P21 rebate automation vendor exists [12], so gaps are likely. Exact gaps UNVERIFIED. **On-prem P21 final release tentatively May 2028; active support to 30 Jun 2029** (CIO.com, 7 Jan 2026) [13] |
| **Infor CloudSuite Distribution (SX.e)** | Infor customers | Bundled | Vendor-on-purchase and vendor-on-sale rebates, EDI 849 claim responses, rebate reconciliation entry, outstanding-rebate report [14][15] | Alternate rebates not supported in the cloud product [16] |
| **NetSuite Rebates and Trade Promotions SuiteApp** | NetSuite customers | Part of NetSuite licensing; cost UNVERIFIED | Agreements, accruals, settlements as vendor credits [17] | Documented limits: recalculates only on save; real-time display slows large volumes; no "Internal" custom segments in accruals [17]. One old forum complaint of slow entry on the previous bundle [18] |
| **Acumatica** + add-ons (IIG AcuRebate, Asgard) | Acumatica customers | None found | Set up, calculate, report, credit memos; breakpoints by period [19][20] | No native vendor rebate feature found; depends on partner add-on |
| **Rebate.AI** (Tredence) | Buying groups, suppliers, distributors | None [21] | Analytics platform for buying groups and members [22] | AI-first; not comparable to our no-AI v1 |
| **Spreadsheets** | Most small independents | Free | Anything, by hand | Enable surveys: 53% still use spreadsheets [23]; 52% believe they don't receive all rebates they earn (2024) [24]; spreadsheet users miss ~1% of rebates owed (2022) [23]. All vendor-commissioned |
| **Contingency recovery auditors** (PRGX, apexanalytix, ProfitOptics rebate audit) | Mid to large | 20–30% of recoveries typical, some 10–40%, some add a fixed fee [25][26] | Look-back audit of payments and rebates | Pay a large share forever; one-off, not continuous; no month-end accrual |

"Rebate Tracker" as a named product: **not found**.

---

## 3. Market

### Sourced facts
- US wholesale trade had 418,780 establishments in 2012; merchant wholesalers of durable goods
  243,645 [27]. Newer Economic Census totals not retrieved: UNVERIFIED for today.
- Electrical (NAICS 423610): 13,379 establishments in 2023 per a third-party site citing
  Census CBP, UNVERIFIED [28]. Electrical Wholesaling put full-line electrical locations
  at ~7,000 (2010) and ~4,000 main houses + 6,000 branches (older) [29].
- Consolidation: many family-owned independents are being bought by large national and
  regional distributors [30].
- Buying groups: AD merged with IMARK Electrical in Sept 2024, >700 independent electrical
  distributors in one group [31]. 57% of distributors in buying groups don't know the rebate
  earned per manufacturer (Enable survey) [31].
- Distributors have rebate programmes with ~50 of their top 100 manufacturers (Enable, 2022) [25].
- Only 43% of distributors know the rebate earned per manufacturer (MDM / Enable) [25].
- ERP churn: Epicor ends on-prem P21, Kinetic and BisTrack (P21 final on-prem release ~May
  2028) [13]. An Epicor-commissioned Forrester survey: 68% of distributors plan to change ERP
  by 2028 [32].
- Buyers report setup and mapping effort as the main cost before value appears; "time saved"
  is felt before "money recovered" [33].
- Accrual timing (monthly vs continuous) is a known buying question [33].

### Estimates (mine, not sourced)
- **Target customers:** independent electrical, HVAC/R, plumbing and building-materials
  distributors with $20M–$250M revenue: low thousands of companies in the US.
- **Who decides:** the CFO or Controller signs. A rebate admin or AP lead does the daily work.
- **Typical budget:** a few hundred to low thousands of dollars per month, so $249–$899
  is plausible. Verify this with pilots.
- **What triggers a purchase:**
  - a supplier short-pays and someone notices
  - auditors question the rebate receivable
  - the person who kept the spreadsheet leaves
  - an ERP migration
  - joining a buying group

---

## 4. Gap analysis

Y = yes per vendor material · P = partial · N = no · ? = not found / UNVERIFIED.

| Capability | RebateLedger | Enable | Phocas | Eclipse / P21 native | NetSuite RTP | Infor CSD | Spreadsheets | Recovery auditors |
|---|---|---|---|---|---|---|---|---|
| Agreement rules (tiers, growth, per-unit) | Y | Y | Y | Y | Y | Y | P | N |
| Earned vs received vs missing, per period | **Y** | Y | P | P | P | P (reconciliation entry) | P | Y (one-off) |
| Explain any number to source lines | **Y** | ? | P (transaction level) | ? | ? | ? | N | P |
| Claims with evidence pack | **Y** | ? | P | ? | N | P (EDI 849) | N | Y |
| Tier opportunity / forecast | Y | Y | Y (pro-rata) | Y (Epicor DA) | ? | ? | N | N |
| Accrual journal | Y (export) | Y | ? | Y (posts to GL) | Y (posts) | ? | P | N |
| Buying-group programmes | Y | Y | ? | ? | ? | ? | P | N |
| SPA / ship-and-debit | Y | Y | ? | Y (Eclipse) | ? | Y (vendor-on-sale) | P | ? |
| Customer (payable) rebates | **N** | Y | Y | Y | Y | Y | P | N |
| Live ERP integration / EDI | **N** (files) | Y | Y | native | native | native, EDI 849 | N | N |
| Supplier portal / collaboration | **N** | Y | ? | N | N | N | N | N |
| Bulk agreement import | **N** | ? | ? | ? | ? | ? | n/a | n/a |
| Look-back audit for past years | P (possible, not packaged) | ? | ? | N | N | N | N | **Y** |
| ERP-independent (survives ERP change) | **Y** | Y | Y | N | N | N | Y | Y |
| Price for a 50-person distributor | **$249–$899/mo (planned)** | quote | quote | bundled | bundled | bundled | free | 20–30% of recoveries |

### Gaps that lose deals
1. **Onboarding effort.** Typing in 50 supplier agreements by hand is the biggest cost before
   value appears, and we have no bulk agreement import [33].
2. **Unproven ERP presets.** The 7 presets have never seen a real export file.
3. **Accounting fit.** Prospects ask about accruals [33]. Our export is generic CSV, with no
   import format for QuickBooks, NetSuite or Acumatica journals.
4. **Customer (payable) rebates.** Every ERP and mid-market rival does them. Distributors that
   pay contractor rebates may want both in one tool. Larger scope: needs a decision.

### Where we are ahead
- Independent of the ERP, so the rebate history survives the 2028 P21 / Kinetic migrations.
- Every number can be explained down to source lines, and runs are reproducible
  (identical output from the same inputs).
- An evidence pack per claim.
- A published monthly price instead of quotes or a 20–30% contingency fee.
- Buying-group programmes and SPA claims built in, at a small-company price.

---

## 5. Recommendations

Ranked by impact ÷ effort. Effort: S ≈ days, M ≈ 1–3 weeks, L ≈ months.

| # | Feature | Action | Evidence | Who benefits | Effort | Impact | Risk |
|---|---|---|---|---|---|---|---|
| 1 | **Look-back recovery audit** (package the existing engine as "import 2–3 years, get a recovery report"): first version is a report preset plus a pilot offer | Add | Auditors charge 20–30% of recoveries [25][26]; prospects feel "time saved" first, so a cash finding is the faster hook [33] | CFO (cash), sales | S | High | Must never present "identified" as "recovered" (SPEC §1.4.5). Old agreements may be incomplete, so expect many NEEDS_REVIEW |
| 2 | **Verify ERP presets with real exports** (one anonymised file per ERP from pilots) | Change | Presets UNVERIFIED (ADR 0017); SPEC §15 item 8 | Analyst onboarding | S | High | Needs customer files; handle as sensitive data |
| 3 | **Bulk agreement import** (CSV template, one row per tier; same validation and approval as the editor) | Add | Setup effort is the top complaint [33] | Rebate admin | M | High | Wrong bulk terms produce wrong numbers at scale. Imported agreements go to Draft and need approval |
| 4 | **Accrual export presets** for NetSuite and Acumatica journal import (QBO already exists: `backend/app/services/accruals.py`) | Change | Accrual timing is a known buying question [33] | Controller | S | Medium | Column formats UNVERIFIED until tested against real imports |
| 5 | **ERP-migration positioning** (marketing page: "your rebate history survives the ERP change") | Add | P21 on-prem ends 2028 [13]; 68% plan an ERP change [32] | Sales | S | Medium | Must not name customers or claim certifications |
| 6 | **Supplier rebate statement compare**: import the supplier's own statement of earnings and diff it against our calculation per agreement-period | Add | Disputes start from the supplier's statement; competitors validate claims against terms [5] | Analyst, claims | M | Medium | Statement formats vary by supplier; start with a CSV mapping only |
| 7 | **Buying-group payout reconciliation** (credits paid by the group, not the supplier) | Change | 57% of buying-group members don't know their earned rebate [31]; AD + IMARK has >700 members [31] | Members of AD / IMARK and similar groups | M | Medium | Group statement formats UNVERIFIED |
| 8 | Core: agreements, imports, engine, reconciliation, claims, tiers, dashboard, audit, MFA | Keep | This is the product | All | n/a | High | n/a |
| 9 | SPA / ship-and-debit | Keep, label beta; no new work until a pilot asks | Eclipse handles SPAs natively for most users [9]; electrical/HVAC only | Electrical and HVAC distributors | n/a | Low–Med | Maintenance cost on a niche feature |
| 10 | Deal modelling | Keep, move out of the main navigation (link it from agreements) | Rarely used in month one [estimate] | Purchasing manager | S | Low | None |
| 11 | Approvals (maker-checker) | Keep — already off by default (`four_eyes_*` default False, `backend/app/db/models/identity.py`) | Checked in code | Small teams | n/a | Low | None |
| 12 | Weekly digest | Keep | Cheap and keeps people coming back [estimate] | Controller | n/a | Low | None |
| 13 | Customer (payable) rebates | Later, needs a decision | All rivals have it (§2) | Distributors who pay contractor rebates | L | Med–High | Doubles the engine scope; SPEC scope change |
| 14 | Scheduled file drop (SFTP or email-in imports) | Later, needs a decision | Removes the monthly manual upload | Analyst | M | Medium | Near the "no live integration" line in SPEC §14; adds an inbound attack surface |
| 15 | Supplier portal, SSO, public API | Later (SPEC §14) | Enterprise features [1] | Larger customers | L | Low now | Scope |

**Removals.** Nothing should be deleted outright: every shipped feature has tests and was
asked for. The cheaper moves are to demote rarely used features (rows 9–10) rather than
remove them. If a feature shows no use after 3 pilots, remove it then (SPA is the first
candidate).

**AI/LLM (not allowed in v1, CLAUDE.md §4). Later, needs a decision.** Possible uses:
- reading agreement terms from supplier PDF contracts into a draft
- suggesting credit-to-agreement matches

Rebate.AI and Enable market these [2][22]. If ever added, the output must stay a draft for a
person to approve.

---

## 6. Top 5 next

1. **Look-back recovery audit offer (S).** It reuses the engine we already have and turns a
   pilot into a cash number the CFO can see. It also undercuts auditors who keep 20–30% of
   what they recover.
2. **Real ERP sample files for the presets (S).** Onboarding currently rests on unverified
   column guesses, and one wrong mapping breaks trust in the first week.
3. **Bulk agreement import (M).** Setup effort is what buyers complain about most.
   Keep it safe by importing to Draft and requiring approval.
4. **Accrual export presets for NetSuite and Acumatica (S; QBO already ships).** These close the
   Controller's month-end loop with little code.
5. **ERP-migration landing page (S).** P21's on-prem end in 2028 and the planned ERP changes
   are a real trigger to buy, and we are the tool that does not depend on the ERP.

None of these needs a new paid service. Items 1, 3 and 4 touch money logic, so each needs
golden tests before it ships.

---

## Assumptions
- The target is independent US electrical, HVAC/R, plumbing and building-materials
  distributors (SPEC §1.3), and the prices are those in SPEC §4.14.
- Usage claims ("rarely needed") are my judgement; there are no usage analytics yet.
- Vendor survey figures (Enable, Epicor/Forrester) are treated as direction only.

## Could not verify
- Citation mapping. Sources were read through search-result summaries, not opened page by page,
  so a few numbers may come from a sibling page in the same search: the AD/IMARK merger and the
  57% figure [31], and the 43% and "50 of top 100" figures [25]. Open the page before quoting
  any number externally.
- Any competitor price except the commission ranges, which are self-reported.
- What P21's native rebate module can and cannot do.
- What Enable's distributor reviews say.
- A current Census count of target distributors (the latest official figure found is from 2012).
- Whether a product called "Rebate Tracker" exists.
- The $1,000–$5,000/month figure for specialised tools (one blog source).

## Open questions for you
1. Approve the look-back audit as a paid one-off, or only as a free pilot hook? This
   changes pricing (SPEC §4.14).
2. Can pilots provide anonymised ERP exports and supplier statements?
3. Customer (payable) rebates: in scope for v2, or never?
4. Scheduled SFTP or email imports: allowed under the "no live integration" rule?

---

## Sources (accessed 2026-11-17)
1. https://erpresearch.com/erp-add-ons/distribution/enable/pricing
2. https://www.guideflow.com/blog/rebate-management-software
3. https://enable.com/customer-stories/affiliated-distributors-scales-to-45bn-in-revenue-with-enable
4. https://www.sourceforge.net/software/rebate-management/windows
5. https://phocassoftware.com/rebates
6. https://docs.phocassoftware.com/rebates/overview-of-rebates
7. https://ondemand.epicor.com/courseResources/r2366_IndustryTraining_ElectricalDistribution-Transcript_1.pdf
8. https://www.epicor.com/en/solutions/industries/distribution/electrical-distribution-software/
9. https://pulserevops.com/knowledge/tk0176
10. https://epicor.swoogo.com/insights2026/session/3995519/a-practical-guide-to-using-rebate-functionality
11. https://www.epicor.com/en-us/products/business-intelligence-and-data-management/epicor-data-analytics/epicor-data-analytics-rebates/
12. https://www.mindharbor.com/p21-supplier-rebates-price-page-automation
13. https://www.cio.com/article/4114170/epicor-sets-timeline-to-sunset-on-prem-erp-as-cloud-becomes-the-only-path-forward.html
14. https://docs.infor.com/csdis/latest/en-us/useradminlib_csd_cloud/sxepgov/sx_smror-master.html
15. https://docs.infor.com/csdis/2026.x/en-us/useradminlib_csd_cloud/edolh/yvx1569596790376.html
16. https://docs.infor.com/sxe/2021.x/en-us/sxolh/paz1503926027273.html
17. https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_163653469325.html
18. https://archive.netsuiteprofessionals.com/t/27562462/good-morning-does-anyone-have-any-feedback-on-the-rebates-ma
19. https://www.acumatica.com/acumatica-marketplace/iig-acuboost-rebate-processing/
20. https://www.acumatica.com/content/plugins/ac-marketplace/uploads/DEVCONSULT/Manage-ISV-Solution-1638-3Manage-ISV-Solution1616-3Case-Study-Vendor-Rebate.pdf
21. https://g2.com/products/rebate-ai/pricing
22. https://www.tredence.com/blog/tredence-propels-intelligent-enterprise-rebate-management-with-launch-of-rebateai
23. https://enable.com/state-of-volume-rebates-2025
24. https://www.mdm.com/news/operations/finance/rebates-half-of-distributors-say-theyre-not-getting-what-theyve-earned/
25. https://www.sentra.app/articles/recovery-audit
26. https://www.prgx.com/faq/how-much-does-a-recovery-audit-cost
27. https://www.census.gov/newsroom/releases/pdf/2012_econ_advance_report.pdf
28. https://vantainsights.com/industry/423610-electrical-apparatus-equipment-wiring-supplies-related-equipment-merchant-wholesalers
29. https://ewweb.com/community-opinions/article/20920230/defining-the-universe
30. https://www.ecmweb.com/product-sourcing-supply/article/55131107/2024s-top-50-electrical-distributors
31. https://enable.com/blog/how-buying-groups-can-put-more-money-in-their-members-pockets
32. https://www.mdm.com/news/technology/erp/epicor-debuts-agentic-ai-platform-promises-90-day-cloud-erp-deployments/
33. https://www.g2.com/discussions/is-dedicated-rebate-management-software-worth-it-for-a-mid-size-distributor
