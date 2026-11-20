# ADR 0020 — Production on the VM `opspilot-production` (revises ADR 0018)

Status: accepted (founder, 2026-11-20)

## Context
ADR 0018 put production on the devbox VM with its host Caddy. The founder chose instead the
existing production VM `opspilot-production` (us-central1-a), which runs OpsPilot (nginx +
certbot on ports 80/443, Container-Optimized OS) and, since 2026-11-20, imageme. It had 772 MB
of 4 GB available; an on-VM image build took OpsPilot down for ~50 minutes on 2026-11-20.
Domain: `rebateledger.imagenet.tech`, one host for the app and the public pages.

## Decision
- **Resize** the VM to e2-standard-2 (8 GB) (founder approved; ~$25/month more, UNVERIFIED).
- **Build on the devbox, never on the VM.** `infra/prod/deploy.sh <tag>` builds both images
  from the git tag, copies them and the infra files over IAP, and runs `infra/prod/vm-release.sh`
  on the VM (pre-deploy base backup, migrate, start, smoke check). The VM keeps the current and
  previous release for rollback.
- **Compose** runs from a pinned `docker:29.1.3-cli` container (COS has no runnable compose;
  `/home` is noexec), with the release directory mounted at the same path.
- **TLS and routing**: OpsPilot's nginx, through its existing `~/nginx-extra` include (as
  imageme does). Server blocks in `infra/prod/nginx/`; the certificate is issued and renewed
  by OpsPilot's certbot container. The web container joins OpsPilot's network
  (`opspilot-clinic-frontdesk_default`) with the alias `rebateledger-web`; no host port.
- **Secrets**: `/var/lib/rebateledger/prod.env` (root, 600). UNVERIFIED: `/etc` on COS does not
  persist across reboots, `/var` does.
- **Memory caps** (`mem_limit`) on every RebateLedger container, ~3.7 GB in total; idle use
  ~590 MB (measured locally on 2026-11-20).
- Unchanged from ADR 0018: own Postgres 18 and Redis, WAL archiving + nightly base backup
  mirrored to GCS, uptime check, no automatic deploys, no staging.

## Consequences and risks
- **Medium: shared machine.** OpsPilot, imageme and RebateLedger share 8 GB and one disk; the
  memory caps limit, but do not remove, the effect one app can have on another.
- **Medium: nginx is shared.** A broken server block stops all three sites; always `nginx -t`
  before a reload, and install the HTTPS block only after the certificate exists.
- **Medium: cost mode.** When OpsPilot's VM is stopped to save money, RebateLedger is down too.
- **Low: shared network.** OpsPilot and imageme containers can reach the RebateLedger web
  container directly and could forge `X-Forwarded-For` (affects rate limits and the ops IP
  allowlist only). The API itself is not on that network.
- **Low: bucket access.** Any container on the VM can use the VM's service account, which may
  manage objects in the backup bucket; soft delete (7 days) limits the damage.
