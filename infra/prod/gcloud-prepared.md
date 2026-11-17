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
