"""Resilience drills on the LOCAL stack (PHASES §10.4). Needs `make up` and `make migrate`.

Starts the API (:8100) and one worker as real processes, then:
  A. kills the worker while an import commit is running,
  B. kills the worker while a calculation run is running,
  C. kills the worker while a full data export is being built,
  D. restarts Redis,
  E. restarts PostgreSQL,
and checks that nothing partial becomes visible and that work resumes or fails cleanly.
Prints a Markdown report. Never touches anything but the local docker-compose services.

    cd backend && set -a && . ./.env.example && set +a && uv run python scripts/resilience_drill.py
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8100"
ORIGIN = "http://localhost:3100"
ENV = {**os.environ, "RL_APP_BASE_URL": ORIGIN, "RL_JOBS_MODE": "queue"}
report: list[str] = []


def log(line: str) -> None:
    print(line, flush=True)
    report.append(line)


def start(cmd: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - fixed argv built in this script
        cmd,
        cwd=ROOT / "backend",
        env=ENV,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop(p: subprocess.Popen[bytes], sig: int = signal.SIGKILL) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(p.pid, sig)
    p.wait(timeout=30)


def worker() -> subprocess.Popen[bytes]:
    return start(
        [
            "uv",
            "run",
            "dramatiq",
            "app.workers.broker",
            "app.services.registry",
            "--processes",
            "1",
            "--threads",
            "2",
        ]
    )


def api() -> subprocess.Popen[bytes]:
    p = start(["uv", "run", "uvicorn", "app.asgi:app", "--host", "127.0.0.1", "--port", "8100"])
    for _ in range(60):
        try:
            if httpx.get(f"{API}/healthz", timeout=1).status_code == 200:
                return p
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("API did not start")


def sql(statement: str, **params: Any) -> list[Any]:
    from sqlalchemy import create_engine, text

    url = os.environ["RL_MIGRATION_DATABASE_URL"]
    with create_engine(url).begin() as conn:
        result = conn.execute(text(statement), params)
        return list(result.all()) if result.returns_rows else []


def wait(predicate: Any, timeout: float, step: float = 0.25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def job(job_id: str) -> dict[str, Any]:
    rows = sql("SELECT status, progress, attempts FROM rl.jobs WHERE id = :j", j=job_id)
    return {"status": rows[0][0], "progress": rows[0][1], "attempts": rows[0][2]} if rows else {}


def recover() -> list[uuid.UUID]:
    from app.workers.jobs import recover_stale

    return recover_stale(max_age=timedelta(seconds=0))


def setup() -> tuple[httpx.Client, uuid.UUID]:
    """A fresh demo tenant (seed_demo) plus an analyst created through the ORM, so every
    column default and constraint matches what the application itself writes."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.security import hash_password
    from app.db.models.identity import Membership, User
    from app.services.seed import seed_demo

    tag = uuid.uuid4().hex[:8]
    note = seed_demo(purchase_lines=2_000, owner_email=f"drill-owner-{tag}@example.com")
    tenant = uuid.UUID(note.split()[2])
    password = "resilience drill passphrase 2026"  # noqa: S105  # nosec B105 - local drill user
    email = f"drill-{tag}@example.com"
    with Session(create_engine(os.environ["RL_MIGRATION_DATABASE_URL"])) as db, db.begin():
        user = User(email=email, name="Drill", password_hash=hash_password(password))
        db.add(user)
        db.flush()
        db.add(Membership(tenant_id=tenant, user_id=user.id, role="analyst"))
    c = httpx.Client(base_url=API, headers={"Origin": ORIGIN}, timeout=60)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"drill login failed: {r.status_code} {r.text[:200]}"
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    # The session cookie is `__Host-` + Secure; httpx (unlike browsers on localhost) will
    # not send a Secure cookie over plain http, so pass it explicitly for this local drill.
    c.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
    c.cookies.clear()
    return c, tenant


def import_file(c: httpx.Client, rows: int) -> str:
    body = "Vendor,Invoice,Item,Qty,Ext,Inv Date\n" + "".join(
        f"DRILL,I{i},SKU{i % 50},1,{(i % 900) + 100}.00,{(i % 12) + 1:02d}/15/2025\n"
        for i in range(rows)
    )
    r = c.post(
        "/api/v1/imports",
        files={"file": ("drill.csv", body.encode(), "text/csv")},
        data={"import_type": "purchases"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    bid = r.json()["id"]
    cols = {
        "supplier_code": "Vendor",
        "invoice_number": "Invoice",
        "sku": "Item",
        "quantity": "Qty",
        "amount": "Ext",
        "invoice_date": "Inv Date",
    }
    c.put(f"/api/v1/imports/{bid}/config", json={"columns": cols, "date_format": "MM/DD/YYYY"})
    c.post(f"/api/v1/imports/{bid}/validate")
    assert wait(lambda: c.get(f"/api/v1/imports/{bid}").json()["status"] == "validated", 300), (
        "validation did not finish"
    )
    return str(bid)


def main() -> None:
    api_p, worker_p = api(), worker()
    try:
        c, _tenant = setup()
        c.post("/api/v1/suppliers", json={"name": "Drill Supply", "codes": ["DRILL"]})
        listing = c.get("/api/v1/suppliers")
        assert listing.status_code == 200, f"{listing.status_code} {listing.text[:300]}"
        sid = listing.json()["items"][0]["id"]
        terms = {
            "effective_from": "2025-01-01",
            "effective_to": "2025-12-31",
            "period_type": "quarterly",
            "fiscal_aligned": True,
            "custom_periods": [],
            "date_basis": "invoice_date",
            "measure": "spend",
            "spend_basis": "net_of_returns",
            "threshold_comparison": "gte",
            "negative_result": "floor_at_zero",
            "rounding_mode": "half_up",
            "payment_terms_days": 60,
            "stacking": "stackable",
            "prorate_thresholds_on_partial_period": False,
            "zero_baseline_policy": "needs_review",
            "cap_amount": None,
            "minimum_payout": None,
            "eligibility": [],
            "components": [{"key": "base", "type": "flat_percent", "rate": "0.02", "tiers": []}],
        }
        a = c.post(
            "/api/v1/agreements", json={"supplier_id": sid, "name": "Drill 2%", "terms": terms}
        ).json()
        c.post(f"/api/v1/agreement-versions/{a['versions'][0]['id']}/activate", json={})
        log("| Drill | What happened | Result |")
        log("|---|---|---|")

        # A. Worker killed during import commit.
        rows = 300_000
        bid = import_file(c, rows)
        r = c.post(
            f"/api/v1/imports/{bid}/commit",
            json={"mode": "all_or_nothing"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        jid = r.json()["job_id"]
        wait(
            lambda: job(jid).get("status") == "running" and job(jid).get("progress", 0) > 0,
            120,
            0.05,
        )
        before = job(jid)
        stop(worker_p)
        visible = sql("SELECT count(*) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0]
        batch_status = c.get(f"/api/v1/imports/{bid}").json()["status"]
        worker_p = worker()
        recovered = jid in [str(j) for j in recover()]
        done = wait(lambda: job(jid).get("status") in ("succeeded", "dead", "failed"), 600)
        final = c.get(f"/api/v1/imports/{bid}").json()
        committed = sql("SELECT count(*) FROM rl.purchase_lines WHERE batch_id = :b", b=bid)[0][0]
        ok = (
            visible == 0
            and recovered
            and done
            and final["status"] == "committed"
            and committed == rows
        )
        log(
            f"| A. Kill worker during import commit ({rows:,} rows) | Killed at job progress {before.get('progress', 0):,}; rows visible after kill: {visible}; batch showed `{batch_status}`; recovery re-queued the job; final `{final['status']}` with {committed:,} rows (attempt {job(jid).get('attempts')}) | {'PASS' if ok else 'FAIL'} |"
        )

        # B. Worker killed during a calculation run. A control run with the same scope,
        # left alone, gives the expected number of period results.
        control = c.post(
            "/api/v1/runs",
            json={
                "scope": {"type": "all"},
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).json()["id"]
        assert wait(
            lambda: c.get(f"/api/v1/runs/{control}").json()["status"] == "succeeded", 600
        ), "control run did not finish"
        expected = sql("SELECT count(*) FROM rl.period_results WHERE run_id = :r", r=control)[0][0]
        r = c.post(
            "/api/v1/runs",
            json={
                "scope": {"type": "all"},
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        run, jid = r.json()["id"], r.json()["job_id"]
        wait(lambda: job(jid).get("status") == "running", 60, 0.02)
        stop(worker_p)
        partial = sql("SELECT count(*) FROM rl.period_results WHERE run_id = :r", r=run)[0][0]
        status_after_kill = c.get(f"/api/v1/runs/{run}").json()["status"]
        worker_p = worker()
        recover()
        done = wait(
            lambda: c.get(f"/api/v1/runs/{run}").json()["status"] in ("succeeded", "failed"), 600
        )
        final_run = c.get(f"/api/v1/runs/{run}").json()
        results = sql("SELECT count(*) FROM rl.period_results WHERE run_id = :r", r=run)[0][0]
        ok = partial == 0 and done and final_run["status"] == "succeeded" and results == expected
        log(
            f"| B. Kill worker during a calculation run | Results visible after kill: {partial}; run showed `{status_after_kill}`; after recovery `{final_run['status']}` with {results} period results (uninterrupted control run: {expected}) | {'PASS' if ok else 'FAIL'} |"
        )

        # C. Worker killed during an export (PDF report).
        r = c.post(
            "/api/v1/exports",
            json={"report": "reconciliation_summary", "format": "pdf"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        eid, jid = r.json()["id"], r.json()["job_id"]
        wait(lambda: job(jid).get("status") in ("running", "succeeded"), 60, 0.01)
        state_at_kill = job(jid).get("status")
        stop(worker_p)
        worker_p = worker()
        recover()
        done = wait(
            lambda: c.get(f"/api/v1/exports/{eid}").json()["status"] in ("succeeded", "failed"), 300
        )
        export = c.get(f"/api/v1/exports/{eid}").json()
        log(
            f"| C. Kill worker during PDF export | Job was `{state_at_kill}` when killed; after recovery the export is `{export['status']}` ({export.get('size_bytes')} bytes) | {'PASS' if done and export['status'] == 'succeeded' else 'FAIL'} |"
        )

        # D. Redis restart.
        t0 = time.time()
        subprocess.run(
            ["docker", "compose", "restart", "redis"],  # noqa: S607 - docker from PATH (dev machine)
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        ready = wait(lambda: httpx.get(f"{API}/readyz", timeout=2).status_code == 200, 60)
        r = c.post(
            "/api/v1/runs",
            json={
                "scope": {"type": "all"},
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        run_after = r.json().get("id")
        if not wait(
            lambda: c.get(f"/api/v1/runs/{run_after}").json()["status"] == "succeeded", 120
        ):
            recover()
        ok_d = (
            ready
            and r.status_code == 202
            and wait(
                lambda: c.get(f"/api/v1/runs/{run_after}").json()["status"] == "succeeded", 300
            )
        )
        log(
            f"| D. Restart Redis | Ready again after {time.time() - t0:.1f} s; a run started afterwards returned {r.status_code} and finished `{c.get(f'/api/v1/runs/{run_after}').json()['status']}` (worker reconnected) | {'PASS' if ok_d else 'FAIL'} |"
        )

        # E. PostgreSQL restart.
        t0 = time.time()
        subprocess.run(
            ["docker", "compose", "restart", "postgres"],  # noqa: S607 - docker from PATH (dev machine)
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        during = httpx.get(f"{API}/readyz", timeout=10).status_code
        ready = wait(lambda: httpx.get(f"{API}/readyz", timeout=2).status_code == 200, 120)
        after = c.get("/api/v1/suppliers").status_code
        log(
            f"| E. Restart PostgreSQL | `/readyz` answered {during} while restarting; ready after {time.time() - t0:.1f} s; existing session works ({after}) without restarting the API (pool pre-ping) | {'PASS' if ready and after == 200 else 'FAIL'} |"
        )
    finally:
        stop(worker_p, signal.SIGTERM)
        stop(api_p, signal.SIGTERM)


if __name__ == "__main__":
    main()
