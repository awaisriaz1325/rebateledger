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
