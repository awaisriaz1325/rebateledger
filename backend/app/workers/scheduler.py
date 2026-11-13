"""Periodic tasks: stale-job recovery, daily audit-chain verification, reminders.

Run one instance: `python -m app.workers.scheduler`. Each tick only enqueues jobs;
the work itself runs in the worker.
"""

from __future__ import annotations

import signal
import threading
from datetime import datetime
from types import FrameType

import structlog
from sqlalchemy import select

from app.core.clock import utcnow
from app.core.logging import configure_logging
from app.db.models.identity import Tenant
from app.db.session import session_factory, set_platform_context
from app.workers.jobs import enqueue, recover_stale

log = structlog.get_logger("scheduler")
_stop_event = threading.Event()


def _stop(signum: int, frame: FrameType | None) -> None:
    _stop_event.set()


def enqueue_for_all_tenants(job_type: str) -> int:
    with session_factory()() as db, db.begin():
        set_platform_context(db, True)
        tenant_ids = list(db.execute(select(Tenant.id)).scalars())
    for tid in tenant_ids:
        with session_factory()() as db, db.begin():
            from app.db.session import set_tenant_context

            set_tenant_context(db, tid)
            enqueue(db, tenant_id=tid, job_type=job_type, payload={})
    return len(tenant_ids)


DAILY: dict[str, int] = {
    "verify_audit_chain": 3,
    "expire_exports": 4,
    "billing_lapse": 6,
    "claim_reminders": 13,
    "tier_alerts": 14,
    # Sends only on the organization's local Monday (the job checks). 12:00 UTC is Monday
    # morning across US time zones (07:00 Eastern standard time, 04:00 Pacific).
    "weekly_digest": 12,
}
"""job type → UTC hour at which it runs once a day."""
HOURLY: list[str] = []


def tick(now: datetime, last: dict[str, str]) -> None:
    recover_stale()
    for job_type, hour in DAILY.items():
        stamp = now.strftime("%Y-%m-%d")
        if now.hour >= hour and last.get(job_type) != stamp:
            n = enqueue_for_all_tenants(job_type)
            last[job_type] = stamp
            log.info("scheduled", job_type=job_type, tenants=n)
    for job_type in HOURLY:
        stamp = now.strftime("%Y-%m-%dT%H")
        if last.get(job_type) != stamp:
            enqueue_for_all_tenants(job_type)
            last[job_type] = stamp


def main() -> None:  # pragma: no cover - long-running process
    import app.services.registry  # noqa: F401

    configure_logging()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last: dict[str, str] = {}
    while not _stop_event.is_set():
        try:
            tick(utcnow(), last)
        except Exception:
            log.exception("scheduler_tick_failed")
        _stop_event.wait(60)


if __name__ == "__main__":  # pragma: no cover
    main()
