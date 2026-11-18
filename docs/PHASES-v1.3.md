# RebateLedger v1.3: feature phases (PLAN, awaiting founder approval)

Based on market research of 2026-11-18 (below; extends `docs/research/2026-11-17-feature-review.md`)
and the security audit `docs/security/2026-11-18-audit.md`. Same rules as `docs/PHASES.md`:
- one phase at a time
- a plan first
- money logic gets hand-worked golden tests
- each phase ends with the end-of-phase report, then I stop and ask

No AI features (CLAUDE.md §4). No paid services.

## What users struggle with (research, accessed 2026-11-18)
Vendor-published or vendor-commissioned material is marked *(vendor)*.

| Pain | Evidence |
|---|---|
| Rebate tools take months to implement and are complex to set up | Enable on G2: about 115 reviews, 4.5/5; cons include "difficult implementation", "steep learning curve", "implementation costs, time and effort are extremely high", G2 average 7 months to implement [1]. Vistex: complexity, learning curve, cost, poor reporting [2] |
| Tiers are missed by small margins; sometimes the supplier has to point it out | An HVACR distributor almost missed $10,000, $2,000 short of a tier; the supplier alerted them [3][4] |
| Discrepancies take months to resolve | A $1M discrepancy took months to resolve [4] *(vendor quote)*; claim disputes delay recognition [5] |
| Most rebate work is still manual; nobody owns it | Only 35% have meaningful rebate automation; programs "touch multiple teams but are owned by none" [6] *(vendor)*; 53% still use spreadsheets [7] *(vendor)* |
| Little visibility of rebate impact on margin and liabilities | 2026 survey of 301 leaders: pricing decisions made without full visibility of rebate liabilities [8] *(vendor)* |
| Key-person risk: the spreadsheet owner leaves | [9] *(vendor)* |
| Competitors' 2026 direction: claim automation, partner portals, exception-based dispute handling, audit trails | [10][11] *(vendor directories)* |

## Where we already answer these
- **Setup time:** file-based setup, ERP presets, bulk agreement import.
- **Near-miss tiers:** tier tracker, tier-proximity alerts, weekly digest.
- **Reconciliation and disputes:** reconciliation, claims, evidence packs, supplier statement compare, recovery audit.
- **Liabilities:** month-end accruals.
- **Key-person risk:** audit log.

The gaps are below.

## Phases

| Phase | Feature | Pain it answers | Size | SPEC / engine change |
|---|---|---|---|---|
| 24 | **Getting-started checklist** | Long, complex setup | S | §4.10 addition; no engine change |
| 25 | **Claim-deadline alerts** | Money lost to time-barred claims | S | §4.11 addition; no engine change |
| 26 | **Supplier scorecard** | Disputes, visibility, negotiating leverage | M | New report + supplier tab; no engine change |
| 27 | **Dispute tracking on claims** | Disputes that drag on for months | M | Claim status + fields (migration); §4.8 |
| 28 | **Effective rebate rate report** | Margin and liability visibility | S | New report; no engine change |
| 29 | **Advisor portfolio view** | Fractional CFOs and accountants serving several distributors (SPEC §1.3) | M | Cross-organization summary; security-sensitive |

### 24. Getting-started checklist
**What it does:** a dashboard card, driven by real data rather than ticked by hand:
1. add suppliers
2. import purchases
3. add or bulk-import agreements
4. activate them
5. run a calculation
6. import credits
7. review discrepancies

Each step links to the right page and shows a count. The card hides itself once every step is done.

**Tests:** step state for an empty org, a partly set-up org and a complete one. End-to-end test.

### 25. Claim-deadline alerts
**What it does:** a new alert type `claim_deadline`. It fires for short-paid or missing periods whose agreement claim deadline (`claim_deadline_days`, Phase 20) falls within the next 30 days. It's sent once per period, the user can turn it off, and it also appears in the weekly digest.

**Tests:** boundary days (31, 30 and 0 days left), never sent twice, not sent for paid periods.

### 26. Supplier scorecard
**What it does:** shown per supplier and across all suppliers, over the last 4 quarters:
- rebate earned
- rebate received (% of earned)
- on-time payment rate (credit date against due date)
- average days late
- number of short-paid and missing periods
- open claims
- recovery rate

It appears as a tab on the supplier page and as a report (CSV, Excel or PDF).

**Tests:** a hand-worked fixture with on-time, late, short and missing periods. Tenant isolation.

### 27. Dispute tracking
**What it does:**
- A new claim status `disputed`, between submitted and resolved.
- A supplier response: a reason category (data mismatch, eligibility, rate or tier, timing, other), the supplier's counter-amount and a note.
- Dispute ageing appears on the claims page and in the claims register.
- The evidence pack shows the dispute history.

**Tests:** status transitions (allowed and refused), an existing-claims regression, audit events.

### 28. Effective rebate rate
**What it does:** by supplier, and by category where products exist:
- spend
- rebate earned and received
- effective rate (earned ÷ spend, received ÷ spend)
- change against the same period last year

It's a report plus a dashboard tile.

**Tests:** golden values; zero spend shows "—", never a division error.

### 29. Advisor portfolio view
**What it does:** users who belong to several organizations get one page listing each organization's identified shortfall, missing count, open claims and last run.

**How it stays isolated:** each organization is read in its own tenant context (RLS). The page never runs a query that spans tenants.

**Tests:** every organization the user belongs to is listed; one they've left, or another user's, never is; matrix and RLS tests.

## Not planned without a decision
- **Customer (payable) rebates:** doubles the scope.
- **Supplier portal and SSO:** SPEC §14 says not in v1.
- **Automated emails to suppliers:** SPEC §14.
- **AI (claim triage, reading contracts):** CLAUDE.md §4.
- **Claimable statement differences before the due date:** still open.

## Security and system design (done in this session; see the audit report)
Done:
- open redirect fixed
- API schema hidden in production
- container hardening
- Redis password
- per-user limit on expensive reads
- penetration tests kept as regression tests

Still open, with a recommendation:

| Item | Recommendation |
|---|---|
| Production on the shared VM | High risk (ADR 0018). Recommended: a dedicated VM (~$50–60/month) |
| Restore drill | Not yet run. Before launch |
| Dev-tool advisories in `make audit` | Founder decision |
| Third-party penetration test | Declined (ADR 0016); worth revisiting before the first large customer |

## Sources
1. https://g2.com/products/enable-international-enable/reviews
2. https://www.g2.com/products/vistex/reviews
3. https://www.inddist.com/operations/article/22940874/three-costly-rebate-management-mistakes-distributors-are-making
4. https://www.foodmanufacturing.com/home/article/22940874/three-costly-rebate-management-mistakes-distributors-are-making
5. https://timdietrich.me/blog/improve-vendor-rebate-management-with-ai/
6. https://www.vendavo.com/pricing/rebates-reimagined-pricing-report/
7. https://enable.com/state-of-volume-rebates-2025
8. https://sapinsider.org/map/pricing-rebate-data-margin-visibility-enable-survey/
9. https://www.mealticket.com/blog/manual-rebate-tracking-cost-food-distributors
10. https://www.snipp.com/blog/b2b-rebate-management
11. https://gitnux.org/best/vendor-rebate-management-software/

Read through search-result summaries, not opened page by page; open a source before quoting it externally.
