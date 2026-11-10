# Error codes

Every API error is RFC 9457 Problem Details (`application/problem+json`) with a
stable `code`. Clients branch on `code`, never on `title`/`detail` text.
`backend/tests/test_error_catalogue.py` fails if the backend raises a code that
is not listed here.

```json
{"type": "https://docs.rebateledger.invalid/errors/LAST_OWNER", "title": "Conflict",
 "status": 409, "code": "LAST_OWNER", "detail": "…", "instance": "/api/v1/org/members/…",
 "request_id": "…", "errors": [{"field": "email", "code": "…", "message": "…"}]}
```

## Generic
| Code | Status | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body/query failed validation; see `errors[]` |
| `NOT_FOUND` | 404 | Missing **or belongs to another organization** (existence never revealed) |
| `FORBIDDEN` | 403 | Role lacks the permission |
| `UNAUTHENTICATED` | 401 | No valid session |
| `METHOD_NOT_ALLOWED` | 405 | |
| `HTTP_ERROR` | 4xx | Other framework-level HTTP error |
| `INTERNAL_ERROR` | 500 | Logged with the request id; no internals returned |
| `RATE_LIMITED` | 429 | Too many attempts; honour `Retry-After` |
| `PRECONDITION_REQUIRED` | 428 | Send `If-Match` with the ETag |
| `PRECONDITION_FAILED` | 412 | Someone else changed the object; reload |
| `IDEMPOTENCY_KEY_INVALID` | 422 | Key must be 8–200 characters |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Same key, different request body |
| `UNKNOWN_FIELD` | 422 | Field not allowed in this settings section |
| `NEGATIVE_NOT_ALLOWED` | 422 | Value must be ≥ 0 |

## Security & sessions
| Code | Status | Meaning |
|---|---|---|
| `CSRF_ORIGIN` | 403 | `Origin`/`Referer` is not this application |
| `CSRF_TOKEN` | 403 | Missing/invalid `X-CSRF-Token` |
| `INVALID_CREDENTIALS` | 401 | Generic sign-in failure (wrong password, unknown email or locked — indistinguishable) |
| `MFA_REQUIRED` | 403 | Session waits for a TOTP/recovery code |
| `MFA_ENROLLMENT_REQUIRED` | 403 | Role or org policy requires MFA set-up first |
| `MFA_INVALID` | 401 | Wrong, expired or replayed code |
| `MFA_CODE_REQUIRED` | 422 | No code supplied |
| `MFA_NOT_PENDING` | 409 | Session is not waiting for MFA |
| `MFA_NOT_STARTED` | 409 | Confirm called before set-up |
| `MFA_ALREADY_ENABLED` | 409 | Disable first to replace the authenticator |
| `MFA_REQUIRED_FOR_ROLE` | 409 | Cannot disable MFA while a role requires it |
| `STEP_UP_REQUIRED` | 403 | Re-authenticate (password + code) within 10 minutes |
| `STEP_UP_FAILED` | 401 | Re-authentication failed |
| `TOKEN_INVALID` | 400 | Email link/invite invalid, expired or used |
| `WEAK_PASSWORD` | 422 | Length or breached-password rule failed |
| `WRONG_PASSWORD` | 422 | Current password incorrect (account settings) |
| `EMAIL_UNCHANGED` | 422 | New email equals current |
| `EMAIL_TAKEN` | 409 | New email cannot be used |
| `NAME_REQUIRED` | 422 | Invite acceptance needs a name |
| `UNKNOWN_PREFERENCE` | 422 | Unsupported user preference key |

## Organizations
| Code | Status | Meaning |
|---|---|---|
| `NO_ORGANIZATION` | 403 | No organization selected in this session |
| `NO_MEMBERSHIP` | 403 | No longer a member of the selected organization |
| `LAST_OWNER` | 409 | The last active Owner cannot be demoted/deactivated |
| `CANNOT_DEACTIVATE_SELF` | 409 | |
| `ALREADY_MEMBER` | 409 | Reactivate instead of inviting |
| `DOMAIN_NOT_ALLOWED` | 422 | Invite email outside allowed domains |
| `TIMEZONE_INVALID` | 422 | Not an IANA timezone |
| `DURATION_INVALID` | 422 | Support access must be 1 h – 7 days |
| `SUPPORT_ACCESS_ENDED` | 403 | Platform admin's grant expired or was revoked |
| `TENANT_READ_ONLY` | 403 | Organization suspended: view/export only |

## Jobs (in `GET /api/v1/jobs/{id}` → `error.code`)
| Code | Meaning |
|---|---|
| `JOB_FAILED` | The job raised; message is user-safe |
| `WORKER_LOST` | The worker stopped mid-job too many times |
