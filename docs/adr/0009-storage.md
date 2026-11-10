# ADR 0009 — Object storage adapter: local filesystem in dev, GCS in cloud

Status: accepted

Options for local dev: MinIO container (S3 API parity) vs a filesystem adapter.
Decision: a `Storage` interface with `LocalStorage` (dev/test, under
`RL_STORAGE_DIR`, outside any web root) and `GcsStorage` (Phase 11). Keys are
`{tenant_id}/{kind}/{random}`; downloads always go through an authorised API
endpoint (re-check permission, `Content-Disposition: attachment`). Signed URLs
(GCS) live ≤ 15 minutes. One less container locally; the interface keeps cloud
behaviour testable.
