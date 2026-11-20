# Launch checklist (Phase 11) — founder signs off each line

| # | Item | Owner | Done |
|---|---|---|---|
| 1 | Real domains chosen; DNS A records point at the VM — domain `rebateledger.imageme.tech` (one host for app and public pages) → 34.135.27.193 | Founder | ☑ 2026-11-20 |
| 2 | Email provider chosen (ADR 0006); SPF, DKIM, DMARC published; test email delivered — Brevo, DKIM + DMARC already on imageme.tech, SMTP login verified; password-reset email sent through Brevo 2026-11-20 (founder to confirm inbox + DKIM pass) | Founder | ☐ |
| 3 | `/var/lib/rebateledger/prod.env` filled with generated secrets (never in git) | Operator | ☑ 2026-11-20 |
| 4 | Backup bucket, lifecycle (archive/ only) and IAM created (`infra/prod/gcloud-prepared.md`) | Operator | ☑ 2026-11-20 |
| 5 | nginx server blocks in `~/nginx-extra` (HTTP, certificate, then HTTPS); HTTPS works on the domain (Let's Encrypt, expires 2027-02-18, renewed by OpsPilot's certbot) | Operator | ☑ 2026-11-20 |
| 6 | `deploy.sh` smoke check passed (v1.3.0, 2026-11-20); manual smoke (sign in, dashboard, report) passed — needs the operator account | Operator | ☐ |
| 7 | Real client IPs visible in API logs (not 172.31.250.x) — verified 2026-11-20 | Operator | ☑ 2026-11-20 |
| 8 | WAL files arriving in GCS within 5 minutes; first base backup present — verified 2026-11-20 (archived 4, failed 0) | Operator | ☑ 2026-11-20 |
| 9 | Restore drill done once (docs/runbooks/restore.md) and timed under 4 h — local rehearsal passed 2026-11-20; repeat on the production VM from GCS | Operator | ☐ |
| 10 | Uptime check and alert email tested (stop web briefly, alert arrives) — check + email alert policy created 2026-11-20, not yet tested | Operator | ☐ |
| 11 | Legal pages reviewed by a lawyer; `[LEGAL REVIEW REQUIRED]` removed (ADR 0015) | Founder | ☐ |
| 12 | Marketing `[PLACEHOLDER]` blocks and prices confirmed or removed | Founder | ☐ |
| 13 | SPEC §15 open items resolved or accepted | Founder | ☐ |
| 14 | No demo or E2E tenant in production | Operator | ☐ |
| 15 | Operator account created with MFA; ops IP allowlist set if wanted — created 2026-11-20, MFA set-up at first sign-in pending | Operator | ☐ |
| 16 | Accountant review of the accrual journal, or the page labelled beta | Founder | ☐ |
| 17 | Re-measure the 50 × 1M calculation run on this VM; record in load-tests.md | Operator | ☐ |
| 18 | Disk: at least 10 GB free after the first deploy | Operator | ☐ |
