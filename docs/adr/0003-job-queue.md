# ADR 0003 — Background jobs: Dramatiq on Redis + a durable `jobs` table

Status: accepted

## Options
- **RQ** — simple, but retries/backoff and dead-letter need extra code.
- **Celery** — powerful, heavy configuration surface, many moving parts.
- **arq** — async-only (conflicts with ADR 0002).
- **Dramatiq** — retries with exponential backoff, time limits and a dead-letter
  queue built into its Redis broker; small API.

## Decision
Dramatiq with one generic actor `execute_job(job_id, tenant_id)`. Every job also
has a row in `jobs` (status, progress, result, error, attempts, queue_key) that
backs `GET /api/v1/jobs/{id}` and the ops job monitor.

- Messages are sent only **after commit** (SQLAlchemy `after_commit`), so a
  rolled-back request never starts work.
- `queue_key` serialises jobs (one active calculation run per tenant).
- `max_attempts` reached → `dead` (visible, retryable from the ops console).
- A scheduler process re-queues jobs whose heartbeat is stale (killed worker).
- Payloads that contain secrets (email links) are sealed with Fernet and wiped
  after success.
- Tests run jobs inline after commit (`RL_JOBS_MODE=inline`).
