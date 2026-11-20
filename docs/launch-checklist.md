# Launch checklist (Phase 11) — founder signs off each line

| # | Item | Owner | Done |
|---|---|---|---|
| 1 | Real domains chosen; DNS A records point at the VM — domain `rebateledger.imageme.tech` (one host for app and public pages), DNS not yet set | Founder | ☐ |
| 2 | Email provider chosen (ADR 0006); SPF, DKIM, DMARC published; test email delivered | Founder | ☐ |
| 3 | `/var/lib/rebateledger/prod.env` filled with generated secrets (never in git) | Operator | ☐ |
| 4 | Backup bucket, lifecycle (archive/ only) and IAM created (`infra/prod/gcloud-prepared.md`) | Operator | ☐ |
| 5 | nginx server blocks in `~/nginx-extra` (HTTP, certificate, then HTTPS); HTTPS works on the domain | Operator | ☐ |
| 6 | `deploy.sh` smoke check passed; manual smoke (sign in, dashboard, report) passed | Operator | ☐ |
| 7 | Real client IPs visible in API logs (not 172.31.250.x) | Operator | ☐ |
| 8 | WAL files arriving in GCS within 5 minutes; first base backup present | Operator | ☐ |
| 9 | Restore drill done once (docs/runbooks/restore.md) and timed under 4 h — local rehearsal passed 2026-11-20; repeat on the production VM from GCS | Operator | ☐ |
| 10 | Uptime check and alert email tested (stop web briefly, alert arrives) | Operator | ☐ |
| 11 | Legal pages reviewed by a lawyer; `[LEGAL REVIEW REQUIRED]` removed (ADR 0015) | Founder | ☐ |
| 12 | Marketing `[PLACEHOLDER]` blocks and prices confirmed or removed | Founder | ☐ |
| 13 | SPEC §15 open items resolved or accepted | Founder | ☐ |
| 14 | No demo or E2E tenant in production | Operator | ☐ |
| 15 | Operator account created with MFA; ops IP allowlist set if wanted | Operator | ☐ |
| 16 | Accountant review of the accrual journal, or the page labelled beta | Founder | ☐ |
| 17 | Re-measure the 50 × 1M calculation run on this VM; record in load-tests.md | Operator | ☐ |
| 18 | Disk: at least 10 GB free after the first deploy | Operator | ☐ |
