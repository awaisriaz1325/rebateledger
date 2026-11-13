# Security review (Phase 10)

Date: 2026-11-12. Scope: the whole repository at the Phase 10 commit, running on the local
stack. Reviewer: Claude Code (automated plus manual reading). **This is not a third-party
penetration test**, and none will be bought for launch (ADR 0016).

## 1. Findings

| # | Finding | Severity | Status | Fix / evidence |
|---|---|---|---|---|
| F1 | No request-body size limit before parsing. A large JSON body was read fully into memory by any authenticated (or public) route. | High | **Fixed** | `backend/app/core/body_limit.py`: pure ASGI middleware. JSON bodies are capped at 1 MiB; upload routes get their file limit + 1 MiB. Bodies without a declared length are capped while streaming. Responds 413 `PAYLOAD_TOO_LARGE`. Tests: `tests/api/test_hardening.py::test_oversized_json_body_is_refused_before_parsing`, `::test_streamed_body_without_length_is_also_capped`, `::test_upload_routes_keep_their_larger_limit` |
| F2 | `/credits/unmatched` ran 2 queries per credit (N+1). At 100k credits one request ran for more than 10 minutes, so any analyst could tie up a DB connection and an API worker (denial of service). | High | **Fixed** | `backend/app/services/reconciliation.py::unmatched`: one grouped allocation subquery, one allocations query, `limit` 1–2000 (default 500). Now p95 96 ms at 100k credits. Test: `test_hardening.py::test_unmatched_credits_query_count_does_not_grow_with_credits` |
| F3 | If Redis was down when a request committed, the after-commit job dispatch raised. The client got a 500 for work that *was* committed, and the job stayed `queued` forever. | Medium | **Fixed** | `backend/app/workers/jobs.py`: dispatch failures are logged (`job_dispatch_failed`, job id only), and `recover_stale` re-dispatches queued jobs older than 5 minutes. Test: `tests/api/test_jobs_platform.py::test_broker_outage_at_commit_keeps_the_request_ok_and_the_job_recoverable` |
| F4 | Tier tracker and dashboard loaded every purchase line of the supplier from January of the previous year as ORM entities (≈ 4 s at 100k lines). | Medium (performance; a repeated-request load vector) | **Mitigated** | Column-tuple loading and a look-back bounded to what the engine can read (`agreements.lines_needed_from`): 5.6 s → 1.4 s. Still above the 500 ms [PROPOSED TARGET]. See `load-tests.md` §3; precomputation is proposed for Phase 11 |
| F5 | Offline breached-password list is small. | Medium | Accepted (ADR 0016: stays offline) | HIBP k-anonymity needs an ADR that allows one outbound call from a request path (`.claude/rules/backend.md` forbids it today) |
| F6 | Rate limits fail closed when Redis is unavailable, so logins are refused during a Redis outage. | Low/Medium | Accepted (safer failure mode) | Drill D: Redis back in < 5 s. Phase 11 uses Memorystore with HA |
| F7 | No per-user rate limit on export creation. Exports are queued and bounded by the plan's limits, but one user could queue many. | Low | Accepted (ADR 0016) | Add with Phase 11 quotas |
| F9 | API responses carry `server: uvicorn` | Low | Open (Phase 11) | `--no-server-header` in the container command |
| F8 | `pnpm audit`: 1 moderate (`minimatch` ReDoS, pulled in by the ESLint toolchain, dev-only, not shipped to browsers or the server bundle). | Low | Accepted | Re-check when ESLint ships the patched range |

No finding was rated Unsafe. All High findings are fixed.

## 2. Authorization fuzzing and IDOR sweep

- `tests/api/test_authz_matrix.py::test_matrix` covers every route × every role × own
  tenant / other tenant. Other-tenant ids must return 404 (never 403, which would leak
  existence) and never 200.
- `tests/api/test_route_policy.py` fails if any route lacks a declared policy.
- `tests/api/test_hardening.py::test_random_ids_never_cause_server_errors` sends random UUIDs
  to every GET route with a path id. Every answer is 404/422 Problem Details, never 5xx.
- `tests/api/test_tenancy.py` covers RLS as the second layer: raw SQL as the application
  role, with no `tenant_id` filter, sees and writes only the current tenant. Every tenant
  table has RLS enabled and forced, and the app role is not privileged.
- Platform operators: `test_ops_billing.py::test_platform_admin_needs_an_active_grant_for_business_data`.

## 3. Upload abuse

| Attack | Result | Test |
|---|---|---|
| Zip bomb in XLSX | Rejected before inflating (ratio + size cap) | `test_import_pipeline.py::test_case28_zip_bomb_and_external_entity_rejected` |
| XML external entity in XLSX | Rejected (defusedxml) | same |
| Renamed executable / wrong signature | Rejected by magic-byte check | `test_import_pipeline.py::test_file_type_and_signature_checks` |
| Oversized file | 413 from the size check; JSON routes capped at 1 MiB | `test_hardening.py` |
| Formula injection in exported cells | Neutralised in CSV and XLSX (string type forced) | `tests/api/test_exports.py` |

## 4. CSRF and session

- HMAC CSRF token plus an Origin check on every unsafe method:
  `tests/api/test_auth.py::test_csrf_token_and_origin_required`.
- `__Host-` session cookie: Secure, HttpOnly, SameSite=Lax. Rotated on login, MFA and step-up.
  Other sessions are revoked on password change (`test_password_change_revokes_other_sessions`).

## 5. Scans (actual output, 2026-11-12)

| Tool | Command | Result |
|---|---|---|
| pip-audit (strict) | `make audit` | `No known vulnerabilities found` |
| pnpm audit (high) | `make audit` | `1 vulnerabilities found — Severity: 1 moderate` (F8) |
| bandit | `make sast` | 0 issues (only "nosec encountered" warnings for two documented Jinja `Markup` uses in `app/emails/service.py`) |
| gitleaks (history) | `make secrets` | `17 commits scanned … no leaks found` |
| gitleaks (working tree) | `gitleaks dir` | 15 hits: all are dummy test keys (`backend/tests/conftest.py`, the RFC 6238 vector in `totp.test.ts`), the gitignored `frontend/.next/` build cache, or the gitignored local E2E seed `frontend/e2e/.state/seed.json`. None are tracked or real |
| Container image scan | n/a | **Deploy**: Dockerfiles land in Phase 11; scan with Artifact Registry / Trivy there |

## 6. Header scan

`curl -D -` against the production build (`pnpm build && pnpm start`, with
`RL_API_ORIGIN` set) and the API behind its `/api` rewrite, 2026-11-12:

| Header | Web pages (`/`, `/login`) | API (`/api/v1/*`) |
|---|---|---|
| Content-Security-Policy | `default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic'; style-src 'self' 'nonce-…' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'` |
| Strict-Transport-Security | `max-age=31536000; includeSubDomains` | added by the API in production only |
| X-Frame-Options | `DENY` | `DENY` |
| X-Content-Type-Options | `nosniff` | `nosniff` |
| Referrer-Policy | `strict-origin-when-cross-origin` | same |
| Permissions-Policy | camera, microphone, geolocation, payment, usb all `()` | same |
| Cross-Origin-Opener/Resource-Policy | — | `same-origin` / `same-origin` |
| Cache-Control | `private, no-cache, no-store, max-age=0, must-revalidate` | `no-store` |
| Server | — | `uvicorn` (**F9**) |

- **F9 (Low): `server: uvicorn` reveals the server software.** Fix in Phase 11: start the
  container with `uvicorn --no-server-header` (Cloud Run fronts it anyway).
- `style-src 'unsafe-inline'` sits next to a nonce. CSP Level 3 browsers ignore
  `'unsafe-inline'` when a nonce is present, so it only applies to legacy browsers.
  `script-src` has no `unsafe-inline` and no `unsafe-eval`. Accepted (Low).
- **Deployment note.** Next.js resolves the `/api` rewrite at build time, so `RL_API_ORIGIN`
  must be set when the image is **built**, not only at runtime. A build without it proxies
  to the default `127.0.0.1:8000`. This goes into the Phase 11 Dockerfile as a build arg,
  with a runbook check.

## Not covered

- Third-party penetration test: not bought (founder decision, ADR 0016). Do not claim one.
- TLS configuration, HSTS preload, Cloud Armor rules: verified on staging in Phase 11.
- Container base-image CVEs: Phase 11.
