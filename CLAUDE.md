# RebateLedger — standing instructions for Claude Code

RebateLedger is a multi-tenant B2B SaaS that tells independent US wholesale
distributors what supplier rebates they earned, what they actually received,
and what is still missing. Customers are finance teams. Wrong numbers destroy
trust instantly, so correctness, explainability and security outrank speed.

- Full product + technical spec: `docs/SPEC.md` (read the relevant section before each task)
- Phase plan, acceptance criteria and stop gates: `docs/PHASES.md`
- Running log you maintain: `docs/PROGRESS.md`
- Architecture decisions you record: `docs/adr/NNNN-title.md`

## 1. Phase discipline (non-negotiable)

- Work one phase at a time, in order. Never start the next phase, and never
  "get ahead" on later-phase work, without my explicit written approval.
- Before writing code for a phase: read its section in `docs/PHASES.md`,
  produce a plan (files, steps, tests, risks, open questions) and wait for approval.
- A phase is done only when every acceptance criterion passes and the full
  check suite is green. If something fails, fix it before reporting. Never
  mark work complete on a red build, a skipped test, or a "should work".
- End every phase with the report below, then STOP and ask whether to proceed.

### End-of-phase report (use these exact headings)
1. **Built** — what now exists, with key file paths
2. **Verification** — commands run and their actual results (paste summaries, not claims)
3. **Assumptions** — every assumption made, and why
4. **Undecided** — open questions that need my decision
5. **Risks** — each rated Low / Medium / High / Unsafe; for High or Unsafe give a warning and a safer alternative
6. **How I can verify manually** — 3–8 concrete steps
7. **Proceed to Phase N+1?** — ask, and wait

## 2. Stop and ask (do not guess) when

- The spec is ambiguous, contradictory, or silent on something that affects
  money, security, data retention, or user-visible behavior.
- A change would alter scope, add a paid service, raise recurring cost, or
  weaken the security posture in any way.
- You would need to deviate from `docs/SPEC.md` (propose the change; don't make it).
- An action is destructive or irreversible (dropping data, force-pushing,
  deleting files outside the task, rewriting migrations already applied).
- Any cloud, DNS, billing or deployment command is involved. Prepare it, show
  it, and wait. Never provision or deploy on your own.

## 3. Truthfulness and verification

- Never invent library APIs, CLI flags, config keys or framework behavior.
  Check the official docs or the installed package source. If you cannot
  verify something, say "UNVERIFIED" explicitly in code comments and reports.
- Use current stable versions. Verify each version from the official source in
  Phase 0 and pin it in lockfiles. Do not trust remembered version numbers.
- Report real command output. If you did not run it, say so.
- Do not write marketing copy that claims customers, results, logos,
  testimonials, certifications (e.g. SOC 2) or security guarantees that do not
  exist. Use clearly marked placeholders instead.

## 4. Money and calculation rules (apply everywhere)

- Money and rates are `Decimal` in Python and `NUMERIC` in Postgres. Never
  `float`, never JS `number` arithmetic for money. The frontend only formats
  values the API returns as strings.
- The rebate engine is pure and deterministic: no I/O, no clock, no randomness,
  no network, no LLM. Same inputs + same engine version = identical output.
- Never silently guess an ambiguous financial rule. Flag `NEEDS_REVIEW` with a
  reason and let the user decide.
- No AI/LLM features in v1 at all.

## 5. Security baseline (details in SPEC §8)

- Every table with customer data has `tenant_id`; Postgres Row-Level Security is
  enforced in addition to application-level scoping. Cross-tenant access tests
  are mandatory for every new endpoint.
- Deny by default. Every endpoint declares the role/permission it needs and
  checks object ownership (no IDOR).
- Backend validation is the authority; frontend validation is UX only.
- Never log secrets, tokens, passwords, session ids, file contents, or raw
  purchase/credit rows. Log IDs, not data.
- Never commit secrets. Use `.env` locally (git-ignored) and Secret Manager in
  cloud. Keep `.env.example` files up to date with dummy values only.
- Do not read `.env` files; ask me for any value you need.
- CSV/XLSX exports must neutralise spreadsheet formula injection.
- Any new dependency: state why, check maintenance status and licence, prefer
  the standard library or an existing dependency.

## 6. Code standards

- Monorepo: `backend/` (FastAPI, Python), `frontend/` (Next.js, TypeScript),
  `infra/`, `docs/`. Keep the layout defined in Phase 0 and record changes in an ADR.
- Python: type hints everywhere, strict type checking, Ruff for lint/format,
  Pydantic v2 models at every API boundary, SQLAlchemy 2.x, Alembic migrations.
- TypeScript: `strict: true`, no `any` without a justified comment, API types
  generated from the backend OpenAPI schema (never hand-written duplicates).
- Small, focused modules. Business logic lives in services, not route handlers
  or React components.
- Every bug fix starts with a failing test that reproduces it.
- Migrations are forward-only once applied to a shared environment; each one
  is reviewed for locking impact on large tables.
- Conventional commit messages; one logical change per commit.

## 7. Tests are part of the feature

- Engine: golden fixtures with hand-worked expected values + property-based
  tests. Target ≥ 95% line and branch coverage for `backend/app/engine/`.
- Backend: unit + integration tests against real Postgres (containers), plus an
  authorization matrix test (endpoint × role × own/other tenant).
- Frontend: component tests for complex logic, Playwright for critical journeys,
  automated accessibility checks on every page.
- Never weaken, skip or delete a test to make a build pass. Ask first.

## 8. Commands

<!-- Fill this section in Phase 0 with the real, verified commands. -->
- Setup: _to be defined in Phase 0_
- Run all checks (lint + types + tests): _to be defined in Phase 0_
- Start local stack: _to be defined in Phase 0_
- Run backend tests / frontend tests / e2e: _to be defined in Phase 0_
- Create migration / apply migrations: _to be defined in Phase 0_

## 9. Progress log

After every working session append to `docs/PROGRESS.md`: date, phase, what
changed, decisions made (link ADRs), open questions, next step. Keep it short.
