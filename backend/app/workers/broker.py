"""Dramatiq broker and the single generic actor that runs jobs by id."""

from __future__ import annotations

import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker

from app.core.config import JobsMode, get_settings
from app.workers.jobs import RetryLaterError, run_job

_settings = get_settings()
if _settings.jobs_mode is JobsMode.INLINE:  # pragma: no cover - tests never send messages
    dramatiq.set_broker(StubBroker())
else:
    dramatiq.set_broker(RedisBroker(url=_settings.redis_url.get_secret_value()))  # type: ignore[no-untyped-call]


def _retry_when(retries: int, exc: BaseException) -> bool:
    return isinstance(exc, RetryLaterError) or retries < 3


@dramatiq.actor(
    queue_name="jobs",
    max_retries=50,
    min_backoff=5_000,
    max_backoff=300_000,
    retry_when=_retry_when,
    time_limit=60 * 60 * 1000,
)
def execute_job(job_id: str, tenant_id: str | None) -> None:
    run_job(uuid.UUID(job_id), uuid.UUID(tenant_id) if tenant_id else None)
