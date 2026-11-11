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
