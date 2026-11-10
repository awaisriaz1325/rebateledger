# ADR 0006 — Email provider shortlist (decision [OPEN])

Status: proposed — founder decision required (SPEC §15 item 2)

All mail goes through `app.emails.service.EmailAdapter`; locally Mailpit, in tests
an in-memory adapter. The production adapter is SMTP (any provider) unless the
chosen provider's API is needed.

| Provider | Notes (to verify at decision time — pricing not checked in this session) |
|---|---|
| Postmark | Strong transactional deliverability; separate message streams for transactional vs alerts |
| Amazon SES | Lowest cost at volume; more setup (sandbox exit, bounce handling) |
| Resend | Simple API/SMTP, modern DX |
| SendGrid | Widely used; shared IP reputation varies by plan |

Requirements regardless of choice: SMTP or HTTPS API from the worker only,
SPF + DKIM + DMARC on the sending domain, bounce/complaint webhooks considered in
Phase 11, no tracking pixels in security emails.
