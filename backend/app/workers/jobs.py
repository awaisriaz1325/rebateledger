"""Durable jobs: a `jobs` row + a Dramatiq message (ADR 0003).

- ``enqueue`` inserts the row in the caller's transaction and sends the message
  only after commit, so a rolled-back request never starts work.
- Handlers run inside a tenant-scoped transaction and report progress through
  short separate transactions (live progress, SPEC §4.5.2).
- Failures retry with exponential backoff; after ``max_attempts`` the job is
  ``dead`` (visible in the ops job monitor, retryable from there).
- ``queue_key`` serialises jobs (e.g. one active calculation run per tenant).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import JobsMode, get_settings
from app.core.security import _fernet
from app.db.models.identity import Job, JobStatus
from app.db.session import session_factory, set_platform_context, set_tenant_context

log = structlog.get_logger("jobs")


class JobCancelledError(Exception):
    pass


class RetryLaterError(Exception):
    """Raised by the runner when a job must wait for its queue_key."""


@dataclass
class JobContext:
    job_id: uuid.UUID
    tenant_id: uuid.UUID | None
    payload: dict[str, Any]
    created_by: uuid.UUID | None

    def progress(self, done: int, total: int | None = None) -> None:
        """Commit progress immediately in its own transaction; checks for cancellation."""
        with session_factory()() as db, db.begin():
            _scope(db, self.tenant_id)
            values: dict[str, Any] = {"progress": done, "heartbeat_at": utcnow()}
            if total is not None:
                values["total"] = total
            db.execute(update(Job).where(Job.id == self.job_id).values(**values))
            cancelled = db.execute(
                select(Job.cancel_requested).where(Job.id == self.job_id)
            ).scalar()
        if cancelled:
            raise JobCancelledError()


Handler = Callable[[Session, JobContext], dict[str, Any] | None]
HANDLERS: dict[str, Handler] = {}


def handler(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return deco


def _scope(db: Session, tenant_id: uuid.UUID | None) -> None:
    if tenant_id is None:
        set_platform_context(db, True)
    else:
        set_tenant_context(db, tenant_id)


def seal(data: dict[str, Any]) -> dict[str, Any]:
    """Encrypt a sensitive payload (e.g. email links) so it is never stored in clear."""
    return {"sealed": _fernet().encrypt(json.dumps(data).encode()).decode()}


def unseal(payload: dict[str, Any]) -> dict[str, Any]:
    if "sealed" not in payload:
        return payload
    data: dict[str, Any] = json.loads(_fernet().decrypt(payload["sealed"].encode()))
    return data


def enqueue(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    job_type: str,
    payload: dict[str, Any] | None = None,
    created_by: uuid.UUID | None = None,
    queue_key: str | None = None,
    max_attempts: int = 3,
) -> Job:
    if job_type not in HANDLERS:
        raise KeyError(f"no handler registered for job type {job_type}")
    job = Job(
        tenant_id=tenant_id,
        type=job_type,
        payload=payload or {},
        created_by=created_by,
        queue_key=queue_key,
        max_attempts=max_attempts,
        status=JobStatus.QUEUED.value,
    )
    db.add(job)
    db.flush()
    db.info.setdefault("after_commit_jobs", []).append((job.id, tenant_id))
    return job


@event.listens_for(Session, "after_commit")
def _dispatch_after_commit(db: Session) -> None:
    # Releasing a SAVEPOINT also fires after_commit, before the real COMMIT: the job row is
    # not visible to other sessions yet. Keep the jobs until the outermost commit.
    if db.in_nested_transaction():
        return
    pending: list[tuple[uuid.UUID, uuid.UUID | None]] = db.info.pop("after_commit_jobs", [])
    for job_id, tenant_id in pending:
        try:
            dispatch(job_id, tenant_id)
        except Exception as exc:  # noqa: BLE001 - the job row is committed; recovery re-dispatches it
            log.warning("job_dispatch_failed", job_id=str(job_id), error_type=type(exc).__name__)


@event.listens_for(Session, "after_rollback")
def _forget_after_rollback(db: Session) -> None:
    db.info.pop("after_commit_jobs", None)


def dispatch(job_id: uuid.UUID, tenant_id: uuid.UUID | None, delay_ms: int = 0) -> None:
    if get_settings().jobs_mode is JobsMode.INLINE:
        try:
            run_job(job_id, tenant_id)
        except RetryLaterError:  # pragma: no cover - inline jobs run one at a time
            pass
        except Exception:  # noqa: BLE001 - status already recorded on the job row
            log.debug("inline_job_failed", job_id=str(job_id))
        return
    from app.workers.broker import execute_job

    execute_job.send_with_options(
        args=(str(job_id), str(tenant_id) if tenant_id else None), delay=delay_ms or None
    )


def run_job(job_id: uuid.UUID, tenant_id: uuid.UUID | None) -> None:
    # 1. Claim the job.
    with session_factory()() as db, db.begin():
        _scope(db, tenant_id)
        job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED.value:
            return
        if job.cancel_requested:
            job.status, job.finished_at = JobStatus.CANCELLED.value, utcnow()
            return
        if job.queue_key:
            busy = db.execute(
                select(Job.id).where(
                    Job.queue_key == job.queue_key,
                    Job.status == JobStatus.RUNNING.value,
                    Job.id != job.id,
                )
            ).first()
            if busy:
                raise RetryLaterError()
        job.status = JobStatus.RUNNING.value
        job.attempts += 1
        job.started_at = job.heartbeat_at = utcnow()
        ctx = JobContext(job.id, job.tenant_id, unseal(job.payload), job.created_by)
        job_type = job.type
        attempts, max_attempts = job.attempts, job.max_attempts

    # 2. Run it.
    log.info("job_started", job_id=str(job_id), job_type=job_type, attempt=attempts)
    try:
        with session_factory()() as db, db.begin():
            _scope(db, tenant_id)
            result = HANDLERS[job_type](db, ctx)
    except JobCancelledError:
        _finish(job_id, tenant_id, JobStatus.CANCELLED, None, None)
        return
    except Exception as exc:
        final = attempts >= max_attempts
        error = {"code": "JOB_FAILED", "message": _safe_message(exc), "type": type(exc).__name__}
        log.warning(
            "job_failed",
            job_id=str(job_id),
            job_type=job_type,
            final=final,
            error_type=type(exc).__name__,
        )
        _finish(job_id, tenant_id, JobStatus.DEAD if final else JobStatus.QUEUED, None, error)
        if not final:
            raise
        return
    _finish(job_id, tenant_id, JobStatus.SUCCEEDED, result or {}, None)
    log.info("job_succeeded", job_id=str(job_id), job_type=job_type)


def _safe_message(exc: Exception) -> str:
    """User-facing message: only from exceptions that declare one."""
    message = getattr(exc, "user_message", None)
    return str(message) if message else "The job failed. It was logged; you can retry it."


def _finish(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    status: JobStatus,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> None:
    with session_factory()() as db, db.begin():
        _scope(db, tenant_id)
        job = db.get(Job, job_id)
        if job is None:  # pragma: no cover
            return
        job.status = status.value
        job.result = result
        job.error = error
        if status is not JobStatus.QUEUED:
            job.finished_at = utcnow()
        if status is JobStatus.SUCCEEDED and "sealed" in job.payload:
            job.payload = {}  # wipe sealed secrets once used


ORPHAN_AFTER = timedelta(minutes=5)


def recover_stale(max_age: timedelta = timedelta(minutes=10)) -> list[uuid.UUID]:
    """Jobs left `running` by a killed worker go back to the queue (or dead); queued jobs
    that were never picked up (lost dispatch) are dispatched again."""
    cutoff = utcnow() - max_age
    recovered: list[tuple[uuid.UUID, uuid.UUID | None]] = []
    with session_factory()() as db, db.begin():
        set_platform_context(db, True)
        stale = (
            db.execute(
                select(Job)
                .where(Job.status == JobStatus.RUNNING.value, Job.heartbeat_at < cutoff)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        orphaned = (
            db.execute(
                select(Job)
                .where(
                    Job.status == JobStatus.QUEUED.value,
                    Job.started_at.is_(None),
                    Job.cancel_requested.is_(False),
                    Job.created_at < utcnow() - ORPHAN_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        # Queued jobs whose dispatch was lost (broker outage at commit): send them again.
        recovered.extend((job.id, job.tenant_id) for job in orphaned)
        for job in stale:
            if job.attempts >= job.max_attempts:
                job.status, job.finished_at = JobStatus.DEAD.value, utcnow()
                job.error = {
                    "code": "WORKER_LOST",
                    "message": "The worker stopped while running this job.",
                }
            else:
                job.status = JobStatus.QUEUED.value
                recovered.append((job.id, job.tenant_id))
    for job_id, tenant_id in recovered:
        try:
            dispatch(job_id, tenant_id)
        except Exception as exc:  # noqa: BLE001 - next scheduler tick retries
            log.warning("job_dispatch_failed", job_id=str(job_id), error_type=type(exc).__name__)
    return [j for j, _ in recovered]
