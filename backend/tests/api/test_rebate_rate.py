"""Effective rebate rate (v1.3 Phase 28). Hand-worked values.

Fixture (world_setup): ACME-1, 2% flat quarterly from 2025-01-01. Purchases 2025: 60,000 (Jan 15),
40,000 (Mar 20), 50,000 (Apr 10) = 150,000. A 1,500.00 credit for Q1. Run Q1–Q2 2025.

Range 2025-01-01 … 2025-06-30:
- spend 150,000.00; earned 2,000.00 + 1,000.00 = 3,000.00; received 1,500.00
- earned rate 3,000 / 150,000 = 2.00%; received rate 1,500 / 150,000 = 1.00%
- same range a year earlier: no purchases → no rate ("—"), no change
With 20,000.00 bought on 2024-02-01 (before the agreement started, so nothing earned):
- prior earned rate 0 / 20,000 = 0.00%; change +2.00 percentage points
"""

from __future__ import annotations

from typing import Any

from tests.api.test_workflow import (
    CREDIT_COLS,
    PURCHASE_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)

H1 = {"period_from": "2025-01-01", "period_to": "2025-06-30"}


def _book(c: Any) -> None:
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)


def _rows(c: Any) -> list[dict[str, str]]:
    r = c.get("/api/v1/reports/preview", params={"report": "rebate_rate", **H1})
    assert r.status_code == 200, r.text
    return list(r.json()["rows"])


def test_rates_for_the_range(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    _book(c)
    assert _rows(c) == [
        {
            "supplier": "Acme",
            "spend": "150000.00",
            "earned": "3000.00",
            "received": "1500.00",
            "earned_pct": "2.00",
            "received_pct": "1.00",
            "prior_earned_pct": "",
            "change_pts": "",
            "needs_review": "0",
        }
    ]


def test_change_against_the_same_range_last_year(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    imp(
        c,
        "purchases",
        "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\nACME,I0,1,A,1,20000.00,02/01/2024\n",
        PURCHASE_COLS,
    )
    _book(c)
    [row] = _rows(c)
    assert (row["prior_earned_pct"], row["change_pts"]) == ("0.00", "2.00")


def test_dashboard_tile_is_present_and_empty_without_recent_data(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    tile = c.get("/api/v1/dashboard").json()["rebate_rate"]
    assert tile["link"].startswith("/app/reports")
    assert (
        tile["earned_pct"] is None
    )  # fixture data is from 2025; the tile shows the last 12 months
