# RebateLedger — Product & Technical Specification (v1.0)

Status: approved for build. Working name "RebateLedger" (brand and domain not yet
verified; keep the name in one config value so it can change).

Conventions in this document:
- **MUST / MUST NOT** are hard requirements. **SHOULD** is a strong default you may
  change only with an ADR. **MAY** is optional.
- **[PROPOSED DEFAULT]** marks a number chosen as a sensible starting point, not a
  researched fact. Make it configurable.
- **[OPEN]** marks a decision that needs the founder. Ask; do not guess.

---

## 1. Product summary

### 1.1 Problem
Distributors buy from manufacturers under rebate agreements (volume, tiered,
growth, per-unit, bonus). Finance teams track these in ERP exports and
spreadsheets, often cannot say what they earned per manufacturer, and miss
credits they were owed.

### 1.2 What RebateLedger does
1. Store supplier rebate agreements as precise, versioned rules.
2. Import purchase lines and supplier credits from CSV/XLSX exports (no ERP integration in v1).
3. Calculate the expected rebate per agreement per period with a deterministic engine.
4. Reconcile expected vs received; flag short-paid, missing, overpaid and unmatched items.
5. Manage claims to recover money, with an evidence pack per claim.
6. Show tier opportunities ("you are $18,400 from the next tier with 12 days left").

### 1.3 Who uses it
- **Economic buyer:** CFO / Controller / VP Finance at a US electrical, HVAC/R,
  plumbing or building-materials distributor.
- **Daily user:** finance analyst, rebate administrator, purchasing manager.
- **Advisors:** fractional CFOs and accountants who serve several distributors
  (supported via one user belonging to several organizations).
- **Platform operator:** the founder, via an internal operations console.

### 1.4 Product principles
1. **Explainable over clever.** Every number can be traced to agreement terms and source lines.
2. **Never guess with money.** Ambiguity becomes `NEEDS_REVIEW`, never a silent assumption.
3. **Reproducible.** Any past result can be regenerated exactly from stored inputs.
4. **Overlay, not replacement.** Works from exports; never asks the customer to change ERP.
5. **Identified ≠ recovered.** The product never reports a projected amount as recovered money.
6. **Secure by default.** Supplier pricing and purchase data are commercially sensitive.

### 1.5 Commercial model at launch
- Invoice-only billing (no card checkout). Pilots and subscriptions are provisioned
  by the operator; invoices are generated in-app and paid by bank transfer.
- No public self-serve signup at launch. Public site offers "Request a pilot".
  Self-serve signup exists behind a feature flag, off by default.

---

## 2. Roles and permissions

### 2.1 Tenant roles
| Role | Purpose |
|---|---|
| **Owner** | Full control incl. billing view, security settings, ownership transfer, org deletion. At least one per org. |
| **Admin** | Manage users (except Owners), settings, agreements, approvals, imports, runs, claims. |
| **Analyst** | Create/edit agreements (drafts), run imports and reconciliations, work claims. Cannot approve own items when four-eyes is on. |
| **Viewer** | Read-only access to all business data and reports. Can export reports. |

### 2.2 Platform role
- **Platform admin** (operator). Not a tenant role. Created only via a backend CLI
  command. MFA mandatory. Cannot see tenant business data unless a tenant
  Admin/Owner has granted time-boxed support access (§4.15).

### 2.3 Permission matrix (minimum; implement as named permissions, map roles to permissions)
| Capability | Owner | Admin | Analyst | Viewer |
|---|:-:|:-:|:-:|:-:|
| View dashboards, suppliers, agreements, results, claims | ✓ | ✓ | ✓ | ✓ |
| Export reports / evidence packs | ✓ | ✓ | ✓ | ✓ |
| Create/edit suppliers | ✓ | ✓ | ✓ | |
| Create/edit agreement drafts | ✓ | ✓ | ✓ | |
| Activate agreement version | ✓ | ✓ | ✓* | |
| Upload/commit/void imports | ✓ | ✓ | ✓ | |
| Start reconciliation runs | ✓ | ✓ | ✓ | |
| Create/edit claims, record outcomes | ✓ | ✓ | ✓ | |
| Write off a claim | ✓ | ✓ | ✓* | |
| Invite users / change roles (non-Owner) | ✓ | ✓ | | |
| Promote/demote Owners, transfer ownership | ✓ | | | |
| Org settings, tolerances, security policy | ✓ | ✓ | | |
| View audit log | ✓ | ✓ | | |
| View plan, usage and invoices | ✓ | ✓ | | |
| Full data export, delete organization | ✓ | | | |
| Grant/revoke support access | ✓ | ✓ | | |

\* When the tenant enables **four-eyes approval**, these actions require approval by a
different user with Admin or Owner role. Self-approval MUST be impossible, including
via role changes mid-flow.

---

## 3. Glossary

- **Supplier** — a manufacturer/vendor the distributor buys from.
- **Agreement** — a rebate program with one supplier; has one or more **versions**.
- **Agreement version** — an effective-dated, immutable-once-active set of rules.
- **Component** — one calculation inside a version (e.g. base 2% + growth bonus). Components sum.
- **Period** — the measurement window (month, quarter, half, year, or custom).
- **Measure (M)** — the quantity tiers are tested against: eligible spend or eligible units.
- **Eligible line** — a purchase line that passes the version's eligibility filters for the period.
- **Expected (E)** — rebate the engine calculates for an agreement-period.
- **Received (C)** — supplier credits allocated to that agreement-period.
- **Variance (V)** — `C − E`.
- **Run** — one execution of the engine + reconciliation over a defined scope with frozen inputs.
- **Claim** — a recovery case opened for a short-paid or missing amount.
- **Identified** — variance the system has found. **Recovered** — money the user has confirmed received.

---

## 4. Functional requirements

### 4.1 Authentication & account security
- Email + password login. Password rules: minimum 12 characters, maximum 128,
  no composition rules, reject passwords found in a breached-password corpus
  (use the k-anonymity range API of Have I Been Pwned or an offline list; fail
  open with a logged warning if the service is unreachable). Hash with Argon2id.
- **MFA:** TOTP (authenticator app) plus 10 single-use recovery codes (stored hashed).
  MFA is mandatory for Owner and Admin roles and for platform admins; tenants MAY
  require it for all users. TOTP secrets are encrypted at rest with an application
  key held in Secret Manager.
- **Sessions:** opaque random token (≥ 256 bits) in a cookie named with the
  `__Host-` prefix, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`. Server stores
  only a hash of the token. Idle timeout 30 min [PROPOSED DEFAULT, tenant-configurable
  15–240 min]; absolute lifetime 12 h [PROPOSED DEFAULT]. Rotate the token on login,
  MFA completion and privilege change. Revoke all sessions on password change, MFA
  reset and user deactivation.
- **Step-up re-authentication** (password + TOTP within the last 10 min) for:
  changing roles, security settings, full data export, deleting the org, granting
  support access, disabling MFA, ownership transfer.
- **Flows:** login, MFA challenge, MFA enrollment, recovery-code login (forces MFA
  re-enrollment prompt), forgot password, reset password, email verification,
  accept invite, change password, change email (verify new address, notify old),
  view and revoke active sessions (device, approximate location from IP is NOT
  required; show user agent and last-seen time).
- **Anti-abuse:** rate limit login, MFA, reset and invite endpoints per IP and per
  account; progressive delay after failures; temporary lockout (15 min after 10
  failures [PROPOSED DEFAULT]) without permanent lockout. Identical responses and
  similar timing for "unknown email" vs "wrong password" (no user enumeration),
  including on forgot-password.
- All tokens sent by email (invite, verify, reset) are single-use, random,
  stored hashed, and expire (invite 7 days, verify 24 h, reset 30 min [PROPOSED DEFAULTS]).
- Security notifications by email (cannot be disabled): new sign-in from a new
  device, password changed, MFA enabled/disabled, email changed, role changed.

### 4.2 Organizations, users and membership
- An organization (tenant) has: name, legal name (optional), timezone, fiscal year
  start month, currency (USD only in v1, read-only), logo (optional, validated image).
- A user MAY belong to several organizations with a different role in each; an
  org switcher appears when they do. Each request operates in exactly one org context.
- Invite users by email with a role; resend, revoke pending invites; deactivate
  users (sessions revoked, data retained, seat freed); reactivate.
- The last active Owner cannot be demoted, deactivated or removed.
- Optional allowed-email-domain list for invites.
- Onboarding checklist for new orgs: add supplier → add agreement → import purchases
  → import credits → run reconciliation → review results. Dismissible, progress saved.

### 4.3 Suppliers
- Fields: name, supplier code(s) (aliases as they appear in import files; unique
  per tenant), category tags, contacts (name, email, phone, role), payment notes,
  status (active/inactive), notes.
- Supplier detail page: agreements, latest results, open claims, data freshness
  (latest purchase date imported, latest credit date imported), activity timeline.
- Merge two suppliers (moves aliases, agreements, lines, credits; audited;
  blocked if both have overlapping active agreements until resolved).

### 4.4 Rebate agreements

#### 4.4.1 Structure
```
Agreement: supplier, name, external reference, status, owner user, notes, attachments
  └─ AgreementVersion (effective_from, effective_to?, status, version_no)
       ├─ period: type (monthly|quarterly|semiannual|annual|custom), fiscal alignment,
       │          custom period list when type=custom
       ├─ date_basis: invoice_date | ship_date | receipt_date
       ├─ measure: spend | quantity
       ├─ spend_basis: net_of_returns | gross        (does a return reduce M?)
       ├─ threshold_comparison: gte | gt             (explicit; no default hidden in code)
       ├─ eligibility: include/exclude rules (see 4.4.3)
       ├─ components[]: one or more calculation components (see 4.4.2)
       ├─ cap_amount?, minimum_payout?
       ├─ negative_result: floor_at_zero | allow_clawback   (default floor_at_zero)
       ├─ rounding_mode: half_up | half_even; scale 2
       ├─ payment_terms_days: credits expected within N days after period end
       ├─ stacking: exclusive | stackable   (may a line count toward another agreement
       │                                     of the same supplier in the same period?)
       ├─ prorate_thresholds_on_partial_period: bool (default false)
       └─ zero_baseline_policy: needs_review | qualifies | does_not_qualify (growth only)
```

#### 4.4.2 Component types — exact semantics
Let `M` = eligible measure for the period, `S` = eligible net spend, `Q` = eligible
net quantity, `B` = baseline measure (growth types). Rates are decimal fractions
(0.02 = 2%). Tier thresholds are strictly ascending; validation rejects otherwise
and warns (does not reject) if rates decrease as tiers rise.

| Type | Parameters | Expected for the component |
|---|---|---|
| `flat_percent` | `rate` | `rate × S` |
| `per_unit` | `amount_per_unit` | `amount_per_unit × Q` |
| `tiered_all_units` | `tiers[{threshold, rate or amount_per_unit}]` | Find highest tier whose threshold is met by `M` (using `threshold_comparison`). Pay that tier's rate × `S` (or amount × `Q`) on **all** eligible volume. If no tier is met → 0. |
| `tiered_incremental` | same | Each tier's rate applies only to the portion of `M` inside its band `[threshold_i, threshold_{i+1})`. Requires payout basis = measure basis (rate tiers need `measure=spend`; per-unit tiers need `measure=quantity`). Validation enforces this. |
| `growth_incremental` | `rate`, `baseline_source` | `rate × max(0, M − B)` |
| `growth_threshold` | `rate`, `growth_pct`, `baseline_source` | If `B > 0` and `(M ÷ B − 1)` meets `growth_pct` by `threshold_comparison`: `rate × S`; else 0. If `B = 0` apply `zero_baseline_policy`. |
| `fixed_bonus` | `amount`, `threshold` | `amount` if `M` meets `threshold`, else 0. |

`baseline_source`: `imported` (a baseline value imported per agreement-period) or
`prior_period_computed` (engine computes `M` for the same version eligibility over
the corresponding prior period from imported lines). Missing baseline →
`NEEDS_REVIEW` (`BASELINE_MISSING`), never treated as zero.

**Order of operations per agreement-period (MUST be implemented exactly):**
1. Select lines whose basis date falls in the period (clipped to version effective range).
2. Apply eligibility filters; record excluded lines with reason codes.
3. Compute `S`, `Q`, `M` with full precision (returns handled per `spend_basis`).
4. Compute each component at full precision.
5. Sum components.
6. Apply `negative_result` policy.
7. Apply `cap_amount` (if set) → result ≤ cap.
8. Apply `minimum_payout` (if set): if result < minimum → 0 with status `BELOW_MINIMUM`.
9. Round once to 2 decimal places with `rounding_mode`.
10. Emit result + full trace (inputs, intermediate values, steps 1–9).

#### 4.4.3 Eligibility rules
Include and exclude filters on: SKU list, product category list (from import or
product catalog), branch/location list, line flags (e.g. `special_pricing`,
`drop_ship`, `promo`) as booleans present in the import, and minimum line amount.
Exclude wins over include. Lines with a missing attribute that a filter depends on
are excluded with reason `ATTRIBUTE_MISSING` and counted in the trace.

#### 4.4.4 Lifecycle and versioning
- Version states: `draft → (pending_approval →) active → superseded | expired`;
  `archived` for agreements no longer used.
- Active versions are immutable. Changing terms = create a new version with an
  effective date.
- Effective ranges of a single agreement's versions MUST NOT overlap.
- **Mid-period version change:** if a version boundary falls inside a period, the
  engine MUST NOT pick a version. The period gets `NEEDS_REVIEW`
  (`VERSION_CHANGE_IN_PERIOD`) until the user chooses: apply old version, apply new
  version, or split the period at the boundary (each sub-period measured separately,
  thresholds prorated only if `prorate_thresholds_on_partial_period`).
- **Partial periods** (agreement starts/ends mid-period): period is clipped; result
  status includes `PARTIAL_PERIOD` (informational).
- **Overlapping exclusive agreements:** if a line is eligible for two exclusive
  agreements of the same supplier in the same period, both agreement-periods get
  `NEEDS_REVIEW` (`STACKING_CONFLICT`) listing the conflicting lines.

#### 4.4.5 Agreement editor UX requirements
- Form-based rule builder with inline validation.
- **Deterministic plain-English summary** generated from the rules (template code,
  not AI), e.g. "Pays 2.00% on eligible net spend once quarterly eligible spend is at
  least $250,000. Applies to all eligible spend (all-units). Excludes special-pricing lines."
- **Preview:** dry-run the draft version against already-imported data for a chosen
  period and show the result + trace without saving a run.
- Version history with a side-by-side diff of terms.
- Attach the source agreement document (PDF/DOCX/XLSX/image) for reference.

### 4.5 Data imports

#### 4.5.1 Import types
| Type | Required columns | Optional columns |
|---|---|---|
| Purchase lines | supplier code, basis date(s) per agreements in use, SKU, quantity, extended amount, invoice number | line number, unit price, ship date, receipt date, branch, category, description, line flags, currency |
| Supplier credits | supplier code, credit date, amount, credit reference | memo, agreement reference, period start, period end, currency |
| Baselines | supplier code or agreement reference, period start, period end, measure value | notes |
| Product catalog | SKU, category | description, supplier code |
| Suppliers (bulk) | name, supplier code | contacts, tags |

#### 4.5.2 Import flow
1. **Upload** CSV or XLSX (first worksheet unless the user picks one). Max 50 MB and
   1,000,000 rows per file [PROPOSED DEFAULTS; plan limits may be lower].
2. **Detect** encoding (UTF-8, UTF-8 with BOM, UTF-16 with BOM, Windows-1252 fallback,
   with the detected value shown and user-overridable), delimiter (comma, semicolon,
   tab, pipe), header row (user can choose a different row).
3. **Map columns** to fields. Auto-suggest from header names and previously saved
   **mapping templates** (per tenant, per import type, optionally per supplier).
   Templates are versioned and selectable by name.
4. **Choose formats explicitly:** date format (never auto-guess between MM/DD and
   DD/MM; offer detected candidates and require confirmation when ambiguous),
   decimal/thousand separators, negative style (`-123.45`, `(123.45)`, `123.45-`),
   currency symbol stripping, credit sign convention (credits positive or negative in file).
5. **Validate:** instant preview of the first 200 rows with per-cell errors, then a
   background full validation producing a downloadable error report (row number,
   column, value, error code, message).
6. **Commit:** default all-or-nothing. User MAY choose "commit valid rows, skip
   invalid" — skipped rows stay listed in the batch record. Progress is shown live.
7. **Result:** batch summary (rows read/committed/skipped/duplicates, date range,
   suppliers touched, totals by supplier) and links to affected agreements.

#### 4.5.3 Validation rules (minimum)
- Required fields present; types parse; dates are real calendar dates within a sane
  window (not before 2000-01-01, not more than 31 days in the future [PROPOSED DEFAULT]).
- Amounts parse to Decimal with ≤ 4 decimal places; quantities ≤ 4 decimal places.
- If unit price and quantity and extended amount are all present, check
  `|qty × price − amount| ≤ max(0.01, 0.1% of amount)` [PROPOSED DEFAULT] → warning, not error.
- Currency column, if present, MUST be USD (case-insensitive) or the row errors (v1).
- Supplier code must map to a supplier or alias. Unknown codes are grouped in one
  error type with an in-flow action: "create supplier" or "map to existing supplier".
- SKUs are text: preserve leading zeros; detect values that look like spreadsheet
  scientific notation (e.g. `1.23E+11`) and warn that the source file was corrupted
  by Excel.
- Trim whitespace, normalise Unicode (NFC), drop fully empty rows, reject rows with
  more cells than headers (report, don't shift).
- Negative quantity/amount lines are returns; allowed and flagged as such.

#### 4.5.4 Duplicates and idempotency
- File-level: SHA-256 of the file; re-uploading an identical file warns with the date
  and batch of the previous import and requires explicit confirmation.
- Row-level purchase key: `(supplier, invoice_number, line_number)` when line number
  exists; otherwise a hash of all mapped normalized fields. Credit key:
  `(supplier, credit_reference)`. Duplicates of committed rows are skipped and counted.
- Same amount + same date + different credit reference → "possible duplicate" warning.

#### 4.5.5 Voiding
- A committed batch can be **voided** (soft): its rows are excluded from future runs.
- Past runs are not modified; they reference the batches they used. Runs whose inputs
  include a voided batch are marked **stale** with the reason.
- Hard delete of import data only via org deletion or data-retention policy.

#### 4.5.6 File security
- Validate extension AND file signature (magic bytes); reject macros-enabled formats
  (`.xlsm`, `.xlsb`) and anything not CSV/XLSX for imports.
- XLSX parsing MUST use a library configured with safe XML parsing (no external
  entities) and MUST enforce a maximum decompressed size and row/column limits before
  loading (zip-bomb protection).
- Store originals in object storage under a tenant-scoped random key; never in the
  web root; never served inline.

### 4.6 Calculation engine (non-functional)
- Implemented as an isolated Python package `backend/app/engine/` with no
  dependencies on web, DB or storage code.
- Public entry point (shape, not exact signature):
  `calculate(version_snapshot, period, lines, baselines, options) -> PeriodResult`.
- `PeriodResult`: expected (rounded + unrounded), per-component values, `S`, `Q`, `M`,
  tier reached, eligible/excluded counts by reason, status set (`OK`, `NEEDS_REVIEW`,
  `PARTIAL_PERIOD`, `BELOW_MINIMUM`, `CAPPED`, `NOT_EARNED`), reasons, trace,
  `engine_version`, `input_hash` (SHA-256 of a canonical serialization of all inputs).
- Performance target: a run over 50 agreements and 1,000,000 purchase lines completes
  in under 5 minutes on staging [PROPOSED TARGET]. Aggregation MAY be pushed to SQL as
  long as the engine receives exact pre-aggregated values and the trace still lists
  line-level drill-down queries; document the approach in an ADR.
- Also exposed as a CLI for concierge pilots (Phase 1).

### 4.7 Reconciliation runs
- User starts a run with a scope: all agreements, one supplier, or selected agreements,
  and a period range. Runs execute in the worker; one active run per tenant at a time
  (others queue); cancellable.
- A run snapshots: agreement version IDs, import batch IDs, baseline IDs, tolerance
  settings, engine version, input hashes, who started it, timestamps.
- Run results are immutable. Re-running creates a new run. Each agreement-period shows
  the **latest run** and lets the user open history and **diff** two runs (what changed:
  new lines, voided batch, version change, tolerance change).
- **Stale detection:** when any input of the latest run changes (new import overlapping
  the period, voided batch, new active version, credit allocation change), mark affected
  results stale and prompt to re-run.

#### 4.7.1 Credit matching and allocation
1. **Deterministic auto-match:** credit has an agreement reference (matching agreement
   external reference) AND a period (explicit dates or a period label that maps
   unambiguously) → allocate to that agreement-period.
2. **Suggestions:** same supplier, amount within tolerance of an outstanding expected
   amount, credit date between period end and period end + payment terms + 60 days
   [PROPOSED DEFAULT] → shown as suggestions with a confidence explanation. Never
   auto-applied.
3. **Manual allocation:** split one credit across several agreement-periods; sum of
   allocations ≤ credit amount; remainder stays unallocated and visible.
4. Allocations are audited, reversible, and changing them marks results stale.

#### 4.7.2 Reconciliation status per agreement-period
Tolerance `T = max(abs_tolerance, pct_tolerance × E)`; defaults `abs = $1.00`,
`pct = 0.5%` [PROPOSED DEFAULTS, tenant-configurable]. Due date = period end +
`payment_terms_days`.

| Status | Rule |
|---|---|
| `NEEDS_REVIEW` | Engine flagged review (takes precedence) |
| `NOT_EARNED` | `E = 0` and `C = 0` |
| `MATCHED` | `|V| ≤ T` |
| `OVERPAID` | `V > T` |
| `PENDING` | `V < −T` and today ≤ due date (today in the tenant timezone) |
| `SHORT_PAID` | `V < −T`, today > due date, `C > 0` |
| `MISSING` | `C = 0`, `E > 0`, today > due date |

Unallocated credits appear in an **Unmatched credits** queue.

### 4.8 Discrepancies and claims
- Every `SHORT_PAID` / `MISSING` / `OVERPAID` item appears in the discrepancy queue
  with filters (supplier, status, period, amount, age, assignee).
- **Claim** created from one or more discrepancies of the same supplier. Fields:
  claimed amount (defaults to `|V|`; editing requires a reason), assignee, due/follow-up
  date, supplier contact, channel (email/portal/phone/other), notes, attachments.
- Claim states: `draft → ready → submitted → acknowledged →
  resolved_recovered | resolved_partial | rejected | written_off`.
  `written_off` requires a reason and (with four-eyes) approval.
- **Recovered amounts** are recorded only by linking an actual credit (imported or
  manually entered with a reference and date). Never inferred.
- **Evidence pack (PDF + CSV appendix):** claim summary, agreement version terms and
  plain-English summary, calculation trace, eligible line summary (full line listing in
  the CSV appendix), credits received and allocations, variance, timeline of claim
  events, notes. Generated asynchronously; stored; downloadable via short-lived link.
- Reminders: follow-up date reached, claim aging thresholds (30/60/90 days).

### 4.9 Tier tracker and accruals
- For open periods: current `M`, next tier threshold, gap to next tier, days remaining,
  simple linear run-rate projection (clearly labelled **estimate**), and potential
  additional rebate if the next tier is reached.
- Alert when within X% of the next tier with Y days left [PROPOSED DEFAULTS 10% and 21
  days; per-user notification setting].
- Accrual view: expected-to-date per agreement for the open period at the current tier,
  labelled **estimate**, with "data as of" date (latest imported purchase date).

### 4.10 Dashboard, reports and exports
- **Dashboard KPIs:** identified open variance; recovered (confirmed) this year;
  open claims count and amount by aging bucket (0–30, 31–60, 61–90, 90+); results needing
  review; top suppliers by open variance; tier opportunities; data freshness per supplier
  (warn when the latest purchase date is older than 45 days [PROPOSED DEFAULT]).
- Every KPI tile links to the filtered list behind it.
- **Reports:** reconciliation summary by period; supplier statement (all agreements for
  one supplier); claims register; recovery report (identified vs recovered); agreement
  register; import history.
- Export every report as CSV and XLSX; key reports also as PDF.
- **Formula-injection protection:** in CSV/XLSX exports, any cell value starting with
  `=`, `+`, `-`, `@`, tab or carriage return is prefixed with a single quote, except
  genuine numeric cells written as typed numbers in XLSX.
- **Full data export (Owner):** ZIP of CSVs for all entities + original import files,
  generated asynchronously, link expires in 24 h [PROPOSED DEFAULT].

### 4.11 Notifications and email
- In-app notification centre (bell, unread count, mark read, link to object).
- Email via a provider behind an adapter interface; local development uses a mail
  catcher container. Every email has HTML and plain-text parts, from a verified domain.
- Transactional/security emails always send. Alert emails (tier proximity, claim
  reminders, run finished, credit overdue) follow per-user preferences with
  one-click unsubscribe links that work without login (signed token).
- Email types: invite, verify email, password reset, security notifications (4.1),
  import finished/failed, run finished/failed, new `MISSING` items detected, claim
  follow-up due, tier proximity, export ready, invoice issued, invoice overdue,
  account suspended, org deletion scheduled/cancelled.

### 4.12 Audit log
- Append-only `audit_events`: timestamp, tenant, actor (user / platform admin via
  support access / system), action, object type + ID, before/after summary (no raw
  imported rows, no secrets), request ID, IP, user agent.
- Tamper evidence: each event stores a hash of its content plus the previous event's
  hash per tenant (hash chain). A verification job checks the chain daily.
- The application DB role can INSERT but not UPDATE or DELETE audit rows.
- UI: filter by actor, action, object, date; export CSV. Retention: life of the org.

### 4.13 Settings
- Organization profile; timezone; fiscal year start.
- Security: require MFA for all; session idle timeout; allowed invite domains.
- Reconciliation: tolerances; default payment terms; data-freshness threshold.
- Approvals: four-eyes for agreement activation; four-eyes for write-offs.
- Import mapping templates (view, rename, delete, set default per supplier).
- Notifications (per user).
- Plan & usage (read-only), invoices list with PDF download.
- Data: full export; delete organization (Owner, step-up, type org name, 30-day grace
  period with cancel; then hard delete of DB rows and stored files; platform keeps a
  minimal deletion record: tenant ID, deletion date, who requested).

### 4.14 Plans, limits and invoice billing (no card payments)
- **Plan catalog** stored in DB (not hard-coded): name, monthly price (USD), limits
  (active agreements, users, import rows per month, storage), features. Seed with
  Pilot, Lite ($249), Growth ($499), Multi-location ($899) — prices are
  [PROPOSED DEFAULT] hypotheses, editable in the ops console.
- **Subscription** per tenant: plan, status (`pilot`, `active`, `past_due`,
  `suspended`, `cancelled`), term dates, custom limit overrides, billing contact.
- **Invoices:** sequential numbering per year (e.g. `RL-2026-0001`), seller details
  and payment instructions from ops settings (never hard-coded), line items, issue
  and due dates, status (`draft`, `issued`, `paid`, `void`), paid date + payment
  reference recorded manually. PDF generated server-side; emailed to the billing
  contact; visible to tenant Owners/Admins. Issued invoices are immutable; corrections
  = void + reissue. No tax computation in v1 ([OPEN] — see §15).
- **Lapse policy:** overdue → `past_due` banner; after a grace period (14 days
  [PROPOSED DEFAULT]) the operator MAY set `suspended` = read-only (view and export
  allowed; imports, runs, edits blocked). Data is never deleted because of non-payment.
- **Limit enforcement:** exceeding a limit blocks only the new action with a clear
  message and an upgrade contact; existing data and results stay accessible.
  Downgrades below current usage put excess items in read-only rather than deleting.

### 4.15 Operations console (platform admin)
- Lives under `/ops`, enforced server-side by the platform-admin role (not just hidden UI).
- Platform admins are created via a backend CLI command; MFA mandatory; optional IP
  allowlist via config.
- Features: tenants list and detail (metadata, plan, usage, health — no business data);
  create tenant and invite its first Owner; plans; subscriptions; invoices (create,
  issue, mark paid, void, resend); pilot/demo request inbox with status; feature
  flags per tenant; announcement banner; job monitor (queue depth, failed jobs, retry,
  dead-letter); audit of platform-admin actions.
- **Support access:** a tenant Owner/Admin grants access for a chosen duration
  (default 24 h, max 7 days) and scope (read-only default; read-write explicit).
  The tenant sees an active-access banner and can revoke anytime. Every action under
  support access is audited in the tenant's audit log, attributed to the platform admin.

### 4.16 Public marketing website
- Same Next.js app, public route group. Pages: Home, How it works, Features,
  Security, Pricing (plans shown; CTA "Request a pilot" — no checkout), About,
  Contact, Request a pilot, Blog (MDX; nav link hidden until at least one post exists),
  Privacy Policy, Terms of Service, Data Processing Addendum, Cookie notice,
  custom 404 and 500 pages.
- **Content integrity:** no invented customers, logos, testimonials, statistics,
  recoveries or certifications. Use clearly marked `[PLACEHOLDER]` blocks where real
  proof will go later. Legal pages are templates with a visible
  `[LEGAL REVIEW REQUIRED]` notice and MUST NOT ship to production until reviewed.
- **Request a pilot form:** name, work email, company, role, distributor segment,
  ERP/accounting system, approximate number of supplier agreements, message, consent
  checkbox. Server-side validation, honeypot field, rate limit, optional bot challenge
  behind a config flag. Stored in DB; operator notified by email; confirmation email
  to requester.
- **SEO:** per-page metadata, canonical URLs, `sitemap.xml`, `robots.txt`, Open Graph
  and social images, JSON-LD for Organization and the software product (no fake
  ratings), semantic headings, fast LCP. Target Lighthouse ≥ 90 for Performance,
  Accessibility, Best Practices and SEO on marketing pages [PROPOSED TARGET].
- **Analytics:** privacy-friendly, cookieless analytics on marketing pages only
  [OPEN: which provider]. No analytics or third-party scripts inside the app.
  If any non-essential cookie is ever added, a consent banner with equal-weight
  "Reject all" is required.

---

## 5. Data model (minimum)

Common columns on tenant tables: `id` (UUID; v7 if natively supported by the chosen
runtime, else v4), `tenant_id`, `created_at`, `updated_at` (UTC `timestamptz`),
`created_by`, `updated_by`, `row_version` (optimistic locking where updates happen).
Business dates are `date` (no timezone). Money `NUMERIC(18,4)` stored, results rounded
per agreement for presentation; rates `NUMERIC(9,6)`; quantities `NUMERIC(18,4)`.

Entities:
- Identity: `tenants`, `users`, `memberships(user, tenant, role, status)`, `sessions`,
  `mfa_factors`, `recovery_codes`, `email_tokens(type, hash, expires_at, used_at)`,
  `platform_admins`, `support_access_grants`.
- Suppliers: `suppliers`, `supplier_aliases(code unique per tenant)`, `supplier_contacts`,
  `products(sku, category)`.
- Agreements: `agreements`, `agreement_versions`, `agreement_components`,
  `agreement_tiers`, `eligibility_rules`, `agreement_attachments`, `approvals`.
- Imports: `import_batches(type, status, file_hash, storage_key, mapping_id, stats,
  voided_at)`, `import_mappings(versioned)`, `import_row_errors`, `purchase_lines`,
  `credit_lines`, `baselines`.
- Runs: `calculation_runs(scope, status, snapshot JSON, engine_version)`,
  `run_inputs(run, batch | version | baseline)`, `period_results(run, agreement_version,
  period, expected, components JSON, statuses, input_hash)`, `period_traces(JSONB)`,
  `credit_allocations`, `reconciliation_items`.
- Claims: `claims`, `claim_items(discrepancy refs)`, `claim_events`, `attachments`, `notes`.
- Platform: `notifications`, `notification_preferences`, `audit_events`, `plans`,
  `subscriptions`, `invoices`, `invoice_lines`, `invoice_sequences`, `pilot_requests`,
  `feature_flags`, `idempotency_keys`, `exports`, `jobs` (if the queue needs a
  durable record).

Indexes at minimum: `purchase_lines(tenant_id, supplier_id, basis dates)`,
`credit_lines(tenant_id, supplier_id, credit_date)`, `period_results(tenant_id,
agreement_version_id, period_start)`, unique dedupe keys from §4.5.4. Record the plan
for very large tenants (partitioning) in an ADR; do not implement partitioning in v1
unless load tests require it.

---

## 6. API conventions

- REST + JSON under `/api/v1`. OpenAPI generated by FastAPI is the contract; the
  frontend client is generated from it in CI and a drift check fails the build.
- Errors: RFC 9457 Problem Details with stable `code` values (catalogue in
  `docs/error-codes.md`), field-level `errors[]` for validation.
- Pagination: cursor-based (`cursor`, `limit` ≤ 200). Sorting and filtering only on
  whitelisted fields.
- Money and rates as decimal strings; dates ISO 8601 (`YYYY-MM-DD`); timestamps
  ISO 8601 UTC.
- `Idempotency-Key` on POSTs that create imports, runs, claims, invoices, exports.
  Keys stored 24 h per tenant + user + route.
- `ETag` / `If-Match` on agreements, versions, claims, settings.
- Long operations return `202` + `Location` of a job resource
  (`GET /api/v1/jobs/{id}` → status, progress, result link, error).
- `X-Request-ID` accepted or generated, returned, and logged end to end.
- Rate-limit responses use `429` with `Retry-After`.

---

## 7. Architecture and technology

| Layer | Choice | Notes |
|---|---|---|
| Frontend + marketing | Next.js (App Router), React, TypeScript strict | Route groups: `(marketing)`, `(auth)`, `(app)` under `/app`, `(ops)` under `/ops` |
| UI | Tailwind CSS + shadcn/ui (Radix primitives) | Design tokens, light/dark themes |
| Data fetching | TanStack Query; TanStack Table with row virtualization | |
| Forms | react-hook-form + zod | |
| Charts | Choose one maintained library in Phase 0 (ADR) | Accessible, themeable |
| Backend | Python (current stable supported by dependencies), FastAPI, Pydantic v2 | |
| ORM / migrations | SQLAlchemy 2.x, Alembic | Async vs sync decided in Phase 0 ADR |
| Database | PostgreSQL (current supported major) | RLS, `NUMERIC` money |
| Queue / cache / rate limits | Redis + a proven Python job library (RQ, Dramatiq, arq or Celery — choose in ADR) | Retries with backoff, dead-letter, idempotent jobs |
| Object storage | Storage adapter: local/MinIO for dev, Google Cloud Storage in cloud | Private buckets, signed URLs ≤ 15 min |
| PDF | Server-side HTML→PDF (e.g. WeasyPrint) with a custom URL fetcher that blocks all network access | Verify the library API before use |
| Email | Provider adapter; mail catcher locally; provider chosen in ADR | SPF, DKIM, DMARC on sending domain |
| Python tooling | uv (deps + lockfile), Ruff, mypy or pyright strict, pytest, hypothesis | Verify current tooling in Phase 0 |
| JS tooling | pnpm or npm with lockfile, ESLint, TypeScript, Vitest, Playwright, axe | |
| Observability | Structured JSON logs, Sentry (scrubbed), metrics, health endpoints | |
| Hosting | Docker images on GCP (Cloud Run, Cloud SQL, Memorystore, GCS, Secret Manager) | Alternatives priced in Phase 11 |

**Same-origin rule:** the browser only talks to the Next.js origin. `/api/*` is routed
to FastAPI (Next.js rewrites in dev; rewrites or load-balancer path routing in
production — decide in ADR). This removes CORS and keeps the session cookie
first-party with the `__Host-` prefix.

**Repository layout:**
```
backend/   app/{api,core,db,engine,services,workers,emails,pdf}, migrations/, tests/
frontend/  app/(marketing|auth|app|ops), components/, lib/, generated/, e2e/
infra/     terraform or deployment scripts (Phase 11)
docs/      SPEC.md, PHASES.md, PROGRESS.md, adr/, runbooks/, threat-model.md, error-codes.md
```

---

## 8. Security requirements

Target: OWASP Application Security Verification Standard (ASVS), current published
version, Level 2. Verify the current version in Phase 0 and produce a checklist
mapping in Phase 10.

### 8.1 Tenant isolation
- Every tenant table has `tenant_id NOT NULL` and an RLS policy restricting rows to
  `current_setting('app.tenant_id')` (or equivalent). The app DB role does not own
  tables and lacks `BYPASSRLS`.
- Tenant context is set per transaction from the authenticated membership, never
  from client input.
- Object storage keys are prefixed by tenant ID and every download path re-checks
  authorization before issuing a signed URL.
- Background jobs carry tenant ID and set the same context.
- Mandatory tests: for every endpoint, a user of tenant A cannot read, list, modify,
  or infer existence of tenant B objects (404, not 403, for other-tenant IDs).

### 8.2 Authorization
- Deny by default; each route declares a permission; object-level checks in services.
- A test walks all registered routes and fails if one lacks a permission declaration
  (explicit `public` marker allowed for marketing/auth endpoints).
- Platform-admin routes are a separate router with their own dependency and tests.

### 8.3 Web security
- CSRF: `SameSite=Lax` cookie + per-session CSRF token required in a header for all
  state-changing requests + `Origin`/`Referer` verification.
- Headers on all responses: strict nonce-based Content-Security-Policy (no
  `unsafe-inline` scripts), `Strict-Transport-Security` (with preload only after
  confirming all subdomains are HTTPS), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` minimal,
  `frame-ancestors 'none'`.
- No user-supplied HTML rendering. Markdown in notes rendered with a safe renderer
  and sanitizer, or stored as plain text.
- File downloads always `Content-Disposition: attachment` with sanitized filenames.

### 8.4 Data protection
- TLS everywhere; encryption at rest via the cloud provider; application-level
  encryption for TOTP secrets and any third-party credentials.
- Secrets only from environment / Secret Manager; startup fails if required secrets
  are missing; no secrets in images.
- Logs and error reports scrub cookies, auth headers, tokens, passwords, emails
  (hash or mask), and never include file contents or purchase/credit row values.
- Backups: automated daily + point-in-time recovery in production; restore tested
  on staging before launch and quarterly after.
- Data retention: active org data kept while subscribed; deletion per §4.13.

### 8.5 Supply chain and code
- Lockfiles committed; automated dependency update PRs; CI runs dependency
  vulnerability audits for Python and JS, secret scanning, static analysis (SAST),
  container image scanning. High/critical findings block merges unless an ADR
  documents an accepted risk.
- Containers run as non-root, read-only filesystem where possible, minimal base images.

### 8.6 Threat model
- Maintain `docs/threat-model.md` (STRIDE per component: browser, Next.js, API,
  worker, DB, Redis, storage, email, ops console). Update it each phase that adds
  an attack surface.

---

## 9. Edge-case catalogue (each needs a test)

| # | Area | Case | Required behaviour |
|---|---|---|---|
| 1 | Engine | `M` exactly equals a tier threshold | Apply `threshold_comparison` as configured; test both `gte` and `gt` |
| 2 | Engine | Zero eligible lines | Expected 0, status `NOT_EARNED`, trace explains why |
| 3 | Engine | Returns exceed purchases (`M < 0`) | No tier met; apply `negative_result` policy |
| 4 | Engine | Return dated in a later period than the purchase | Counts in the period of its own basis date (v1); documented in UI |
| 5 | Engine | Version change inside a period | `NEEDS_REVIEW` `VERSION_CHANGE_IN_PERIOD` until user resolves |
| 6 | Engine | Agreement starts mid-period | Clip period; `PARTIAL_PERIOD`; no threshold proration unless enabled |
| 7 | Engine | Growth with missing baseline | `NEEDS_REVIEW` `BASELINE_MISSING` |
| 8 | Engine | Growth with zero baseline | Apply `zero_baseline_policy` |
| 9 | Engine | Line eligible for two exclusive agreements | `STACKING_CONFLICT` on both |
| 10 | Engine | Cap lower than computed amount | Result = cap; status `CAPPED` |
| 11 | Engine | Result below minimum payout | 0; `BELOW_MINIMUM` |
| 12 | Engine | Input line order shuffled | Identical result and `input_hash` |
| 13 | Engine | Very large values (1e12 spend, 6-decimal rates) | No precision loss; no overflow |
| 14 | Engine | Line missing attribute used by a filter | Excluded with `ATTRIBUTE_MISSING`, counted |
| 15 | Engine | Basis date missing for the agreement's date basis | Line excluded with `DATE_BASIS_MISSING`; import warned earlier |
| 16 | Engine | Tiers with decreasing rates | Allowed with warning; results still per definition |
| 17 | Import | Ambiguous dates (03/04/2026) | User must confirm format; no silent guess |
| 18 | Import | UTF-8 BOM / Windows-1252 file | Detected; displayed; overridable |
| 19 | Import | Semicolon delimiter, comma decimals | Supported via explicit format choice |
| 20 | Import | Amounts `(1,234.56)` and `1234.56-` | Parsed as negative when that style is chosen |
| 21 | Import | SKU `00123` and `1.23E+11` | Leading zeros kept; scientific notation warned |
| 22 | Import | Duplicate rows within one file | Second occurrence reported as duplicate |
| 23 | Import | Same file uploaded twice | File-hash warning; explicit confirmation required |
| 24 | Import | Unknown supplier codes | Grouped error with create/map actions |
| 25 | Import | Non-USD currency value | Row error |
| 26 | Import | Row with extra columns / ragged row | Reported, not shifted |
| 27 | Import | 1,000,000-row file | Streams within memory budget; progress visible; completes within target |
| 28 | Import | XLSX zip bomb / external entity | Rejected safely before full load |
| 29 | Import | Worker crashes mid-commit | Transaction rolled back or batch resumable; never half-committed silently |
| 30 | Import | Batch voided after runs used it | Runs marked stale; not altered |
| 31 | Recon | One credit pays three quarters | Manual split allocation; remainder tracked |
| 32 | Recon | Two credits for one period | Summed into `C` |
| 33 | Recon | Credit before period end | Allowed (prepayment); shown as early |
| 34 | Recon | Credit with negative amount (reversal) | Allowed; reduces `C`; flagged |
| 35 | Recon | Variance within tolerance | `MATCHED` |
| 36 | Recon | Day-of-due-date boundary in tenant timezone | `PENDING` through the due date, `MISSING`/`SHORT_PAID` from the next day |
| 37 | Claims | Recovered more than claimed | Allowed; status `resolved_recovered`; overage noted |
| 38 | Claims | Self-approval of write-off with four-eyes on | Blocked, including after role change |
| 39 | Auth | Concurrent sessions across devices | Allowed; each listed and revocable |
| 40 | Auth | Password reset while sessions active | All sessions revoked |
| 41 | Auth | Invite to an email that already has an account | Adds membership after acceptance; no duplicate user |
| 42 | Tenancy | User removed from org mid-session | Next request in that org returns 403/404; session for other orgs unaffected |
| 43 | Concurrency | Two users edit the same draft | Second save gets 412 with a reload prompt |
| 44 | Concurrency | Two runs started at once | Second queues; no interleaved results |
| 45 | Billing | Plan downgrade below usage | Excess becomes read-only; nothing deleted |
| 46 | Billing | Tenant suspended | Read-only; exports still allowed |
| 47 | Export | Cell starting with `=HYPERLINK(` | Neutralized |
| 48 | Time | Fiscal year starting in a month other than January | Quarters align to fiscal start |
| 49 | Time | Leap day period boundaries | Correct period assignment |
| 50 | Deletion | Org deletion during grace period cancelled | Fully restored; audited |

---

## 10. Frontend and UX standards

- **Aesthetic:** calm, precise finance tool. Information-dense but uncluttered.
  Distinctive but restrained brand (decide palette and typography in Phase 5 with a
  short design brief). Avoid generic template look.
- **Typography:** one UI typeface with tabular numerals for all figures.
- **Numbers:** right-aligned; currency `$1,234.56`; negatives `−$1,234.56` plus colour;
  percentages with fixed decimals per context; dates displayed `MMM D, YYYY` by default
  with user preference.
- **Tables:** sorting, filtering, column visibility, saved views per user, sticky header,
  row virtualization above 500 rows, CSV export of the current view, keyboard navigation.
- **States:** skeleton loading, empty states with a next action, inline error with
  retry, permission-denied explanation, stale-data banner.
- **Navigation:** sidebar + breadcrumbs, org switcher, global search (suppliers,
  agreements, claims, imports), command palette (Cmd/Ctrl+K), keyboard shortcuts help.
- **Explain drawer:** on any expected amount: formula steps, tier reached, measure,
  eligible/excluded counts with reasons, link to the line listing, run and engine version.
- **Responsiveness:** marketing pages fully responsive from 360 px; app optimised for
  ≥ 1280 px and fully usable at 1024 px; read-only views usable on mobile.
- **Accessibility:** WCAG 2.2 AA; automated axe checks in CI; manual keyboard pass per phase.
- **Themes:** light and dark, respecting system preference, user override.
- **Copy:** plain English, finance-literate, no hype. Error messages say what happened
  and what to do next.

---

## 11. Testing strategy and quality gates

| Layer | Requirement |
|---|---|
| Engine | ≥ 30 golden fixtures with hand calculations covering every component type and §9 engine cases; property-based tests (order invariance, line-split invariance, ineligible-line invariance, cap respected, monotonic non-decreasing `E` in `M` when tier rates are non-decreasing, incremental ≤ all-units for same ascending tiers); ≥ 95% line + branch coverage |
| Backend | Unit + integration with real Postgres and Redis containers; ≥ 85% coverage overall; authorization matrix; cross-tenant suite; import edge-case fixture files for every §9 import case |
| API contract | OpenAPI snapshot + generated client drift check |
| Frontend | Component tests for complex widgets (rule builder, mapping wizard, tables); Playwright E2E for: login + MFA, invite, import wizard, agreement creation, run, explain, claim lifecycle, invoice view, pilot request form |
| Accessibility | axe on every route in E2E; zero serious/critical violations |
| Performance | Load tests for 1M-row import and a 50-agreement run; p95 API latency < 500 ms for list endpoints at 100k rows [PROPOSED TARGET] |
| Security | Dependency, secret, SAST and container scans in CI; manual review checklist in Phase 10 |

A single command (defined in Phase 0) runs lint, type checks and all non-E2E tests.
CI runs that plus E2E on every pull request.

---

## 12. Observability and operations

- JSON logs with timestamp, level, request ID, tenant ID, user ID (IDs only), route,
  latency, status. No PII beyond IDs; no row data.
- Error tracking with scrubbing; release tagging.
- Metrics: request rate/latency/error by route, job durations and failures, queue depth,
  import rows/sec, run durations.
- Health: `/healthz` (process alive) and `/readyz` (DB, Redis, storage reachable).
- Alerts [PROPOSED]: error rate > 2% for 5 min, failed jobs > 0 in dead-letter,
  queue depth growing for 15 min, DB storage > 80%, backup failure, audit hash-chain
  verification failure.
- Runbooks in `docs/runbooks/`: deploy, rollback, restore from backup, rotate secrets,
  re-run failed jobs, handle a suspected data leak, tenant deletion, support access.

---

## 13. Environments and deployment

- **Local:** Docker Compose with Postgres, Redis, mail catcher, S3-compatible storage
  (or local filesystem adapter); seed script with a demo tenant and realistic fake data.
- **Staging** and **production** on GCP, separate projects, separate secrets, separate
  buckets. Production data never copied to staging.
- Infrastructure as code. CI deploys to staging automatically from the main branch;
  production deploys require manual approval.
- CI authenticates to GCP with keyless workload identity federation, not service
  account key files.
- Database migrations run as a separate release step before new code serves traffic;
  migrations are backward-compatible for one release (expand/contract).
- The background worker needs an always-available process; evaluate Cloud Run options
  vs a small VM and price both in Phase 11. **No provisioning without founder approval.**
- DNS, TLS, SPF/DKIM/DMARC for the sending domain.

---

## 14. Out of scope for v1

Live ERP/accounting integrations · any AI/LLM feature · supplier portal · automated
emails to suppliers · general-ledger posting · multi-currency · SSO/SAML ·
native mobile apps · card/self-serve checkout · public API for customers ·
SOC 2 or other certification claims.

Design so these can be added later (adapters, clean service boundaries), but do not build them.

---

## 15. Open questions (ask the founder; do not decide alone)

1. [OPEN] Final product name and domain.
2. [OPEN] Transactional email provider.
3. [OPEN] Marketing analytics provider (cookieless).
4. [OPEN] Tax treatment on invoices (Pakistan export of services, US state sales tax on
   SaaS) — needs an accountant; v1 invoices show no tax line until confirmed.
5. [OPEN] How invoice payments will be received (bank/payment provider details for
   the invoice footer).
6. [OPEN] Legal entity name and address for invoices and legal pages.
7. [OPEN] Whether returns should optionally net against the original purchase period
   (v1: own basis date only).
8. [OPEN] Which ERP export formats to prioritise for built-in mapping templates
   (collect from pilot customers).
9. [OPEN] Hosting choice after the Phase 11 cost comparison.
