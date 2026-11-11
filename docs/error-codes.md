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

## Suppliers & agreements
| Code | Status | Meaning |
|---|---|---|
| `CODE_REQUIRED` | 422 | A supplier needs at least one code |
| `CODE_IN_USE` | 409 | Supplier code already belongs to another supplier |
| `MERGE_SAME_SUPPLIER` | 409 | Choose two different suppliers |
| `MERGE_OVERLAPPING_AGREEMENTS` | 409 | Both suppliers have overlapping active agreements |
| `REFERENCE_IN_USE` | 409 | Agreement external reference already used |
| `TERMS_INVALID` | 422 | Agreement terms fail engine validation (detail says why) |
| `AGREEMENT_ARCHIVED` | 409 | Unarchive first |
| `DRAFT_EXISTS` | 409 | Finish or delete the open draft before another version |
| `LAST_VERSION` | 409 | An agreement keeps at least one version |
| `VERSION_NOT_EDITABLE` | 409 | Only drafts change; active versions are immutable |
| `VERSION_NOT_DRAFT` | 409 | Activation requested on a non-draft |
| `VERSION_NOT_PENDING` | 409 | Version is no longer awaiting approval |
| `VERSION_OVERLAP` | 409 | Effective ranges would overlap |
| `PERIOD_INVALID` | 422 | No period of the agreement contains the date / period dates invalid |
| `SELF_APPROVAL` | 403 | Four-eyes: a different approver is required |
| `APPROVAL_DECIDED` | 409 | Request already approved/rejected/cancelled |
| `PLAN_LIMIT_REACHED` | 403 | The plan's limit blocks this new action; existing data is unaffected |
| `CURSOR_INVALID` | 422 | Restart pagination |

## Imports
| Code | Status | Meaning |
|---|---|---|
| `FILE_TYPE_NOT_ALLOWED` | 422 | Only .csv/.xlsx; macro formats refused |
| `FILE_SIGNATURE_MISMATCH` | 422 | Contents don't match the extension |
| `FILE_TOO_LARGE` / `FILE_EMPTY` | 422 | Over 50 MB / empty |
| `XLSX_TOO_LARGE` / `XLSX_TOO_COMPLEX` | 422 | Zip-bomb protection triggered |
| `XLSX_UNREADABLE` | 422 | Workbook refused by the safe parser (e.g. external entities) |
| `TOO_MANY_ROWS` / `TOO_MANY_COLUMNS` | 422 | Over 1,000,000 rows / 200 columns |
| `ENCODING_MISMATCH` | 422 | File is not valid in the chosen encoding |
| `ENCODING_INVALID` / `DELIMITER_INVALID` / `SHEET_INVALID` | 422 | Unsupported choice |
| `CSV_MALFORMED` | 422 | CSV could not be parsed |
| `HEADER_NOT_FOUND` | 422 | The chosen header row is beyond the end of the file |
| `FILE_ALREADY_IMPORTED` | 409 | Identical file uploaded before; resend with `confirm_duplicate=true` |
| `IMPORT_NOT_CONFIGURED` | 409 | Confirm mapping and formats first |
| `IMPORT_NOT_EDITABLE` / `IMPORT_BUSY` / `IMPORT_NOT_COMMITTABLE` / `IMPORT_NOT_COMMITTED` | 409 | Wrong state for this action |
| `COMMIT_MODE_INVALID` | 422 | Use `all_or_nothing` or `skip_invalid` |
| `ACTION_INVALID` | 422 | Unknown-supplier resolution must be `create` or `map` |

Row-level codes (in the error report, not HTTP): `REQUIRED`, `NOT_A_NUMBER`,
`TOO_MANY_DECIMALS`, `NEGATIVE_STYLE`, `INVALID_DATE`, `DATE_TOO_OLD`, `DATE_IN_FUTURE`,
`NO_DATE`, `UNKNOWN_SUPPLIER`, `UNKNOWN_AGREEMENT`, `AGREEMENT_AMBIGUOUS`,
`CURRENCY_NOT_USD`, `RAGGED_ROW`, `TOO_LONG`, `TOO_LARGE`, `NOT_A_BOOLEAN`,
`PERIOD_INVALID`; warnings `SKU_SCIENTIFIC`, `AMOUNT_MISMATCH`, `DUPLICATE_ROW`.
