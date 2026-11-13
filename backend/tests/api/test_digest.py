"""Tier opportunities and the weekly buyer digest (v1.1 Phase 14). Hand-worked values.

"Today" is Monday 2025-05-19 (Q2 2025: 1 Apr – 30 Jun; 42 days remaining, 49 elapsed).
- Big deal (supplier BIG): all-units tiers 100,000 @ 2% / 200,000 @ 3%; Q2 spend 150,000.
  Gap 50,000. Potential (3% − 2%) × 200,000 = 2,000.00. Return per extra $ = 0.0400.
- Quick win (supplier QW): all-units tiers 50,000 @ 1% / 60,000 @ 5%; Q2 spend 55,000.
  Gap 5,000. Potential (5% − 1%) × 60,000 = 2,400.00. Return per extra $ = 0.4800.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import notifications, tiers
from tests.api.conftest import World, login
from tests.api.factories import TERMS
from tests.api.test_workflow import PURCHASE_COLS, imp

MONDAY = date(2025, 5, 19)


def _deal(c: TestClient, code: str, name: str, tiers_: list[dict[str, str]], spend: str) -> None:
    sid = c.post("/api/v1/suppliers", json={"name": f"Supplier {code}", "codes": [code]}).json()[
        "id"
    ]
    terms = {
        **TERMS,
        "effective_from": "2025-01-01",
        "components": [{"key": "t", "type": "tiered_all_units", "tiers": tiers_}],
    }
    a = c.post("/api/v1/agreements", json={"supplier_id": sid, "name": name, "terms": terms}).json()
    c.post(f"/api/v1/agreement-versions/{a['versions'][0]['id']}/activate", json={})
    imp(
        c,
        "purchases",
        f"Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\n{code},I-{code},1,A,1,{spend},04/05/2025\n",
        PURCHASE_COLS,
    )


@pytest.fixture
def deals(app_client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch) -> Any:
    t = world.tenant()
    analyst = world.member(t, "analyst")
    login(app_client, analyst)
    c = app_client
    _deal(
        c,
        "BIG",
        "Big deal",
        [{"threshold": "100000", "rate": "0.02"}, {"threshold": "200000", "rate": "0.03"}],
        "150000.00",
    )
    _deal(
        c,
        "QW",
        "Quick win",
        [{"threshold": "50000", "rate": "0.01"}, {"threshold": "60000", "rate": "0.05"}],
        "55000.00",
    )
    monkeypatch.setattr(tiers, "today_in", lambda tz: MONDAY)
    monkeypatch.setattr(notifications, "today_in", lambda tz: MONDAY)
    return c, world, t, analyst


def test_opportunities_rank_by_return_per_extra_dollar(deals: Any) -> None:
    c, *_ = deals
    rows = c.get("/api/v1/tiers/opportunities").json()
    assert [r["agreement_name"] for r in rows] == ["Quick win", "Big deal"]
    qw, big = rows
    assert (qw["gap"], qw["potential_additional"], qw["return_per_unit"]) == (
        "5000.0000",
        "2400.00",
        "0.4800",
    )
    assert (big["gap"], big["potential_additional"], big["return_per_unit"]) == (
        "50000.0000",
        "2000.00",
        "0.0400",
    )
    assert big["days_remaining"] == 42
    assert big["required_daily"] == "1190.48"  # 50,000 / 42
    assert big["current_daily"] == "3061.22"  # 150,000 / 49
    assert big["projected_reaches_next"] is True
    assert c.get("/api/v1/tiers/opportunities", params={"limit": 1}).json()[0][
        "agreement_name"
    ] == ("Quick win")


def _digests(c: TestClient) -> list[dict[str, Any]]:
    items = c.get("/api/v1/notifications").json()["items"]
    return [n for n in items if n["type"] == "weekly_digest"]


def _run_digest(t: Any) -> None:
    from app.db.session import tenant_session
    from app.workers.jobs import enqueue

    with tenant_session(t) as db:
        enqueue(db, tenant_id=t, job_type="weekly_digest")


def test_monday_digest_once_per_user_and_never_to_viewers(deals: Any) -> None:
    c, world, t, analyst = deals
    viewer = world.member(t, "viewer")
    for _ in range(2):  # a retry or second run in the same week sends nothing new
        _run_digest(t)
    login(c, analyst)
    got = _digests(c)
    assert len(got) == 1
    d = got[0]
    assert d["title"] == "2 tier opportunities this week"
    assert d["link"] == "/app/tiers"
    lines = d["body"].splitlines()
    assert lines[2] == (
        "1. Supplier QW — Quick win: $5,000.00 more by Jun 30, 2025 (42 days) reaches tier 2 "
        "for about $2,400.00 more rebate."
    )
    assert "Estimates use the purchases imported so far" in d["body"]
    login(c, viewer)
    assert _digests(c) == []
    count = world.sql("SELECT count(*) FROM rl.digest_sends WHERE tenant_id = :t", t=str(t))
    assert count[0][0] == 1  # only the analyst is a member with a digest role here


def test_no_digest_on_other_days(deals: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _world, t, analyst = deals
    monkeypatch.setattr(notifications, "today_in", lambda tz: date(2025, 5, 20))
    _run_digest(t)
    login(c, analyst)
    assert _digests(c) == []


def test_opted_out_user_gets_nothing_but_is_not_retried(deals: Any) -> None:
    c, world, t, _analyst = deals
    r = c.put(
        "/api/v1/notification-preferences",
        json={"type": "weekly_digest", "in_app": False, "email": False},
    )
    assert r.status_code in (200, 204), r.text
    _run_digest(t)
    assert _digests(c) == []
    count = world.sql("SELECT count(*) FROM rl.digest_sends WHERE tenant_id = :t", t=str(t))
    assert count[0][0] == 1


def test_digest_text_uses_units_for_quantity_agreements() -> None:
    o = tiers.Opportunity(
        agreement_id=uuid.uuid4(),
        agreement_name="Units deal",
        supplier_name="Supplier U",
        period_end=date(2025, 6, 30),
        days_remaining=10,
        measure_kind="quantity",
        next_tier=3,
        gap=Decimal("12.5"),
        potential_additional=None,
        return_per_unit=None,
        required_daily=Decimal("1.25"),
        current_daily=Decimal("2"),
        projected_reaches_next=True,
        data_as_of=None,
    )
    text = notifications.digest_text([o])
    assert "12.50 units more by Jun 30, 2025 (10 days) reaches tier 3." in text
    assert "$" not in text.splitlines()[2]


def test_dashboard_shows_the_top_three_opportunities(deals: Any) -> None:
    from app.services import dashboard

    c, *_ = deals
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dashboard, "today_in", lambda tz: MONDAY)
        d = c.get("/api/v1/dashboard").json()
    assert [o["agreement_name"] for o in d["top_opportunities"]] == ["Quick win", "Big deal"]
    assert d["top_opportunities"][0]["potential_additional"] == "2400.00"
