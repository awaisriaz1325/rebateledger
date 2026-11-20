# ADR 0018 — Production on the shared GCP VM (deviation from SPEC §13)

Status: accepted (founder, 2026-11-17); hosting, TLS and deploy revised by ADR 0020 (2026-11-20)

## Context
SPEC §13 planned Cloud Run + Cloud SQL. The founder chose to run production on the existing
GCP VM (4 vCPU, 14 GB RAM, ~19 GB disk free), which also hosts other apps (frontdesk,
collabspace, imageme), the RebateLedger dev/test databases, a GitHub Actions runner and
interactive development sessions. Domains are placeholders until the founder supplies them.

## Decision
- Docker Compose project `rebateledger-prod` (`infra/prod/compose.yaml`): api, worker,
  scheduler, web, its own Postgres 18 and Redis 8, a `backup` and an `offsite` container.
  Separate volumes and a fixed network (172.31.250.0/24) from the dev stack.
- TLS and routing: the existing host Caddy (imageme) gets a site block
  (`infra/prod/Caddyfile.snippet`) proxying to `127.0.0.1:3200` (web). The API is not
  exposed; the web container reaches it as `http://api:8000` (build argument).
- Client IPs: uvicorn trusts `X-Forwarded-For` only from the stack network, so rate limits,
  lockout and the ops IP allowlist see the real client (Caddy discards client-sent values).
- Secrets: `/etc/rebateledger/prod.env`, root-owned, mode 600 — instead of Secret Manager.
- Backups (ADR 0016: RPO ≤ 5 min, RTO ≤ 4 h): WAL archiving (`archive_timeout=60`) plus a
  nightly base backup, mirrored every minute to a private GCS bucket (30-day lifecycle on
  `archive/`, soft delete 7 days); uploaded files mirrored to the same bucket.
- Deploys: `infra/prod/deploy.sh <tag>` run by a person (build, pre-deploy base backup,
  migrate, start, smoke check). No automatic production deploys.
- Monitoring: container health checks and restart policies, rotated JSON logs, a GCP uptime
  check on `/login` (prepared in `infra/prod/gcloud-prepared.md`).

## Cost
| Item | Monthly (estimate, unverified) |
|---|---|
| VM | $0 extra (already paid) |
| GCS backups (a few GB) | a few dollars |
| Uptime check | free tier |
Cloud Run + Cloud SQL was estimated at roughly $100–150/month.

## Consequences and risks
- **High: shared machine.** Dev tests, other apps and the CI runner compete for CPU, memory
  and disk; a mistake in another project (or a full disk) can take production down. Safer
  alternative: a dedicated small VM in the same project (~$50–60/month) using the same files.
- **Medium: single machine, no failover.** Recovery is by restore (docs/runbooks/restore.md).
- **Medium: disk.** ~19 GB free; images, the database and local WAL compete. Watch `df`.
- Staging: there is no separate staging environment; release candidates are checked locally
  (make check, E2E) before `deploy.sh`.
