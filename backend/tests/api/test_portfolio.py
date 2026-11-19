"""Advisor portfolio view (v1.3 Phase 29): one page across a user's organizations.

Each organization is read in its own tenant context (RLS), never through the current one. Only
active memberships are listed. An organization that requires two-factor sign-in is shown locked,
without numbers, to a user who has not set it up (the same rule as switching to it).
"""

from __future__ import annotations

from typing import Any

from tests.api.conftest import login
from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)


def _portfolio(c: Any) -> dict[str, dict[str, Any]]:
    r = c.get("/api/v1/me/portfolio")
    assert r.status_code == 200, r.text
    return {o["name"]: o for o in r.json()}


def test_each_organization_with_its_own_numbers(world_setup: Any) -> None:  # noqa: F811
    c, w, t, *_ = world_setup
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    analyst = w.member(t, "analyst")
    second = w.tenant(name="Second Client")
    w.add_membership(second, analyst.user_id, "viewer")
    stranger = w.tenant(name="Not Yours")
    w.member(stranger, "analyst")
    left = w.tenant(name="Former Client")
    mid = w.add_membership(left, analyst.user_id, "viewer")
    w.sql("UPDATE rl.memberships SET status = 'deactivated' WHERE id = :m", m=mid)

    login(c, analyst)
    orgs = _portfolio(c)
    assert set(orgs) == {"Acme Supply", "Second Client"}
    a = orgs["Acme Supply"]
    # Q1 short by 500.00 and Q2 missing 1,000.00 (fixture), nothing claimed yet.
    assert (a["identified_open_variance"], a["missing"], a["short_paid"], a["open_claims"]) == (
        "1500.00",
        1,
        1,
        0,
    )
    assert a["last_run_at"] is not None and a["locked"] is False and a["role"] == "analyst"
    b = orgs["Second Client"]
    assert (b["identified_open_variance"], b["missing"], b["open_claims"], b["last_run_at"]) == (
        "0.00",
        0,
        0,
        None,
    )
    assert a["current"] is True and b["current"] is False


def test_mfa_required_organization_is_locked_without_numbers(world_setup: Any) -> None:  # noqa: F811
    c, w, t, *_ = world_setup
    analyst = w.member(t, "analyst")  # no two-factor
    strict = w.tenant(name="Strict Co", require_mfa_all=True)
    w.add_membership(strict, analyst.user_id, "analyst")
    login(c, analyst)
    s = _portfolio(c)["Strict Co"]
    assert s["locked"] is True
    assert s["identified_open_variance"] is None and s["missing"] is None


def test_requires_sign_in(app_client: Any) -> None:
    assert app_client.get("/api/v1/me/portfolio").status_code == 401
