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
