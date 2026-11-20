# Cloud commands — PREPARED, NOT RUN (CLAUDE.md §2: a person runs these after approval)

Replace `PROJECT_ID`, `ZONE`, `VM_NAME` and the bucket name. Read-only checks first.

## 1. Check the VM's service account and scopes (read-only)
```sh
gcloud compute instances describe VM_NAME --zone ZONE --project PROJECT_ID \
  --format="value(serviceAccounts[].email, serviceAccounts[].scopes)"
```
The `offsite` container authenticates as this service account. Its scopes must include
`devstorage.read_write` or `cloud-platform`; changing scopes needs the VM stopped (downtime
for every app on the VM) — decide before running.

## 2. Private backup bucket (cost: storage of ~a few GB, typically a few dollars a month)
```sh
gcloud storage buckets create gs://example-rebateledger-backups \
  --project PROJECT_ID --location REGION --uniform-bucket-level-access \
  --public-access-prevention --soft-delete-duration=7d

# Expire backups after 30 days — ONLY under archive/ (storage/ mirrors live uploads).
cat > lifecycle.json <<'JSON'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30, "matchesPrefix": ["archive/"]}}]}
JSON
gcloud storage buckets update gs://example-rebateledger-backups --lifecycle-file=lifecycle.json

# Least privilege: the VM service account may write objects to this bucket only.
gcloud storage buckets add-iam-policy-binding gs://example-rebateledger-backups \
  --member="serviceAccount:SA_EMAIL" --role="roles/storage.objectAdmin"
```

## 3. Uptime check and alert (SPEC §12)
```sh
gcloud monitoring uptime create rebateledger-login \
  --project PROJECT_ID --resource-type=uptime-url \
  --resource-labels=host=app.example.invalid,project_id=PROJECT_ID \
  --path=/login --protocol=https --period=5
```
UNVERIFIED: flag names of `gcloud monitoring uptime create` — check `--help` on the
installed gcloud before running. Attach an email notification channel in the console.

## 4. DNS (at your registrar or Cloud DNS)
- `app.example.invalid` and `www.example.invalid`: A record → the VM's external IP.
- Email: SPF, DKIM and DMARC records from the chosen email provider (ADR 0006, still OPEN).

## 5. Optional: dedicated production VM (ADR 0018 "safer alternative") — PREPARED, NOT RUN
Moves production off the shared VM (High risk). Cost estimate, UNVERIFIED — check the GCP pricing
calculator for your region: e2-standard-2 (2 vCPU, 8 GB) about $49/month on-demand plus a 50 GB
balanced disk about $5/month, plus egress. Pick a zone near your customers (US).
```sh
# Read-only first: confirm the image family and that the default HTTP/HTTPS firewall rules exist.
gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project ubuntu-os-cloud
gcloud compute firewall-rules list --project PROJECT_ID --filter="name~'default-allow-http'"

# The VM: its own service account scope covers the backup bucket (section 2 IAM binding).
gcloud compute instances create rebateledger-prod \
  --project PROJECT_ID --zone ZONE --machine-type e2-standard-2 \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 50GB --boot-disk-type pd-balanced \
  --scopes https://www.googleapis.com/auth/devstorage.read_write,https://www.googleapis.com/auth/logging.write \
  --tags http-server,https-server --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring

# Only if the list above was empty:
gcloud compute firewall-rules create default-allow-http-https --project PROJECT_ID \
  --allow tcp:80,tcp:443 --target-tags http-server,https-server
```
Then on the new VM: install Docker Engine from Docker's official apt repository, clone the repo,
and follow docs/runbooks/deploy.md "First install". Difference from the shared VM: there is no
host Caddy there, so a Caddy service must be added to `infra/prod/compose.yaml` (I will prepare it
once you choose this option). DNS then points at the new VM's external IP.
