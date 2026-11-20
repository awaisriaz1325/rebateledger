# Cloud commands — PREPARED, NOT RUN (CLAUDE.md §2: a person runs these after approval)

Production VM: `opspilot-production` (ADR 0020). Values from OpsPilot's own docs, check them:
```sh
P=project-8540c9da-5229-461c-bba
Z=us-central1-a
R=us-central1
BUCKET=project-8540c9da-5229-461c-bba-rebateledger-backups   # must be globally unique
```

## 1. Read-only checks first
```sh
gcloud compute instances describe opspilot-production --zone $Z --project $P \
  --format="value(machineType.basename(), serviceAccounts[].email, serviceAccounts[].scopes)"
gcloud compute addresses list --project $P --filter="name=opspilot-production-ip"
```
The `offsite` container uploads backups as the VM's service account (metadata server). Its
scopes must include `devstorage.read_write` or `cloud-platform`. If they do not, add one in
step 2 while the VM is stopped anyway, keeping every scope it already has (OpsPilot needs them).

## 2. Resize to e2-standard-2 — DONE 2026-11-20 15:34–15:36 UTC (founder's go-ahead)
Result: 2 vCPU, 7.9 GB, 5.1 GB available; all 28 containers back, OpsPilot healthy at 15:40.
The service account already has the `cloud-platform` scope: no scope change needed.

The VM had 772 MB available of 4 GB with OpsPilot and imageme; RebateLedger idles at ~590 MB
(measured locally, all 8 containers) and is capped at ~3.7 GB. Cost: about $49/month instead of
about $24 (UNVERIFIED estimate for us-central1, on-demand; check the pricing calculator).
Downtime: a few minutes for OpsPilot and imageme. The static IP is kept.
```sh
gcloud compute instances stop opspilot-production --zone $Z --project $P
gcloud compute instances set-machine-type opspilot-production --zone $Z --project $P --machine-type e2-standard-2
# Only if step 1 showed no storage scope (list ALL current scopes plus the new one):
# gcloud compute instances set-service-account opspilot-production --zone $Z --project $P \
#   --service-account SA_EMAIL --scopes CURRENT_SCOPES,https://www.googleapis.com/auth/devstorage.read_write
gcloud compute instances start opspilot-production --zone $Z --project $P
```
Then follow OpsPilot's `docs/ops-cost-mode.md` start-up checks, and run `free -m` on the VM.

## 3. Private backup bucket (a few GB: typically a few dollars a month)
```sh
gcloud storage buckets create gs://$BUCKET --project $P --location $R \
  --uniform-bucket-level-access --public-access-prevention --soft-delete-duration=7d

# Expire backups after 30 days — ONLY under archive/ (storage/ mirrors live uploads).
cat > lifecycle.json <<'JSON'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30, "matchesPrefix": ["archive/"]}}]}
JSON
gcloud storage buckets update gs://$BUCKET --lifecycle-file=lifecycle.json

# The VM's service account may manage objects in this bucket only.
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member="serviceAccount:SA_EMAIL" --role="roles/storage.objectAdmin"
```

## 4. Uptime check and alert (SPEC §12)
```sh
gcloud monitoring uptime create rebateledger-login --project $P --resource-type=uptime-url \
  --resource-labels=host=rebateledger.imageme.tech,project_id=$P \
  --path=/login --protocol=https --period=5
```
UNVERIFIED: flag names of `gcloud monitoring uptime create` — check `--help` on the installed
gcloud before running. Attach an email notification channel in the console.

## 5. DNS (wherever `imageme.tech` is hosted)
- `rebateledger.imageme.tech`: A record → the VM's static IP from step 1
  (`34.135.27.193`, `opspilot-production-ip`, checked 2026-11-20; OpsPilot's docs say 35.222.55.6, outdated).
- Email: SPF, DKIM and DMARC records from the chosen email provider (ADR 0006, still OPEN).
