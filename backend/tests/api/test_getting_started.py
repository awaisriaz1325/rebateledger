"""Getting-started checklist on the dashboard (v1.3 Phase 24): driven by real data, never ticked."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.conftest import World, login
from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)

KEYS = ["suppliers", "purchases", "agreements", "activate", "run", "credits", "review"]


def _steps(c: Any) -> dict[str, dict[str, Any]]:
    r = c.get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    steps = r.json()["getting_started"]
    assert [s["key"] for s in steps] == KEYS
    return {s["key"]: s for s in steps}


def test_empty_organization_has_every_step_open(app_client: TestClient, world: World) -> None:
    login(app_client, world.member(world.tenant(), "analyst"))
    steps = _steps(app_client)
    assert not any(s["done"] for s in steps.values())
    assert steps["suppliers"]["count"] == 0 and steps["suppliers"]["link"] == "/app/suppliers/new"


def test_steps_follow_the_data(world_setup: Any) -> None:  # noqa: F811
    # Fixture: one supplier, one active agreement, purchases imported; no run, no credits yet.
    c, *_ = world_setup
    steps = _steps(c)
    done = {k for k, s in steps.items() if s["done"]}
    assert done == {"suppliers", "purchases", "agreements", "activate"}
    assert (
        steps["suppliers"]["count"],
        steps["agreements"]["count"],
        steps["activate"]["count"],
    ) == (
        1,
        1,
        1,
    )

    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    steps = _steps(c)
    # Q1 is short-paid and Q2 missing: discrepancies exist and none is claimed yet.
    assert steps["run"]["done"] and steps["credits"]["done"] and not steps["review"]["done"]

    q1 = next(
        r for r in c.get("/api/v1/reconciliation").json() if r["period_start"] == "2025-01-01"
    )
    assert c.post("/api/v1/claims", json={"result_ids": [q1["result_id"]]}).status_code == 201
    assert all(s["done"] for s in _steps(c).values())
