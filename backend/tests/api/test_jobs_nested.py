"""A job enqueued by a running job must be dispatched when the parent commits."""

from __future__ import annotations

from typing import Any

from app.db.session import tenant_session
from app.workers import jobs
from tests.api.conftest import World

RAN: list[str] = []


@jobs.handler("test_child")
def _child(db: Any, job: jobs.JobContext) -> dict[str, Any]:
    RAN.append("child")
    return {}


@jobs.handler("test_parent")
def _parent(db: Any, job: jobs.JobContext) -> dict[str, Any]:
    jobs.enqueue(db, tenant_id=job.tenant_id, job_type="test_child")
    RAN.append("parent")
    return {}


def test_job_enqueued_inside_a_job_runs(world: World) -> None:
    RAN.clear()
    t = world.tenant()
    with tenant_session(t) as db:
        jobs.enqueue(db, tenant_id=t, job_type="test_parent")
    assert RAN == ["parent", "child"]


@jobs.handler("test_parent_savepoint")
def _parent_savepoint(db: Any, job: jobs.JobContext) -> dict[str, Any]:
    db.begin_nested()  # like the import commit job (all-or-nothing savepoint)
    jobs.enqueue(db, tenant_id=job.tenant_id, job_type="test_child")
    RAN.append("parent")
    return {}


def test_job_enqueued_inside_a_savepoint_runs(world: World) -> None:
    RAN.clear()
    t = world.tenant()
    with tenant_session(t) as db:
        jobs.enqueue(db, tenant_id=t, job_type="test_parent_savepoint")
    assert RAN == ["parent", "child"]
