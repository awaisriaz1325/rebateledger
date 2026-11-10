"""Job framework, platform-admin bootstrap, scheduler, email rendering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.identity import Job
from app.db.session import tenant_session
from app.emails.service import RenderedEmail, render
from app.workers import jobs
from app.workers.jobs import JobContext, enqueue, handler, recover_stale
from tests.api.conftest import PASSWORD, World

calls: list[str] = []


@handler("test_ok")
def _ok(db: Session, ctx: JobContext) -> dict[str, Any]:
    ctx.progress(5, 10)
    calls.append("ok")
    return {"value": ctx.payload["value"]}


@handler("test_fail")
def _fail(db: Session, ctx: JobContext) -> dict[str, Any]:
    calls.append("fail")
    raise RuntimeError("secret internal detail")


def _job(world: World, job_id: uuid.UUID) -> dict[str, Any]:
    row = world.sql(
        "SELECT status, attempts, result, error, progress, total FROM rl.jobs WHERE id = :j",
        j=job_id,
    )[0]
    return dict(
        zip(("status", "attempts", "result", "error", "progress", "total"), row, strict=True)
    )


def test_job_runs_after_commit(owner_engine: object, world: World) -> None:
    t = world.tenant()
    calls.clear()
    with tenant_session(t) as db:
        job = enqueue(db, tenant_id=t, job_type="test_ok", payload={"value": 7})
        assert calls == []  # not before commit
    assert calls == ["ok"]
    state = _job(world, job.id)
    assert state["status"] == "succeeded" and state["result"] == {"value": 7}
    assert (state["progress"], state["total"]) == (5, 10)


def test_rolled_back_job_never_runs(owner_engine: object, world: World) -> None:
    t = world.tenant()
    calls.clear()
    with pytest.raises(ZeroDivisionError), tenant_session(t) as db:
        enqueue(db, tenant_id=t, job_type="test_ok", payload={"value": 1})
        _ = 1 / 0
    assert calls == []
    assert world.sql("SELECT count(*) FROM rl.jobs")[0][0] == 0


def test_failing_job_retries_then_dead_without_leaking_detail(
    owner_engine: object, world: World
) -> None:
    t = world.tenant()
    calls.clear()
    with tenant_session(t) as db:
        job = enqueue(db, tenant_id=t, job_type="test_fail", max_attempts=2)
    state = _job(world, job.id)
    assert state["status"] == "queued" and state["attempts"] == 1  # broker would retry with backoff
    jobs.run_job(job.id, t)  # final attempt: marked dead, not re-raised (no further retries)
    state = _job(world, job.id)
    assert state["status"] == "dead" and state["attempts"] == 2
    assert "secret" not in str(state["error"])


def test_unknown_job_type_rejected(owner_engine: object, world: World) -> None:
    t = world.tenant()
    with pytest.raises(KeyError), tenant_session(t) as db:
        enqueue(db, tenant_id=t, job_type="nope")


def test_stale_running_jobs_recovered(owner_engine: object, world: World) -> None:
    t = world.tenant()
    jid, dead = uuid.uuid7(), uuid.uuid7()
    old = datetime.now(UTC) - timedelta(hours=1)
    for job_id, attempts in ((jid, 1), (dead, 3)):
        world.sql(
            "INSERT INTO rl.jobs (id, tenant_id, type, status, progress, payload, attempts, max_attempts, cancel_requested, heartbeat_at, created_at) "
            "VALUES (:j, :t, 'test_ok', 'running', 0, '{\"value\": 3}', :a, 3, false, :h, now())",
            j=job_id,
            t=t,
            a=attempts,
            h=old,
        )
    calls.clear()
    assert recover_stale() == [jid]
    assert _job(world, jid)["status"] == "succeeded" and calls == ["ok"]
    assert _job(world, dead)["status"] == "dead"


def test_job_status_endpoint_and_cancel(app_client: TestClient, world: World) -> None:
    from tests.api.conftest import login

    t = world.tenant()
    m = world.member(t, "analyst")
    jid = uuid.uuid7()
    world.sql(
        "INSERT INTO rl.jobs (id, tenant_id, type, status, progress, payload, attempts, max_attempts, cancel_requested, created_by, created_at) "
        "VALUES (:j, :t, 'test_ok', 'queued', 0, '{}', 0, 3, false, :u, now())",
        j=jid,
        t=t,
        u=m.user_id,
    )
    login(app_client, m)
    assert app_client.get(f"/api/v1/jobs/{jid}").json()["status"] == "queued"
    assert app_client.post(f"/api/v1/jobs/{jid}/cancel").status_code == 200
    with tenant_session(t) as db:
        assert db.get(Job, jid).cancel_requested  # type: ignore[union-attr]
    jobs.run_job(jid, t)
    assert _job(world, jid)["status"] == "cancelled"


def test_platform_admin_bootstrap_forces_mfa(app_client: TestClient, world: World) -> None:
    from app.services.platform_admin import PlatformAdminError, create_platform_admin

    with pytest.raises(PlatformAdminError):
        create_platform_admin("ops@example.com", "Ops", "short")
    create_platform_admin("Ops@Example.com", "Ops", "operator passphrase 2026")
    create_platform_admin("ops@example.com", "Ops", "operator passphrase 2026")  # idempotent
    assert world.sql("SELECT count(*) FROM rl.platform_admins")[0][0] == 1
    r = app_client.post(
        "/api/v1/auth/login",
        json={"email": "ops@example.com", "password": "operator passphrase 2026"},
    )
    assert r.json()["state"] == "pending_enrollment" and r.json()["is_platform_admin"] is True
    events = world.sql("SELECT action FROM rl.audit_events WHERE chain_key = 'platform'")
    assert [e[0] for e in events] == ["platform_admin.created", "platform_admin.created"]


def test_cli_create_platform_admin(
    owner_engine: object,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import io

    from app.cli import main

    monkeypatch.setattr("sys.stdin", io.StringIO("operator passphrase 2027\n"))
    assert (
        main(
            [
                "create-platform-admin",
                "--email",
                "cli@example.com",
                "--name",
                "CLI",
                "--password-stdin",
            ]
        )
        == 0
    )
    assert "two-factor" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("weak\n"))
    assert (
        main(
            [
                "create-platform-admin",
                "--email",
                "cli2@example.com",
                "--name",
                "CLI",
                "--password-stdin",
            ]
        )
        == 2
    )


def test_scheduler_tick_enqueues_daily_once(owner_engine: object, world: World) -> None:
    from app.workers.scheduler import tick

    a, b = world.tenant("A"), world.tenant("B")
    world.member(a, "viewer")
    last: dict[str, str] = {}
    tick(datetime(2026, 11, 10, 4, 0, tzinfo=UTC), last)
    tick(datetime(2026, 11, 10, 5, 0, tzinfo=UTC), last)
    rows = world.sql(
        "SELECT tenant_id, status, result FROM rl.jobs WHERE type = 'verify_audit_chain'"
    )
    assert {r[0] for r in rows} == {a, b}
    assert all(r[1] == "succeeded" and r[2]["ok"] for r in rows)


def test_email_templates_have_both_parts_and_escape() -> None:
    e = render(
        "invite",
        "x@example.com",
        {
            "org_name": "<b>Acme</b>",
            "inviter": "Pat",
            "role": "Viewer",
            "url": "https://app/accept?token=abc",
            "ttl_days": 7,
        },
    )
    assert "&lt;b&gt;Acme&lt;/b&gt;" in e.html and "<b>Acme</b>" in e.text
    assert e.subject == "You're invited to <b>Acme</b> on RebateLedger"
    alert = render(
        "generic",
        "x@example.com",
        {
            "subject": "Tier close",
            "text": "Hi",
            "url": "",
            "link_label": "",
            "unsubscribe_url": "https://u",
        },
        transactional=False,
    )
    assert "unsubscribe" in alert.html and "Unsubscribe" in alert.text


def test_password_login_unknown_tenantless_user(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    """A user with no active organization gets the generic sign-in error."""
    world.user("lonely@example.com")
    r = app_client.post(
        "/api/v1/auth/login", json={"email": "lonely@example.com", "password": PASSWORD}
    )
    assert r.status_code == 401
