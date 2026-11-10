---
paths:
  - "backend/**/*.py"
---

# Backend rules (FastAPI)

- Route handlers are thin: parse input, check permission, call a service,
  return a response model. No business logic or SQL in handlers.
- Every route declares an explicit permission dependency. A route without one
  must fail a test (enforced by a test that walks the app's route table).
- Every query that touches tenant data runs inside a transaction that sets the
  tenant context for Row-Level Security, and also filters by `tenant_id` in the
  query itself (defence in depth).
- The application connects to Postgres as a non-owner role without the
  `BYPASSRLS` attribute. Migrations run as a separate owner role.
- Errors use RFC 9457 Problem Details (`application/problem+json`) with a stable
  `code` field. Never return stack traces, SQL or internal paths to clients.
- Request and response models are Pydantic v2 with strict types, length limits
  on every string, and explicit enums. Reject unknown fields on input.
- Money fields are serialized as decimal strings, never JSON numbers.
- Mutating endpoints that create imports, runs, claims or invoices accept an
  `Idempotency-Key` header. Updates to agreements and claims use optimistic
  locking (`ETag` / `If-Match`, 412 on mismatch).
- Long work (imports, calculation runs, exports, PDFs, emails) runs in the
  background worker and returns `202 Accepted` with a job resource.
- Every state change that matters to a finance auditor writes an audit event in
  the same transaction as the change.
- Use parameterized queries only. No f-strings or string concatenation in SQL.
- Outbound HTTP: none from request paths except the configured email provider.
  Never fetch a URL supplied by a user.
