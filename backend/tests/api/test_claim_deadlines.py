"""Claim-deadline alerts (v1.3 Phase 25). Hand-worked dates.

Fixture (tests.api.test_workflow.world_setup): ACME-1, quarterly, 30-day payment terms. Q1 2025
earned 2,000.00 with 1,500.00 received (short-paid); Q2 earned 1,000.00, nothing received
(missing once due 2025-07-30). Claim deadline: 107 days after the period ends.

- Q2 ends 2025-06-30 → deadline 2025-10-15. Q1 ends 2025-03-31 → deadline 2025-07-16 (passed).
- On 2025-09-15 Q2 is 30 days from its deadline → one alert; Q1 is already time-barred → none.
- On 2025-09-14 (31 days) → no alert. On 2025-10-15 (0 days) → alert.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.services import notifications
from tests.api.conftest import login
from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)


def _run_job(t: Any, job_type: str = "claim_deadlines") -> None:
    from app.db.session import tenant_session
    from app.workers.jobs import enqueue

    with tenant_session(t) as db:
        enqueue(db, tenant_id=t, job_type=job_type)


def _alerts(c: Any, type_: str = "claim_deadline") -> list[dict[str, Any]]:
    return [n for n in c.get("/api/v1/notifications").json()["items"] if n["type"] == type_]


@pytest.fixture
def booked(world_setup: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    c, w, t, _sid, aid = world_setup
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    head = c.get(f"/api/v1/agreements/{aid}")
    r = c.patch(
        f"/api/v1/agreements/{aid}",
        json={"claim_deadline_days": 107},
        headers={"If-Match": head.headers["ETag"]},
    )
    assert r.status_code == 200, r.text

    def at(day: date) -> None:
        monkeypatch.setattr(notifications, "today_in", lambda tz: day)

    return c, w, t, aid, at


def test_alert_once_for_the_period_whose_deadline_is_30_days_away(booked: Any) -> None:
    c, _w, t, _aid, at = booked
    at(date(2025, 9, 15))
    for _ in range(2):  # a second run the same day, or the next day, never repeats it
        _run_job(t)
    got = _alerts(c)
    assert len(got) == 1, got
    a = got[0]
    assert a["title"] == "Claim deadline in 30 days: Acme base, 2025-Q2"
    assert "Oct 15, 2025" in a["body"] and "1,000.00" in a["body"]
    assert a["link"].startswith("/app/discrepancies")


def test_no_alert_at_31_days_and_alert_on_the_last_day(booked: Any) -> None:
    c, _w, t, _aid, at = booked
    at(date(2025, 9, 14))
    _run_job(t)
    assert _alerts(c) == []
    at(date(2025, 10, 15))
    _run_job(t)
    assert [a["title"] for a in _alerts(c)] == ["Claim deadline today: Acme base, 2025-Q2"]


def test_no_alert_once_the_period_is_paid(booked: Any) -> None:
    c, _w, t, _aid, at = booked
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-2,08/20/2025,1000.00,ACME-1,Q2 2025\n",
        CREDIT_COLS,
    )
    run(c)
    at(date(2025, 9, 15))
    _run_job(t)
    assert _alerts(c) == []


def test_weekly_digest_lists_deadlines_even_without_tier_opportunities(booked: Any) -> None:
    c, w, t, _aid, at = booked
    at(date(2025, 9, 15))  # a Monday
    _run_job(t, "weekly_digest")
    digests = _alerts(c, "weekly_digest")
    assert len(digests) == 1
    assert "Claim deadlines in the next 30 days:" in digests[0]["body"]
    assert "Acme base, 2025-Q2: 1,000.00 by Oct 15, 2025 (30 days)" in digests[0]["body"]
    login(c, w.member(t, "viewer"))
    assert _alerts(c, "weekly_digest") == []
