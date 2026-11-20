# Progress log

Newest entry first. One entry per working session.

<!--
Template:

## YYYY-MM-DD — Phase N: <name>
- Changed:
- Decisions (ADRs):
- Open questions:
- Next step:
-->

## 2026-11-20 — Go-live inputs: domain, production VM, deploy rework
- Changed: production domain `rebateledger.imageme.tech` (one host for the app and the public
  pages). Fixed a defect: the web image never received `NEXT_PUBLIC_SITE_URL`, so sitemap,
  robots and canonical links would have pointed at localhost (now a required build argument).
- Decision (founder, ADR 0020): production on `opspilot-production`, resized to e2-standard-2.
  Deploy reworked: images built on the devbox and shipped over IAP (`infra/prod/deploy.sh`,
  `infra/prod/vm-release.sh`), compose from a pinned CLI container, OpsPilot's nginx via
  `~/nginx-extra` (`infra/prod/nginx/`), secrets in `/var/lib/rebateledger`, memory caps.
- Verified locally: full `deploy.sh` run against a stand-in VM (fake gcloud), all 8 services up;
  HTTPS through nginx 1.28 with the real server blocks; client IP forwarded, spoofed
  `X-Forwarded-For` discarded; rollback mode; idle memory ~590 MB.
- Resized `opspilot-production` to e2-standard-2 (founder's go-ahead): ~2 min down, all 28
  containers back, 5.1 GB available. Static IP is 34.135.27.193 (OpsPilot's docs are outdated).
- Open: email provider (ADR 0006); bucket, uptime check, DNS (`infra/prod/gcloud-prepared.md`).

## 2026-11-20 — Launch readiness: restore drill, backup fixes, web hardening
- Restore drill (local, `infra/scripts/restore_drill_local.sh`, prod image and backup command):
  passed, point-in-time restore in 3 s. It found two High production defects, both fixed and then
  verified by running the real prod `postgres` + `backup` services: WAL archiving always failed
  (root-owned archive volume) and base backups always failed (no replication access).
- Web container: verified running read-only, as uid 1000, with no capabilities; compose updated.
- `make audit` passes again (picomatch advisory no longer applies; minimatch moderate remains in
  lint tooling).
- Dedicated VM: commands prepared in infra/prod/gcloud-prepared.md §5, not run.
- Open: domains, email provider, running the prepared cloud commands, the production restore drill.

## 2026-11-19 — v1.3 Phase 29: advisor portfolio view
- Changed: GET /api/v1/me/portfolio and /app/portfolio ("All organizations", linked next to the
  organization switcher when a user has two or more): per active membership, the role, identified
  open variance, short-paid and missing counts, open claims and the last successful run; "Open"
  switches organization. Each organization is read in its own tenant session (RLS); none spans
  tenants. An organization that requires two-factor sign-in is locked (no figures) for a user
  without it, matching switch_tenant. Throttled with ratelimit.heavy.
- Decisions (ADRs): none beyond the plan.
- Next step: v1.3 plan complete; founder review, push, and go-live items.

## 2026-11-19 — v1.3 Phase 28: effective rebate rate
- Changed: report `rebate_rate` (CSV/XLSX/PDF; default last 12 months): per supplier purchases,
  rebate earned and received, earned % and received % of purchases, earned % for the same dates a
  year earlier and the change in points, periods needing review; dashboard tile "Rebate earned, %
  of purchases" (last 12 months) linking to it; Reports page accepts `?report=<key>`.
- Decisions (ADRs): by supplier only, not by category (the plan said "and category where products
  exist"): rebates are calculated per agreement-period, so a category split would need an invented
  allocation rule. Periods needing review are counted, never included in the rate.
- Next step: Phase 29 (advisor portfolio view).

## 2026-11-18 — v1.3 Phase 27: dispute tracking on claims
- Changed: claim status `disputed` (from submitted/acknowledged; to acknowledged, resubmitted,
  resolved, rejected, written off) with a required reason (data mismatch, eligibility, rate or
  tier, timing, other), an optional amount the supplier accepts, and the date (migration 0014);
  the dispute is written into the claim history (and so the evidence pack); claims register gains
  dispute reason, supplier-accepted amount and days in dispute; claim page dispute dialog + notice.
- Decisions (ADRs): the latest dispute is kept after it ends (history); days in dispute count only
  while the claim is still disputed.
- Note: E2E pilot-form test hit its 5/hour per-IP limit after repeated local runs; local Redis
  counters cleared, full suite then green. Not a product issue.
- Next step: Phase 28 (effective rebate rate).

## 2026-11-18 — v1.3 Phase 26: supplier scorecard
- Changed: report `supplier_scorecard` (CSV/XLSX/PDF; default last 12 months): periods owed and
  due, rebate owed vs received %, paid-in-full-on-time %, average days late (paid date = latest
  linked credit), short-paid and missing counts, open claims, recovered % of claimed; "Scorecard"
  tab on supplier pages (reuses the report preview; no new endpoint).
- Decisions (ADRs): not-yet-due, not-earned and needs-review periods are excluded; a fully paid
  period with no linked credit date counts as on time.
- Next step: Phase 27 (dispute tracking).

## 2026-11-18 — v1.3 Phase 25: claim-deadline alerts
- Changed: new alert type `claim_deadline` (daily job `claim_deadlines`, 16:00 UTC): short-paid or
  missing periods whose agreement claim deadline is 0–30 days away; once per period; owners, admins,
  analysts; switchable per channel. Weekly digest now includes a deadlines section and is sent when
  there are deadlines even without tier opportunities.
- Decisions (ADRs): recipients = digest roles (owner/admin/analyst); time-barred periods are not
  alerted (the recovery audit flags them).
- Next step: Phase 26 (supplier scorecard).

## 2026-11-18 — v1.3 Phase 24: getting-started checklist
- Changed: dashboard API returns `getting_started` (7 steps derived from data: suppliers, purchases,
  agreements, activation, first successful run, credits, review = a claim exists or a run found no
  shortfall); the existing dashboard card now uses it (one request instead of five; voided imports
  and failed runs no longer count; counts shown; dismissal kept).
- Decisions (ADRs): none (plan docs/PHASES-v1.3.md approved by founder 2026-11-18).
- Next step: Phase 25 (claim-deadline alerts).

## 2026-11-18 — Security audit, penetration tests, v1.3 plan
- Changed: open redirect after sign-in fixed (safeNext); OpenAPI schema not served in production;
  production containers hardened (no capabilities, no-new-privileges, read-only root for api/worker/
  scheduler, XDG cache in /tmp); Redis password; per-user throttle on expensive reads;
  backend/tests/api/test_pentest.py (cross-tenant ids in bodies/queries, session and CSRF abuse).
- Report: docs/security/2026-11-18-audit.md. Plan: docs/PHASES-v1.3.md (Phases 24–29, awaiting approval).
- Open questions: approve v1.3; dev-tool advisories in make audit; dedicated VM; restore drill.
- Next step: founder approval of v1.3.

## 2026-11-17 — Fixes after v1.2 review
- Fixed (each with a failing test first): accrual journal now accrues programs paid through a
  buying group net of the group fee; bulk agreement import reports over-long text per row (was a
  500) and never echoes a whole cell; supplier statements from the paying buying group match the
  member's program and compare net of the fee; flaky MFA test helper (code issued for the oldest
  accepted step just before a 30 s boundary).
- Security scans: bandit clean, gitleaks clean; pnpm audit fails on two dev-tooling advisories
  (picomatch ReDoS: no fixed release; minimatch: fix released 2026-11-16, too new to adopt).
- Open questions: accept the two dev-only advisories in the audit gate, or wait for fixes.

## 2026-11-17 — v1.2 Phase 23: buying-group payout reconciliation
- Changed: suppliers.group_fee_pct and agreements.paid_via_group_id (migration 0013); a program
  paid through a group accepts the group's credits (auto-match by reference + period, or manual
  allocation) and reconciles against expected × (1 − fee), rounded half-up once; report
  `group_payouts` (earned, fee, expected from group, received, variance); fee field on the group's
  supplier page; "Paid through buying group" on the agreement page. Engine unchanged.
- Decisions (ADRs): ADR 0019 D3 (one fee % of rebate per group).
- Open questions: D2; real group statement to confirm the fee rule.
- Next step: v1.2 plan complete; Phase 11 go-live steps remain with the founder.

## 2026-11-17 — v1.2 Phase 20: look-back recovery audit
- Changed: /app/recovery-audit (coverage check → calculation run → identified shortfalls → one claim
  per supplier); API /api/v1/recovery-audit{,/coverage,/claims}; report `recovery_audit` (CSV/XLSX/PDF,
  "identified, not recovered" printed on every PDF page); agreement field `claim_deadline_days`
  (migration 0012) flags "may be time-barred" without dropping anything.
- Decisions (ADRs): ADR 0019 — D1 free in pilots (no pricing change); D3 group fee = % of rebate per group.
- Open questions: D2 (pilot ERP files); statement differences claimable before due date?
- Next step: Phase 23 (buying-group payout reconciliation) per ADR 0019.

## 2026-11-17 — v1.2 Phase 22: supplier statement compare
- Changed: import type `statements` (migration 0011: statement_lines + RLS, import_type CHECK widened);
  /app/statements compares their rebate with ours per agreement and full period (agrees /
  purchases differ / rate or tier differs / not calculated / needs review / unconfirmed / unmatched);
  assign or confirm the agreement; formula-safe CSV of differences; evidence packs now include the
  supplier's statement (supplier-statement.csv + PDF section).
- Decisions (ADRs): none. Claims still follow the existing rule (short-paid or missing periods only);
  a statement difference before payment is due is shown and exported, not claimed.
- Open questions: D1–D3; whether statement differences should be claimable before the due date.
- Next step: Phase 23 needs D3; Phase 20 needs D1.

## 2026-11-17 — v1.2 Phase 21: bulk agreement import
- Changed: /app/agreements/import (template, column guide, preview, create drafts);
  API /api/v1/agreements/bulk{,/preview,/columns,/template}; service app/services/agreement_bulk.py.
  Drafts only, all-or-nothing, same VersionTermsIn + engine validation as the editor; re-import of
  identical terms is "unchanged"; existing reference → new draft version.
- Decisions (ADRs): none. Deviation from the plan text: a dedicated synchronous endpoint (≤1 MB,
  ≤2,000 rows) instead of a new type in the purchase-line import pipeline; no agreement-to-CSV export yet.
- Open questions: D1–D3.
- Next step: Phase 20 after D1, else Phase 22 (supplier statement compare).

## 2026-11-17 — v1.2 Phase 19: accrual export formats (NetSuite, Acumatica)
- Changed: accrual journal export formats `netsuite` (External ID grouping) and `acumatica`
  (GL301000 detail columns, 0.00 not blank); format hints on the Accruals page.
- Decisions (ADRs): none. Column choices cite the vendor docs in code comments; both UNVERIFIED
  until a customer imports one (Acumatica also needs an import scenario on their side).
- Open questions: D1–D3 (docs/PHASES-v1.2.md).
- Next step: Phase 20 (look-back recovery audit) needs D1 first; Phase 21 can start without it.

## 2026-11-17 — v1.2 Phase 18: positioning and focus
- Changed: marketing page /changing-erp (Epicor dates verified against CIO.com, 7 Jan 2026; footer + sitemap);
  SPA claims labelled Beta; Deal modelling removed from the sidebar and linked from Agreements ("Model a deal").
- Decisions (ADRs): none (plan docs/PHASES-v1.2.md approved by founder).
- Open questions: D1 recovery-audit pricing, D2 pilot ERP files, D3 buying-group fee rules.
- Next step: Phase 19 (NetSuite and Acumatica accrual export formats) after approval.

## 2026-11-17 — Research: feature, competitor and market review
- Changed: docs/research/2026-11-17-feature-review.md (no code).
- Decisions (ADRs): none; recommendations only.
- Open questions: look-back audit pricing; pilot ERP samples; customer (payable) rebates; SFTP imports; approvals default.
- Next step: founder picks from the Top 5.

## 2026-11-17 — Phase 11: deployment preparation (shared VM)
- Changed: `backend/Dockerfile` (Pango/HarfBuzz for PDFs, `--no-server-header`, proxy headers
  trusted only from the stack network), `frontend/Dockerfile` (`RL_API_ORIGIN` build arg),
  `infra/prod/` (compose stack, WAL archiving + nightly base backup + GCS mirror, Caddy
  snippet, `deploy.sh`, prepared gcloud commands), runbooks (deploy, restore), launch
  checklist. Both images built and smoke-run locally (web /login 200; WeasyPrint 70.0 loads).
  Nothing deployed; no cloud command run.
- Decisions (ADRs): 0018 — production on the shared VM, GCS backups, placeholder domains.
- Open questions: domains; email provider (ADR 0006); dedicated VM vs shared (High risk).
- Next step: founder runs the prepared cloud commands and the first install per the runbook.

## 2026-11-13 — Phase 17: ship-and-debit / SPA claims
- Changed: sales-lines import type; SPA records + items; pure matcher `engine/spa.py`
  (engine 1.2.0; 13 hand-worked/property tests); `spa_match` job (claimed lines frozen,
  caps carried); SPA claims (draft → submitted → paid / partially paid / rejected),
  evidence CSV, deadline alerts; migration 0010 (5 tables, RLS, import_type CHECK widened
  NOT VALID + VALIDATE); page `/app/spa`. Tests: API (hand-worked), authz matrix, tenancy,
  E2E + a11y/keyboard/screen reader. Load: 1M lines matched in 10.1 s.
- Bug fixed (pre-existing): jobs enqueued inside a SAVEPOINT (import commit) were dispatched
  before the real commit and lost until stale-job recovery (~5 min). Regression tests in
  `tests/api/test_jobs_nested.py`.
- Decisions (ADRs): 0017 §4 (book cost basis; COST_MISMATCH keeps the amount).
- Next step: v1.1 report; Phase 11 waits for the hosting answer.

## 2026-11-13 — Phase 16: buying-group programs
- Changed: engine 1.1.0 (`member_supplier_ids` on the version snapshot, omitted from the hash
  when empty; planner reads members' lines); golden fixtures 41–43; property tests (one-member
  group = supplier agreement, order independence, pinned 1.0.0 hashes — all 64 existing results
  verified identical old vs new). Backend: supplier `kind`, `buying_group_members` (migration
  0009, RLS), member API, line loading/coverage/staleness for groups, purchase rows under a
  group code rejected, merge rules. UI: type on supplier create, Members tab, "member of" tab,
  group labels in agreement and deal-model pickers.
- Decisions (ADRs): 0017 §3 (counts for both). Group coverage = latest member start.
- Next step: Phase 17 (ship-and-debit / SPA claims).

## 2026-11-13 — Phase 15: month-end accrual journal export
- Changed: `services/accruals.py` (outstanding = earned to D − received ≤ D; closed periods
  from the latest run, open period recalculated to D; exclusions listed), reversing CSV
  (generic, QuickBooks Online UNVERIFIED), `accrual_exports` (migration 0008, RLS) with
  sign-off, audit, hash and change list; Settings → Accounting (GL codes); page
  `/app/accruals`. Tests: hand-worked API tests incl. credit-after-closing, overpaid swap,
  not-calculated periods; bug found and fixed (agreement starting after the closing date).
- Decisions: amount booked = outstanding receivable, the only amount that keeps a reversing
  scheme correct; requires credits booked to the offset account (stated on screen).
- Open questions: accountant review of the treatment; per-supplier GL overrides not built.
- Next step: Phase 16 (buying-group programs).

## 2026-11-13 — Phase 14: weekly buyer digest
- Changed: `tiers.opportunities` ranking (return per extra dollar, required vs current daily
  pace); `GET /api/v1/tiers/opportunities`; dashboard "Top tier opportunities" (reuses the one
  tracker computation); `weekly_digest` job (local Monday, owners/admins/analysts,
  preferences + unsubscribe) with `digest_sends` (migration 0007, RLS) so retries never
  resend. Tests: hand-worked ranking, once-per-week, no viewers, opt-out, other days.
- Next step: Phase 15 (accrual journal export).

## 2026-11-13 — Phase 13: deal modelling
- Changed: `POST /api/v1/deal-models/evaluate` (stateless, read-only; same permission as
  editing agreements) running 1–4 proposed term sets through the engine over ≤ 24 months of
  real purchases, with ±10/20% sensitivity; page `/app/agreements/model` with side-by-side
  comparison, CSV export and "create agreement draft"; TermsEditor ids made unique per
  instance; nav highlights the most specific item. Tests: hand-worked API tests, component,
  E2E + axe/keyboard/screen-reader.
- Decisions: stateless instead of a saved-scenarios table (smaller, no new tenant data).
- Next step: Phase 14 (weekly buyer digest).

## 2026-11-13 — Phase 12: ERP import template packs
- Changed: 11 read-only ERP report presets (`backend/app/imports/presets.py`: Prophet 21,
  Eclipse, Infor CSD, NetSuite, Acumatica, QuickBooks Online/Desktop; purchases and credits);
  upload preview suggests a preset only on a unique fit; apply fills the mapping but leaves it
  unconfirmed; copy preset to template; header-row download. UI on the mapping step and in
  Settings → Import templates. Tests: unit, API, authz matrix, component, E2E.
- Decisions (ADRs): 0017 (v1.1 scope; presets are unverified best guesses).
- Open questions: real ERP sample exports to verify presets.
- Next step: Phase 13 (deal modelling).

## 2026-11-13 — Phase 10 follow-up: decisions, keyboard and screen-reader pass
- Changed: keyboard spec (40 tests) and screen-reader spec (34 tests). Fixes they found:
  distinct page titles on all app routes (29 title layouts), which also makes route changes
  announced; focus returns to the opener when dialogs, drawers and the palette close;
  `scroll-padding-top` so focused items are not hidden under the sticky header. Ops E2E
  race fixed (waits for the issued invoice number). E2E 136/136.
- Decisions (ADRs): 0016 — 0.7 s accepted, engine unchanged, backup RPO 5 min / RTO 4 h
  approved, no third-party pentest, HIBP not enabled, remaining risks accepted.
- Open questions: hosting for Phase 11 (founder says staging and production VMs are live).
- Next step: Phase 11 after the hosting answer.

## 2026-11-12 — Phase 9: marketing website
- Changed: public site (Home, How it works, Features, Security, Pricing from the plan catalog,
  About, Contact, Request a pilot, hidden Blog, legal templates with [LEGAL REVIEW REQUIRED],
  404/500), sitemap, robots, generated social image, JSON-LD (no ratings); pilot form with
  consent, honeypot and rate limits, confirmation + operator emails (migration 0006); optional
  cookieless analytics behind config with route-scoped CSP; sonner CSS-injection patch.
- Verified: Lighthouse (local prod build) Home 100/100/100/100, Pricing 99/100/100/100,
  Security 100/100/100/100; copy audit and axe on every marketing page; pilot request reaches
  the ops inbox and both emails arrive in Mailpit. 62 E2E tests pass.
- Decisions (ADRs): 0015.
- Open questions: analytics provider; bot challenge (third-party); legal review; real proof and
  team bios to replace placeholders; prices.
- Next step: Phase 10 (hardening).

## 2026-11-12 — Phase 8: billing, ops console, support access
- Changed: invoices + lines (RLS, immutability triggers), gap-free yearly numbering, invoice
  PDF and emails, mark paid, void + reissue, daily lapse job (reminders, past_due), tenant
  invoices on Plan & usage; ops console (`/ops`): organizations (create + invite owner,
  subscription, flags, usage via guarded aggregate function), invoices, plans, pilot-request
  inbox (public rate-limited form), announcements, job monitor with retry, billing settings,
  operator audit; support sessions only with a tenant grant; billing, announcement and
  exit-support banners.
- Fixed: support-grant banner did not update after granting (now shares the query).
- Verified: 12 concurrent issuers get RL-YYYY-0001…0012 with no gaps and a rolled-back issue
  consumes no number; suspended tenant is read-only but exports; platform context reads zero
  business rows and needs an active grant. E2E: operator issues an invoice the owner sees;
  support session with consent; axe on every ops page. 47 E2E tests pass.
- Decisions (ADRs): 0014.
- Open questions: reminder schedule and 14-day grace [PROPOSED DEFAULT]; tax treatment (SPEC §15).
- Next step: Phase 9 (marketing website).

## 2026-11-12 — Phase 7: reports, exports, evidence packs
- Changed: `exports` table (RLS) + `build_export`/`expire_exports` jobs; six reports
  (reconciliation summary, supplier statement, claims register, recovery report, agreement
  register, import history) with on-screen preview and CSV/XLSX/PDF export; claim evidence
  pack (PDF + summary, eligible-lines and credits CSVs); Owner full data export ZIP (step-up);
  15-minute signed, user-bound download links; Reports page with recent exports; evidence-pack
  button on claims; "Your data" card in organization settings.
- Verified: malicious-cell fixture neutralised in CSV, XLSX, evidence and full-export CSVs;
  PDF renderer made zero requests to a live local server (and refused `file://`); evidence
  pack amounts equal the Results screen string-for-string and its eligible lines sum to the
  run's spend. E2E downloads a report CSV (total 700.00) and an evidence pack.
- Decisions (ADRs): 0013 exports and evidence packs.
- Open questions: report/evidence file retention 7 days [PROPOSED DEFAULT]; per-user export rate limit.
- Next step: Phase 8 (invoice billing, ops console, support access, suspended mode).

## 2026-11-12 — Phase 10: hardening
- Changed: request-body size limit middleware (413 before parsing); `/credits/unmatched` N+1
  removed and `limit` added; after-commit job dispatch survives a broker outage (orphaned queued
  jobs re-dispatched by `recover_stale`); tier tracker/dashboard load column tuples with a
  bounded look-back (p95 4.1 s → 0.7 s); hardening tests; frontend component tests; resilience
  drill (5/5 pass), backup/restore rehearsal, API latency script; reports in `docs/hardening/`
  (security review F1–F9, load tests, resilience, backup/restore, a11y/performance); threat model updated.
- Decisions (ADRs): none new. Cache for the tier tracker rejected (staleness on money figures).
- Open questions: tiers/dashboard ~0.7 s (accept / precompute / engine option); backup RPO 5 min /
  RTO 4 h proposals; manual keyboard + screen-reader pass (UNVERIFIED); third-party pentest;
  HIBP check; re-measure the 50×1M run on staging.
- Next step: Phase 11 (deploy preparation only), after approval.

## 2026-11-11 — Phase 6: product screens + E2E
- Changed: screens for suppliers (detail), agreements (list/new/detail with terms editor, live
  summary, versions, compare, dry-run preview, documents), import wizard (upload → map → explicit
  formats incl. never-guessed ambiguous dates → 200-row preview → background validation → unknown
  supplier resolution → commit → result, templates, void), runs (start, progress, results, explain,
  diff), results, discrepancies (filters, multi-select → claim), credits (unmatched + suggestions,
  split allocation, manual entry, reversal), claims (list, lifecycle, recoveries via real credits,
  notes, attachments, ETag edits, write-off), tier tracker (estimates labelled), approvals queue,
  reports placeholder (Phase 7).
- Backend: approvals now return a label, link and decision fields; `seed-e2e` CLI (refuses in
  staging/production) for fresh MFA-enrolled E2E users.
- Fixed (each with a failing test first): the worker process registered **no** job handlers
  (`app/services/registry.py` was empty, so every queued email/import/run failed in `make worker`;
  `tests/test_worker_registry.py`). axe findings: focusable chart inside aria-hidden, account menu
  name mismatch, unnamed sort buttons on action columns, colour-only inline link.
- CSP: Radix scroll-lock styles now carry the request nonce (`get-nonce`, already a transitive
  dependency, MIT); sonner's CSS is imported as a stylesheet because its runtime `<style>` is blocked.
- E2E: Playwright + axe on :3100/:8100 (no clash with dev servers), real worker, Mailpit API,
  RFC 6238 TOTP helper (no new dependency). 14 journeys + 30 page accessibility checks pass.
- Next step: Phase 7 (reports, exports, evidence packs).

## 2026-11-11 — Phase 5: frontend foundation
- Changed: design tokens (light/dark), IBM Plex, app shell (navigation, command palette,
  notifications, user menu, breadcrumbs), nonce CSP via `proxy.ts`, generated OpenAPI client,
  auth flows (login + MFA, MFA setup, reset, verify, email change, invite, unsubscribe), settings
  (profile, organization, security incl. support access, reconciliation, approvals, members,
  notifications, templates, plan, audit), dashboard with onboarding, first supplier screens.
- Decisions (ADRs): 0011 Cache Components off so the CSP nonce applies to every page.
- Open questions: design brief still needs founder approval (`docs/design-brief.md`).
- Next step: Phase 6 (product screens).

## 2026-11-11 — Phase 4: runs, reconciliation, claims
- Changed: calculation runs (scope, snapshot, one active per tenant via queue_key, cancel, immutable
  results + traces enforced by trigger, run diff, result history); deterministic credit auto-match during
  runs; live reconciliation (tenant-timezone due dates, run-snapshot tolerances); manual split allocation +
  reversal; unmatched credits with suggestions; stale detection for every SPEC §4.7 trigger; discrepancy
  queue; claims lifecycle with events, attachments, four-eyes write-off, recoveries that link real credits;
  tier tracker + accrual estimates; notifications (in-app + email, preferences, signed unsubscribe);
  claim reminders and tier alerts (daily jobs); dashboard KPIs.
- Measured: 50 agreements / 1,000,000 lines full-year run in 242.7 s (target 300 s), 591 MB peak.
- Decisions: latest result per agreement + *full* period (split windows replace older results);
  recovered = credits linked to claims only.
- Next step: Phase 5 (frontend foundation).

## 2026-11-11 — Phase 3: suppliers, agreements, imports
- Changed: suppliers/aliases/contacts/merge; agreements with versioned terms in SPEC tables,
  plain-English summary, dry-run preview, approvals (four-eyes), attachments; DB triggers make
  non-draft versions immutable; import pipeline (CSV/XLSX upload with signature + zip-bomb checks,
  encoding/delimiter detection, mapping templates, explicit formats, 200-row preview, background
  validation, single-transaction commit with dedupe, error report, unknown-supplier resolution, void);
  plans + subscriptions + limit checks; demo seed; 1M-row load test.
- Decisions (ADRs): 0012 agreement versioning and import pipeline.
- Open questions: upload size vs row limit conflict (ADR 0012 §7); supersession rule (§3).
- Next step: Phase 4 (runs, reconciliation, claims).

## 2026-11-10 — Phases 0, 1, 2: foundations, engine + pilot CLI, backend core
- Changed: monorepo scaffold (backend/frontend/infra/docs), compose stack with owner/app DB roles,
  Makefile, CI (check, audit, SAST, secret scan, e2e job), Dependabot. Pure rebate engine with
  40 golden fixtures + property tests (99% coverage); pilot CLI with sample data and HTML traces.
  Backend core: auth (Argon2id, sessions, MFA/TOTP + recovery codes, step-up, lockout, progressive
  delay, reset/verify/change-email), memberships/roles/permissions, invites, RLS on every tenant
  table, hash-chained audit log + daily verification, Problem Details, CSRF, security headers,
  idempotency helper, durable job framework (Dramatiq), email adapter + templates, platform-admin CLI.
- Decisions (ADRs): 0001 versions, 0002 sync SQLAlchemy, 0003 Dramatiq + jobs table, 0004 Recharts,
  0005 WeasyPrint (network blocked), 0006 email shortlist [OPEN], 0007 /api via Next rewrites,
  0008 package managers + DB roles, 0009 storage adapter, 0010 engine interpretations, 0011 Cache Components off.
- Open questions: SPEC §15 items 1–9; ADR 0010 interpretations need founder confirmation;
  breached-password check uses an offline list (HIBP needs an outbound-HTTP ADR).
- Next step: Phase 3 (suppliers, agreements, imports).
