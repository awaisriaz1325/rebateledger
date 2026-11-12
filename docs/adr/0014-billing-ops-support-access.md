# ADR 0014 — Invoice billing, operations console and support access

Status: accepted ([PROPOSED DEFAULT] items need founder confirmation)

## Decisions
1. **Invoice numbers** `PREFIX-YYYY-NNNN` come from `invoice_sequences` via one
   `INSERT … ON CONFLICT DO UPDATE … RETURNING` in the issuing transaction. The row lock
   serialises concurrent issuers; a rollback also rolls the counter back, so numbers
   never collide or skip. Tested with 12 concurrent issuers and a crash after numbering.
2. **Immutability** is enforced by DB triggers: issued invoices may only change status,
   payment, void and delivery bookkeeping columns; lines of non-draft invoices cannot
   change; issued invoices cannot be deleted. Corrections = void + reissue (a new draft
   linked by `replaces_id`). Drafts may be deleted.
3. **Seller details and payment instructions** live in `ops_settings` (never hard-coded)
   and are copied onto each invoice at issue. Issuing is refused until they are set.
4. **No tax computation** ([OPEN] SPEC §15); the PDF states that no tax was charged.
5. **Lapse**: a daily per-tenant `billing_lapse` job sends reminders (3 and 10 days before
   due [PROPOSED DEFAULT], then weekly when overdue) and moves the subscription to
   `past_due`. **Suspension is always a manual operator decision** (SPEC “MAY”); grace
   period 14 days [PROPOSED DEFAULT] is shown, not enforced automatically. Paying or
   voiding the overdue invoices clears `past_due`.
6. **Suspended = read-only**: every `write=True` route refuses with `TENANT_READ_ONLY`;
   export routes are not write routes, so exports keep working. The session carries
   `billing_status` so every member sees the banner.
7. **Ops console isolation**: `/ops` routes require `PlatformAdminOnly` (404 otherwise).
   Business tables have no platform RLS policy, so platform context cannot read them; the
   console gets aggregate usage only through `rl.tenant_usage()`, a `SECURITY DEFINER`
   function that refuses outside platform context and returns counts, never rows.
8. **Support access**: an operator can enter a tenant only while a tenant-granted,
   unexpired, unrevoked grant exists; read-only grants give view + export permissions
   only. Entering is audited in both the platform chain and the tenant's log; every
   request during the session is audited in the tenant's log. Revoking detaches all
   operator sessions from that tenant immediately.
9. **Pilot request form** is public, rate-limited (5/hour/IP), with a honeypot field and
   an identical response whether stored or discarded.
10. **Invoice emails** are queued as system emails (no tenant on the job row) because the
    operator issues them from platform context; they link to the billing page rather
    than attaching the PDF.
