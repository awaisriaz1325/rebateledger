# RebateLedger — Build Phases

Rules for every phase (from `CLAUDE.md`): plan first and wait for approval; build;
make every acceptance criterion pass; run the full check suite; write the
end-of-phase report; STOP and ask before the next phase.

"Check suite" below means the single command defined in Phase 0 that runs lint,
type checks and all non-E2E tests, plus E2E where the phase says so.

| Phase | Name | Outcome |
|---|---|---|
| 0 | Foundations & decisions | Repo, tooling, CI, local stack, ADRs, threat model draft |
| 1 | Rebate engine + pilot CLI | Correct, tested engine usable for paid concierge pilots |
| 2 | Backend core: identity, tenancy, security | Auth, MFA, sessions, RBAC, RLS, audit log |
| 3 | Suppliers, agreements, imports | Versioned agreements, approvals, robust import pipeline |
| 4 | Runs, reconciliation, claims | Full backend workflow from import to recovered claim |
| 5 | Frontend foundation | Design system, app shell, auth screens, settings |
| 6 | Frontend product screens | Every workflow usable in the browser |
| 7 | Reports, exports, evidence packs | PDFs, safe CSV/XLSX, full data export |
| 8 | Billing (invoices), ops console, support access | Operate the business from inside the product |
| 9 | Marketing website | Public site, SEO, legal templates, pilot request |
| 10 | Hardening | Security review, load, accessibility, resilience |
| 11 | Deployment & launch | Staging, production, monitoring, runbooks, launch checklist |

---

## Phase 0 — Foundations & decisions

**Goal:** a clean, reproducible monorepo where quality checks run with one command.

**Do:**
1. Verify current stable versions of Python, Node.js, Next.js, FastAPI, Pydantic,
   SQLAlchemy, Alembic, PostgreSQL, Redis and the tooling in SPEC §7 from official
   sources. Record them with source links in `docs/adr/0001-versions.md`.
2. Write ADRs (one decision each, with options considered): sync vs async SQLAlchemy;
   job queue library; chart library; PDF library; email provider shortlist (decision
   stays [OPEN]); `/api` routing in production; package managers.
3. Scaffold `backend/`, `frontend/`, `infra/`, `docs/` per SPEC §7. Strict type
   checking, linters and formatters configured for both.
4. Docker Compose for Postgres, Redis, mail catcher and S3-compatible storage (or a
   filesystem adapter, per ADR). Health checks on every service.
5. A task runner (Makefile or equivalent) with: setup, check (lint + types + tests),
   dev stack up/down, backend tests, frontend tests, e2e, migrate, new migration, seed.
6. CI pipeline: check suite, dependency audit, secret scan, SAST. Must pass on the
   empty scaffold.
7. `.env.example` files with dummy values; `.gitignore` covering secrets and builds.
8. Draft `docs/threat-model.md` and `docs/error-codes.md`.
9. Fill in the **Commands** section of `CLAUDE.md` with the real, tested commands.

**Acceptance criteria:**
- Fresh clone → setup → check passes with zero warnings treated as errors.
- Compose stack starts and all health checks are green.
- CI is green on the scaffold.
- ADRs exist for every choice listed above.

---

## Phase 1 — Rebate engine + pilot CLI

**Goal:** a correct, explainable engine the founder can use immediately for paid
concierge pilots, before any web UI exists.

**Do:**
1. Build `backend/app/engine/` exactly per SPEC §4.4.2–4.4.4 and §4.6: value objects,
   periods (incl. fiscal alignment and custom periods), eligibility, all seven
   component types, order of operations, statuses, reason codes, trace, `input_hash`,
   `ENGINE_VERSION`.
2. Reconciliation logic per SPEC §4.7.1 (deterministic matching + manual allocation
   input) and §4.7.2 statuses, also pure.
3. Golden fixtures: ≥ 30 YAML scenarios with hand calculations in comments, covering
   every component type and every engine row in SPEC §9.
4. Property-based tests listed in SPEC §11.
5. **Pilot CLI:** reads an agreements YAML file, purchases CSV, credits CSV and optional
   baselines CSV (with a mapping config file for column names and formats), and writes:
   results CSV, discrepancies CSV, a human-readable HTML report with traces, and a
   summary in the terminal. Formula-injection-safe CSV output.
6. Document the agreements YAML format with three worked examples in
   `docs/pilot-cli.md`, plus sample input files.

**Acceptance criteria:**
- Engine coverage ≥ 95% line and branch; all fixtures and property tests pass.
- Shuffling input lines produces byte-identical results.
- The CLI runs end to end on the sample data and the founder can follow the trace
  for at least one result and reproduce it by hand.
- No imports from web, DB or storage modules inside `engine/` (enforced by a test).

**Report extra:** list every place the spec forced `NEEDS_REVIEW`, so the founder
knows which questions to ask pilot customers.

---

## Phase 2 — Backend core: identity, tenancy, security

**Goal:** a secure multi-tenant foundation every later feature sits on.

**Do:**
1. Schema + migrations for identity and tenancy entities (SPEC §5).
2. Separate DB roles: migration owner vs application role (no `BYPASSRLS`); RLS
   policies on every tenant table; per-transaction tenant context.
3. Auth flows from SPEC §4.1: login, sessions, MFA enrollment and challenge, recovery
   codes, forgot/reset password, email verification, invites, change password/email,
   session list/revoke, step-up re-authentication, breached-password check, rate limits,
   lockout, security notification emails.
4. Memberships, roles, permission mapping (SPEC §2), org switcher support.
5. Audit log with hash chain and verification job (SPEC §4.12).
6. Cross-cutting: Problem Details errors, request IDs, structured logging with
   scrubbing, security headers, CSRF protection, idempotency keys, optimistic locking
   helpers, health endpoints, job framework with retries and dead-letter.
7. Platform-admin bootstrap CLI command (creates a platform admin and forces MFA setup).
8. Email adapter + templates for this phase's emails (mail catcher locally).

**Acceptance criteria:**
- Authorization matrix test passes for every route; the route-walker test fails
  if a route has no permission declaration.
- Cross-tenant suite proves isolation, including direct SQL as the app role.
- Security tests: user enumeration timing/response parity, lockout, session rotation,
  revocation on password change, CSRF rejection, header presence.
- Threat model updated.

---

## Phase 3 — Suppliers, agreements, imports

**Goal:** customers' real data and rules can get into the system safely.

**Do:**
1. Suppliers, aliases, contacts, products, supplier merge (SPEC §4.3).
2. Agreements, versions, components, tiers, eligibility, attachments; lifecycle,
   immutability of active versions, non-overlap validation, approvals with four-eyes
   (SPEC §4.4). Deterministic plain-English summary generator. Dry-run preview endpoint
   using the Phase 1 engine.
3. Import pipeline (SPEC §4.5): upload, detection, mapping templates, explicit format
   choices, preview validation, background full validation, error report, commit modes,
   dedupe, file hash warnings, void, progress, file security controls.
4. Plan-limit checks hooked into creation endpoints (limits read from the
   subscription; plans seeded).
5. Seed script producing a realistic demo tenant (fake suppliers, agreements and
   ~100k purchase lines).

**Acceptance criteria:**
- A fixture file exists and passes for every import row in SPEC §9.
- A 1,000,000-row CSV imports within the memory budget agreed in the plan, with live
  progress; worker kill mid-commit leaves no partial batch.
- Active versions cannot be edited via any endpoint (tested).
- Four-eyes self-approval is impossible (tested, including role change mid-flow).

---

## Phase 4 — Runs, reconciliation, claims

**Goal:** the complete backend workflow works end to end through the API.

**Do:**
1. Calculation runs: scope, snapshot, queueing (one active per tenant), cancel,
   immutable results, traces, run diff, stale detection (SPEC §4.7).
2. Credit matching: deterministic auto-match, suggestions, manual split allocation,
   unmatched queue.
3. Reconciliation statuses with tenant-timezone due dates.
4. Discrepancy queue and claims lifecycle with events, attachments, recovered-amount
   linking to real credits, reminders (SPEC §4.8).
5. Tier tracker and accrual estimates (SPEC §4.9).
6. In-app notifications and alert emails with preferences and signed unsubscribe
   links (SPEC §4.11).
7. Dashboard aggregate endpoints (SPEC §4.10 KPIs).

**Acceptance criteria:**
- API-level scenario test: create supplier → agreement → import purchases and credits
  → run → see `SHORT_PAID` → open claim → record recovering credit → dashboard shows
  identified and recovered correctly.
- Run over the 50-agreement / 1M-line dataset meets the performance target or the
  report explains the gap and proposes options.
- Stale detection fires for every trigger listed in SPEC §4.7.

---

## Phase 5 — Frontend foundation

**Goal:** a distinctive, accessible design system and a working app shell.

**Do:**
1. Short design brief (positioning, tone, palette, type, density) for founder approval
   **before** building components.
2. Design tokens, light/dark themes, core components (buttons, inputs, selects, date
   pickers, dialogs, drawers, toasts, tabs, badges for every status, data table with
   virtualization, money/percent/date formatters, empty/error/loading patterns).
3. Generated API client wired with TanStack Query; same-origin `/api` routing;
   cookie forwarding in server components.
4. App shell: sidebar, breadcrumbs, org switcher, global search, command palette,
   notification bell, user menu.
5. Auth screens for every Phase 2 flow, including MFA enrollment with QR code and
   recovery codes download.
6. Settings screens (SPEC §4.13) except billing.

**Acceptance criteria:**
- Founder approved the design brief.
- Playwright: login + MFA, invite acceptance, session revoke, settings change.
- axe: zero serious/critical violations on all routes; full keyboard pass recorded.

---

## Phase 6 — Frontend product screens

**Goal:** every workflow in SPEC §4.3–4.10 is usable in the browser.

**Do:** onboarding checklist; dashboard; suppliers list/detail/merge; agreements list,
rule builder with live summary and dry-run preview, version history and diff,
approvals; import wizard (upload → detect → map → formats → preview → commit →
result, saved templates, error report download, void); runs list/detail/diff;
results with explain drawer; unmatched credits and allocation UI; discrepancy queue;
claims list/detail/lifecycle; tier tracker; notification centre; stale-data banners.

**Acceptance criteria:**
- Playwright covers: import wizard incl. an ambiguous-date file, agreement creation
  with preview, run, explain drawer, allocation split, claim lifecycle to recovered.
- Tables stay responsive with 100k rows (virtualization verified).
- No screen lacks loading, empty, error and permission-denied states.

---

## Phase 7 — Reports, exports, evidence packs

**Do:** report endpoints and screens (SPEC §4.10); CSV/XLSX exports with formula
neutralization; PDF generation with network-blocked fetcher; claim evidence pack;
full data export ZIP; signed short-lived download links; export history.

**Acceptance criteria:**
- Malicious-cell fixture (`=HYPERLINK(...)`, `+cmd`, `@SUM`) is neutralized in every
  export format.
- PDF renderer cannot fetch any external URL (tested).
- Evidence pack totals reconcile exactly with the on-screen result.

---

## Phase 8 — Billing (invoices), ops console, support access

**Do:** plan catalog, subscriptions, limit enforcement, lapse states, invoice
creation/issue/void/mark-paid with sequential numbering and PDF, invoice emails and
reminders, tenant billing view (SPEC §4.14); ops console with tenants, pilot request
inbox, feature flags, announcements, job monitor; support access grants with banner,
revoke and audit (SPEC §4.15).

**Acceptance criteria:**
- Invoice numbers never collide or skip under concurrent issuing (tested).
- Suspended tenant is read-only but can export (tested).
- Platform admin cannot read tenant business data without an active grant (tested).

---

## Phase 9 — Marketing website

**Do:** all pages in SPEC §4.16; pilot request form with validation, honeypot and rate
limits; SEO metadata, sitemap, robots, social images, JSON-LD; legal templates with
`[LEGAL REVIEW REQUIRED]`; cookieless analytics behind config; 404/500 pages.

**Acceptance criteria:**
- Lighthouse targets met on Home, Pricing and Security pages (report actual scores).
- Copy audit: no invented proof (customers, numbers, testimonials, certifications).
- Pilot request reaches the ops inbox and sends both emails.

---

## Phase 10 — Hardening

**Do:**
1. OWASP ASVS Level 2 checklist mapped to evidence (code, tests, config).
2. Manual security review: authz fuzzing over all routes with other-tenant IDs,
   IDOR sweep, upload abuse, CSRF, header scan, dependency and container scans clean.
3. Load tests (SPEC §11) with results recorded.
4. Resilience: kill worker during import, run and PDF generation; restart Redis and DB;
   confirm jobs resume or fail cleanly with clear user messages.
5. Accessibility audit pass; performance budgets met.
6. Backup and restore rehearsal on a staging-like environment.

**Acceptance criteria:** all High/critical findings fixed or accepted in an ADR by
the founder; reports committed under `docs/hardening/`.

---

## Phase 11 — Deployment & launch

**Do (prepare, then wait for approval before any command that creates cost):**
1. Hosting comparison with monthly cost estimates (GCP managed services vs a lean
   alternative), recommendation, and risks.
2. Infrastructure as code for staging and production; secrets in Secret Manager;
   keyless CI auth; private DB networking; backups + PITR; buckets private.
3. CI/CD: auto-deploy to staging, manual approval for production, migration step,
   rollback procedure.
4. Monitoring, alerts and dashboards per SPEC §12; uptime check.
5. DNS, TLS, email authentication (SPF, DKIM, DMARC).
6. Runbooks (SPEC §12) and a launch checklist covering legal review done, [OPEN] items
   resolved, restore tested, alerts tested, demo tenant removed from production.

**Acceptance criteria:** staging smoke tests pass; founder approves production
deploy; production smoke tests pass; launch checklist signed off by the founder.
