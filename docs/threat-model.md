# Threat model (STRIDE)

Living document (SPEC §8.6). Updated each phase that adds attack surface.
Last update: 2026-11-11 — Phase 3 (uploads, imports, agreements).

## Assets
1. Supplier pricing, purchase lines, credits, agreements (commercially sensitive).
2. Calculated expected rebates and claims (financial decisions rely on them).
3. Credentials: passwords (Argon2id), TOTP secrets (Fernet-encrypted), recovery
   codes (SHA-256), session tokens (SHA-256 stored), email-link tokens (SHA-256).
4. Audit log integrity (hash chain).
5. Operator (platform admin) access.

## Trust boundaries
Browser ↔ Next.js (public internet, TLS) ↔ FastAPI (private) ↔ Postgres/Redis/
storage (private). Worker ↔ same stores. Email provider (outbound only).
Ops console = same apps, separate role enforced server-side.

## STRIDE by component

### Browser
| Threat | Mitigation | Status |
|---|---|---|
| S: session theft via XSS | HttpOnly `__Host-` cookie; strict nonce CSP; no user HTML rendering; React escaping | Cookie done (P2); CSP in P5 |
| T: CSRF | SameSite=Lax + per-session HMAC CSRF token header + Origin/Referer check on every unsafe method, including login | Done, tested |
| I: tokens in URLs/storage | Email tokens only in link query → exchanged via POST; nothing in localStorage | Done (API); UI P5 |
| Clickjacking | `frame-ancestors 'none'`, `X-Frame-Options: DENY` | API done; web P5 |

### Next.js server
| Threat | Mitigation | Status |
|---|---|---|
| I: tenant data in shared cache | `cacheComponents` off, no `use cache` on tenant data (ADR 0011) | P0 |
| S: SSRF via rewrites | Rewrite destination fixed by server env, never user-controlled | P0 |
| E: proxy trust | API trusts `X-Forwarded-For` only from the web service IPs (uvicorn `--forwarded-allow-ips`) | Config in P11 |

### API (FastAPI)
| Threat | Mitigation | Status |
|---|---|---|
| S: credential stuffing | Per-IP + per-email rate limits; progressive delay keyed on email hash (known or unknown); 15-min lockout after 10 failures | Done, tested |
| S: user enumeration | Identical response + one Argon2 verify on all login failure paths; forgot-password always 202 | Done, tested |
| S: weak/breached passwords | 12–128 chars; offline common-password list; HIBP mode available (outbound HTTP needs ADR) | Done |
| S: MFA bypass | MFA mandatory for Owner/Admin/platform admin; pending sessions limited to MFA endpoints; TOTP replay rejected; recovery codes single-use and force re-enrollment | Done, tested |
| S: session fixation / reuse | Token rotated on login, MFA, org switch, password change; all sessions revoked on password reset/MFA disable/email change; role change revokes affected sessions | Done, tested |
| T: IDOR | Every object query filters by `tenant_id` AND RLS; other-tenant ids return 404; generated authz matrix covers every route | Done, tested |
| R: repudiation | Hash-chained audit log written in the same transaction; daily verification job | Done, tested |
| I: error leakage | Problem Details only; SQLAlchemy `hide_parameters`; logs scrub secrets/emails/cookies | Done |
| D: abuse of expensive endpoints | Rate limits on auth, invites; background jobs for long work; statement timeout 60 s | Partial (imports P3) |
| E: privilege escalation | Named permissions per route (walker test); Owner-only owner management; last-owner lock; step-up for sensitive actions | Done, tested |

### Worker
| Threat | Mitigation | Status |
|---|---|---|
| I: secrets in job payloads | Email payloads sealed (Fernet) and wiped after send | Done |
| T: cross-tenant job | Job carries tenant id; runner sets the same RLS context | Done |
| D: poison jobs | Retries with backoff, `dead` state, stale-heartbeat recovery | Done, tested |

### Postgres
| Threat | Mitigation | Status |
|---|---|---|
| E: app bug bypasses tenancy | App role `rl_app` is not owner and `NOBYPASSRLS`; RLS on every `tenant_id` table (tested) | Done, tested |
| T: audit tampering by app | No UPDATE/DELETE grant on `audit_events`; chain verification | Done, tested |
| E: create platform admin via app | App role has SELECT only on `platform_admins` | Done, tested |
| I: backups | Encrypted at rest (cloud); PITR; restore test | P11 |

### Redis
Rate-limit keys hold hashed identifiers only. Not a system of record; loss = rate
limit reset and re-queued jobs (jobs table is durable). Private network only (P11).

### Object storage + file uploads (P3)
| Threat | Mitigation | Status |
|---|---|---|
| T/E: malicious upload (macro workbook, polyglot) | Extension AND magic bytes checked; .xlsm/.xlsb/.xls refused; `vbaProject` parts refused | Done, tested |
| D: zip bomb | Member count, per-member ratio and total uncompressed size checked before parsing | Done, tested |
| I: XXE | openpyxl uses defusedxml (verified `openpyxl.xml.DEFUSEDXML is True`); parser errors → 422 | Done, tested |
| D: huge files | 50 MB / 1M rows / 200 columns; streaming parse; ≤ 768 MB worker budget (measured 258 MB) | Done, measured |
| I: path traversal | Keys `{tenant}/{kind}/{random}`; local adapter refuses paths outside its root | Done |
| I: content served inline | Downloads only via authorised endpoint, `attachment` + `nosniff` | Done |
| T: formula injection in exports | `csv_safe.neutralize` on every exported cell (error report, audit CSV) | Done, tested |

### Reports and exports (P7, ADR 0013)
| Threat | Control | Status |
|---|---|---|
| T: formula injection (CSV/XLSX) | Every text cell neutralised; XLSX text cells forced to string type; numbers typed | Done, tested in every format |
| I: SSRF / local file read via PDF | WeasyPrint `NoNetworkFetcher` refuses all but `data:`; Jinja autoescape | Done, tested with live HTTP server + `file://` |
| I: link leakage / replay | HMAC link bound to export + user + tenant, 15 min; session also required; audit on download | Done, tested |
| I: other users' exports | 404 unless own export or `full_export` permission | Done, tested |
| I: secrets in full export | Internal tables and secret columns excluded; members without credentials | Done, tested |
| D: export flooding | Background jobs; one full export in progress per tenant | Partial — per-user export rate limit not yet added (Low) |

### Email
Tokens single-use, hashed, short-lived. Security emails cannot be disabled.
SPF/DKIM/DMARC (P11). No tracking pixels.

### Ops console (P8)
Server-side `PlatformAdminOnly`, 404 for others, optional IP allowlist, MFA
mandatory, tenant business data only under an active time-boxed grant; every
request under support access is audited in the tenant's log.

## Open risks
- Offline breached-password list is small (1.2k entries ≥ 12 chars). Medium.
  Safer: enable HIBP range API (k-anonymity) in the worker or via an ADR
  allowing this single outbound call from the request path.
- Progressive delay and rate limits rely on Redis availability (fail-closed:
  a Redis outage blocks logins). Low/Medium — documented in runbooks (P11).
