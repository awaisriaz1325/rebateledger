# ADR 0006 — Email provider: Brevo (decided 2026-11-20)

Status: accepted (founder, 2026-11-20) — Brevo SMTP; the shortlist below is kept for history

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

## Decision (2026-11-20)
Brevo SMTP relay (`smtp-relay.brevo.com:587`, STARTTLS), the account that already authenticates
`imageme.tech` (Brevo DKIM keys `brevo1/2._domainkey`, DMARC `p=none`). Sender
`RebateLedger <no-reply@imageme.tech>`. Gmail was the alternative: a personal Gmail account can
only send as its `@gmail.com` address (custom-domain sending needs paid Google Workspace).
SMTP login verified from the devbox on 2026-11-20 (STARTTLS + AUTH: 235). Credentials live only
in `/var/lib/rebateledger/prod.env` on the VM.

Consequences: the free plan's daily limit (300/day per Brevo's site, UNVERIFIED for this
account) is shared with imageme; mail comes from `@imageme.tech`, not a RebateLedger domain.
Bounce/complaint webhooks are not wired (unchanged).
