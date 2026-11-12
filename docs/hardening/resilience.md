# Resilience drills (Phase 10)

Run: 2026-11-12, local docker-compose stack (Postgres 18, Redis 8). Separate API
(uvicorn :8100) and Dramatiq worker processes started by the script. Re-run with:

    cd backend && set -a && . ./.env.example && set +a && uv run python scripts/resilience_drill.py

The worker is killed with SIGKILL (no graceful shutdown), which is the worst case: the
same thing happens when a Cloud Run instance is reclaimed. Recovery is
`app.workers.jobs.recover_stale`, run by the scheduler. Running jobs whose heartbeat is
stale are re-queued, and queued jobs never picked up within 5 minutes are re-dispatched.
The drill calls it with a zero age so it does not wait.

## Result (actual output)

| Drill | What happened | Result |
|---|---|---|
| A. Kill worker during import commit (300,000 rows) | Killed at job progress 10,000; rows visible after kill: 0; batch showed `committing`; recovery re-queued the job; final `committed` with 300,000 rows (attempt 2) | PASS |
| B. Kill worker during a calculation run | Results visible after kill: 0; run showed `queued`; after recovery `succeeded` with 24 period results (uninterrupted control run: 24) | PASS |
| C. Kill worker during PDF export | Job was `running` when killed; after recovery the export is `succeeded` (20484 bytes) | PASS |
| D. Restart Redis | Ready again after 4.2 s; a run started afterwards returned 202 and finished `succeeded` (worker reconnected) | PASS |
| E. Restart PostgreSQL | `/readyz` answered 503 while restarting; ready after 0.8 s; existing session works (200) without restarting the API (pool pre-ping) | PASS |

## What this shows

- **No partial data.** An import commits in one transaction, and a run writes its results
  in one transaction. After a kill, readers see 0 rows, never half a batch or half a run.
- **Jobs resume.** Re-running a job is safe: the import commit is idempotent on its batch
  and the run recomputes from the same inputs. The `attempts` counter shows the retry.
- **User message.** While a job is being recovered, the screen keeps showing its last
  status with progress ("Waiting for a worker…" or "N of M steps done…"). If retries are
  exhausted the job ends `failed` (`JOB_FAILED` / `WORKER_LOST`, `docs/error-codes.md`).
  The import wizard then says "The commit did not finish. Nothing was saved." (or
  "Validation did not finish. Try again."), and the run page shows "This run failed. The
  run stopped before finishing. No results were saved."
- **Broker outage at commit** (found while preparing drill D): the after-commit dispatch
  used to raise, which turned a committed request into a 500 with a job stuck in
  `queued`. Fixed. Dispatch failures are logged, and orphaned queued jobs are
  re-dispatched. Regression test:
  `tests/api/test_jobs_platform.py::test_broker_outage_at_commit_keeps_the_request_ok_and_the_job_recoverable`.
- **Database restart.** `/readyz` reports 503 while the database is down, so the load
  balancer drains the instance. Pooled connections are re-validated (`pool_pre_ping`), so
  the API needs no restart.

## Known limits

- During a Redis outage, rate-limited endpoints (login, pilot form) fail closed: users
  cannot sign in for the few seconds Redis is down. This is accepted as the safer default;
  Memorystore HA is planned for Phase 11.
- The drill ran on one machine. Zone or region failure is a Phase 11 infrastructure
  concern (Cloud SQL HA, PITR).
