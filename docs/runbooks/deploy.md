# Runbook — deploy, rollback, first install (production VM, ADR 0018)

Every command runs on the VM, from the repo root, as a person. Nothing deploys automatically.
`compose` below means:
`RELEASE=<tag> docker compose -p rebateledger-prod -f infra/prod/compose.yaml --env-file /etc/rebateledger/prod.env`

## First install (once)
1. Run the prepared cloud commands in `infra/prod/gcloud-prepared.md` (bucket, IAM, DNS).
2. `sudo install -d -m 700 /etc/rebateledger` and create `/etc/rebateledger/prod.env` from
   `infra/prod/prod.env.example` with real values (`chmod 600`). Pin `CLOUD_CLI_IMAGE` to an
   exact tag checked on the official registry.
3. Add `infra/prod/Caddyfile.snippet` to the host Caddy and reload it.
4. `infra/prod/deploy.sh v1.1.0`
5. Create the operator account:
   `compose run --rm api rebateledger create-platform-admin --email … --name …`
6. Within 5 minutes: `gcloud storage ls gs://BUCKET/archive/wal/` shows WAL files.

## Every release
1. Locally: `make check` and `make e2e` green on the commit; tag it (`git tag v1.1.1`).
2. On the VM: `git fetch --tags && infra/prod/deploy.sh v1.1.1`
3. The script stops on any error. It prints `release … is up` after the smoke check.
4. Manual smoke: sign in, open the dashboard, download one report.
5. Check real client IPs: `compose logs api | tail` shows the visitor's IP, not 172.31.250.x.

## Rollback
- Code only (no migration in the release): `RELEASE=<previous tag> compose up -d` — the old
  images are still on the VM.
- With a migration: migrations are forward-only. Either ship a fix forward, or restore the
  pre-deploy base backup (docs/runbooks/restore.md, target = just before the deploy).

## Routine checks (weekly)
- `df -h /` (stop if under 5 GB free: `docker image prune` old release images).
- `compose ps` — all services healthy; `compose logs backup offsite | grep FAILED` is empty.
- Quarterly restore drill (docs/runbooks/restore.md, "Drill").
