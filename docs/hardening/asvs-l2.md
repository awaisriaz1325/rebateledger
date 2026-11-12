# OWASP ASVS 4.0.3 Level 2 — evidence map

Status per chapter: **Met** (control in place with automated evidence), **Partial** (gap
noted with severity), **N/A** (feature absent in v1), **Deploy** (verified in Phase 11 on
real infrastructure). Paths are relative to the repository root.

| ASVS | Requirement area | Status | Evidence |
|---|---|---|---|
| V1 Architecture | Threat model, trust boundaries, single API authority | Met | `docs/threat-model.md`; ADR 0007 (all browser calls same-origin `/api`); `docs/adr/*` |
| V1.4 Access control architecture | Server-side, deny by default, enforced at one place | Met | `backend/app/api/deps.py` (`Requires`, `PlatformAdminOnly`, `Public`); `tests/api/test_route_policy.py` fails any route without a policy |
| V2.1 Password security | ≥ 12 chars, max 128, breached-password check, no composition rules | Met / Partial | `backend/app/core/security.py`; offline breached list is small (Medium, see threat model; HIBP needs ADR) |
| V2.2 General authenticator | Rate limits, lockout, progressive delay, notification of changes | Met | `backend/app/services/auth.py` (`ratelimit.hit`), `tests/api/test_auth.py` |
| V2.4 Credential storage | Argon2id | Met | `backend/app/core/security.py` (`argon2` PasswordHasher) |
| V2.5 Recovery | Single-use, hashed, expiring reset tokens; no hints | Met | `email_tokens` table, `tests/api/test_auth.py` |
| V2.8 OTP | TOTP with replay protection; recovery codes hashed | Met | `verify_totp` + `last_used_timestep`; `tests/api/test_auth.py`; E2E `e2e/fixtures/totp.ts` |
| V3 Session management | Random tokens, hashed at rest, `__Host-` cookie, HttpOnly, Secure, SameSite=Lax, idle + absolute timeouts, rotation on privilege change, revoke other sessions | Met | `backend/app/api/routes/auth.py` (`set_cookie`), `auth.rotate`; E2E `account.spec.ts` (session revoke) |
| V4 Access control | Object ownership on every query, 404 for other-tenant ids, RLS as second layer | Met | `tests/api/test_authz_matrix.py` (every route × role × other tenant), `tests/api/test_tenancy.py`, `tests/api/test_hardening.py` (random-id sweep); RLS in migrations 0001–0006 |
| V4.3 Admin interfaces | Platform console server-enforced, MFA mandatory, IP allowlist option, tenant data only via grant | Met | `PlatformAdminOnly`; `tests/api/test_ops_billing.py::test_platform_admin_needs_an_active_grant_for_business_data` |
| V5.1 Input validation | Pydantic v2 strict models, length limits, enums, unknown fields rejected | Met | `backend/app/api/schemas/common.py` (`In` forbids extras); route models |
| V5.2 Sanitisation | No HTML rendering of user content; Jinja autoescape for emails/PDF; CSV/XLSX formula neutralisation | Met | `backend/app/core/csv_safe.py`, `backend/app/exports/writers.py`; `tests/api/test_exports.py` |
| V5.3 Output encoding / injection | Parameterised SQL only; JSON-LD escaped constants only | Met | SQLAlchemy Core/ORM throughout; bandit clean; ADR 0015 §5 |
| V5.5 Deserialisation | No pickle/yaml loads of user data; XLSX via defusedxml | Met | `backend/app/imports/reader.py`; zip-bomb/XXE test in `test_import_pipeline.py` |
| V7 Errors and logging | Problem Details, no stack traces/SQL; JSON logs with IDs only; scrubber; hash-chained audit | Met | `backend/app/core/errors.py`, `backend/app/core/logging.py`; `tests/api/test_hardening.py::test_unhandled_errors_never_leak_internals`; audit chain verification job |
| V8 Data protection | Tenant isolation, no sensitive data in URLs/storage, cache-control on app pages, export links short-lived | Met | `frontend/proxy.ts` (`no-store` on /app,/ops); ADR 0013 (15-minute bound links) |
| V9 Communications | TLS everywhere, HSTS | Deploy | `Strict-Transport-Security` set in production (`app/main.py`, `proxy.ts`); verified on staging in Phase 11 |
| V10 Malicious code | Dependency pinning, lockfiles, audits, secret scanning | Met | `uv.lock`, `pnpm-lock.yaml`; `make audit`, `make secrets`, `make sast` (results in `security-review.md`) |
| V11 Business logic | Sequential flow enforcement (claims, imports, invoices), anti-automation on public forms, four-eyes | Met | claim `TRANSITIONS`; import status checks; invoice triggers; pilot form rate limits + honeypot |
| V12 Files | Upload type by signature, size and row limits, zip-bomb guard, files never served inline, random keys outside web root | Met | `backend/app/imports/detect.py`, `backend/app/core/storage.py`; `tests/api/test_import_pipeline.py` |
| V12 Resource | Request body limits before parsing | Met (fixed in Phase 10) | `backend/app/core/body_limit.py`; `tests/api/test_hardening.py` |
| V13 API | CSRF (HMAC token + Origin), JSON content types, 405/404 as Problem Details | Met | `deps._csrf_and_origin`; `tests/api/test_auth.py::test_csrf_token_and_origin_required` |
| V14 Configuration | Security headers, CSP with nonces (no unsafe-eval in prod), no debug docs in prod, secrets from env/Secret Manager | Met / Deploy | `frontend/proxy.ts`; `create_app(docs_url=None if production)`; `.env.example` dummy only; Secret Manager in Phase 11 |

## Gaps carried forward
| Gap | Severity | Plan |
|---|---|---|
| Offline breached-password list is small | Medium | Founder decision on HIBP k-anonymity (needs ADR allowing one outbound call) |
| Rate limits fail closed if Redis is down (logins blocked) | Low/Medium | Runbook; Memorystore HA in Phase 11 |
| Per-user export rate limit | Low | Add with Phase 11 quotas |
| Some list handlers build SQL inline (e.g. suppliers list) instead of a service | Low (style, not security) | Refactor when touched |
| TLS/HSTS, container scan, backup encryption verified only on real infrastructure | Deploy | Phase 11 checklist |
