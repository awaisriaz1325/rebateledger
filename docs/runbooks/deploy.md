# Runbook — deploy, rollback, first install (production VM `opspilot-production`, ADR 0020)

Production runs on `opspilot-production` (us-central1-a), next to OpsPilot and imageme. Images
are **built on the devbox**, never on the VM (an on-VM build took OpsPilot down on 2026-11-20).
Nothing deploys automatically; a person runs every step.

SSH to the VM (IAP only): `gcloud compute ssh opspilot-production --zone us-central1-a --tunnel-through-iap`

On the VM, `compose` below means this shell function (paste it into the session). Compose runs
from a pinned container because Container-Optimized OS has no runnable compose plugin:
```sh
compose() {
  REF=$(cat ~/rebateledger/current); DIR=~/rebateledger/releases/$REF
  sudo docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$DIR:$DIR:ro" -w "$DIR" \
    -v /var/lib/rebateledger:/var/lib/rebateledger:ro -e RELEASE="$REF" docker:29.1.3-cli \
    docker compose -p rebateledger-prod -f infra/prod/compose.yaml \
    --env-file /var/lib/rebateledger/prod.env "$@"
}
```
(Add `-it` after `--rm` for interactive commands such as `compose exec postgres psql …`.)

## First install (once)
1. **Resize the VM** and check its service account (`infra/prod/gcloud-prepared.md` §1–2).
2. **Bucket and IAM** (`gcloud-prepared.md` §3). **DNS**: A record
   `rebateledger.imagenet.tech` → the VM's static IP (`gcloud-prepared.md` §5).
3. **Secrets** on the VM:
   `sudo install -d -m 700 /var/lib/rebateledger`, then create `/var/lib/rebateledger/prod.env`
   from `infra/prod/prod.env.example` with real values (`sudo chmod 600`). Generate every
   password and key (commands in the example's header); `REDIS_PASSWORD` goes into
   `RL_REDIS_URL` too. Pin `CLOUD_CLI_IMAGE` to an exact tag checked on the official registry.
   Set `BACKUP_BUCKET`, the SMTP values (email provider, ADR 0006) and
   `RL_PLATFORM_ADMIN_IP_ALLOWLIST`.
4. **TLS, stage 1** (HTTP only): copy `infra/prod/nginx/rebateledger-http.conf` to
   `~/nginx-extra/` on the VM, then in `~/opspilot-clinic-frontdesk` with OpsPilot's `$DC $CF`
   (defined in its `docs/ops-cost-mode.md` §5.3): `$DC $CF exec nginx nginx -t` and
   `$DC $CF exec nginx nginx -s reload`.
5. **Certificate** (once DNS resolves to the VM), with OpsPilot's certbot:
   `$DC $CF run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot -d rebateledger.imagenet.tech --agree-tos -m <ops email> -n`
   It is renewed by OpsPilot's certbot container from then on.
6. **TLS, stage 2**: only after `~/opspilot-clinic-frontdesk/letsencrypt/live/rebateledger.imagenet.tech/`
   exists, copy `infra/prod/nginx/rebateledger-https.conf` to `~/nginx-extra/`, run `nginx -t`,
   then reload (as in step 4). A wrong file here stops nginx for OpsPilot and imageme too:
   never reload without a passing `nginx -t`.
7. **Deploy** from the devbox: tag the release, push the tag, run `infra/prod/deploy.sh v1.3.0`.
   The first deploy also starts the RebateLedger web container on OpsPilot's network.
8. **Operator account** (on the VM):
   `compose run --rm api rebateledger create-platform-admin --email … --name …`
9. Within 5 minutes: `gcloud storage ls gs://BUCKET/archive/wal/` shows WAL files.

## Every release
1. On the devbox: `make check` and `make e2e` green on the commit; tag it (`git tag v1.3.1`)
   and push the tag.
2. On the devbox: `infra/prod/deploy.sh v1.3.1` (builds, uploads ~400 MB over IAP, then on the
   VM: pre-deploy base backup, migrate, start, smoke check). It stops on any error and prints
   `release … is up` after the smoke check.
3. Manual smoke: `https://rebateledger.imagenet.tech` — sign in, open the dashboard, download
   one report.
4. Real client IPs: `compose logs api | tail` shows visitors' IPs or nginx's network address,
   never `172.31.250.x`.

## Rollback
The VM keeps the current and the previous release (images and files).
- Code only (no migration in the release), from the devbox:
  `gcloud compute ssh opspilot-production --zone us-central1-a --tunnel-through-iap --command "sh -s -- <previous tag> docker:29.1.3-cli rollback" < infra/prod/vm-release.sh`
- With a migration: migrations are forward-only. Either ship a fix forward, or restore the
  pre-deploy base backup (docs/runbooks/restore.md, target = just before the deploy).

## Routine checks (weekly)
- `df -h /mnt/stateful_partition` (stop if under 5 GB free).
- `free -m`: RebateLedger is capped at about 3.7 GB in total (`mem_limit` in compose); if the
  VM runs short, `sudo docker stats --no-stream` shows which app is using it.
- `compose ps` — all services healthy; `compose logs backup offsite | grep FAILED` is empty.
- Quarterly restore drill (docs/runbooks/restore.md, "Drill").
- If OpsPilot's VM is stopped to save money (its `docs/ops-cost-mode.md`), RebateLedger is down
  too; containers restart with Docker when the VM starts.
