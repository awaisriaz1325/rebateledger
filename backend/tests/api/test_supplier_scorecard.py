"""Supplier scorecard (v1.3 Phase 26). Hand-worked values.

ACME-1: 2% flat quarterly, 30-day payment terms (fixture world_setup) plus extra purchases:
| Period  | Purchases | Earned   | Credit (date)          | Due        | Result                 |
|---------|-----------|----------|------------------------|------------|------------------------|
| 2025-Q1 | 100,000   | 2,000.00 | 2,000.00 (2025-04-20)  | 2025-04-30 | paid in full, on time  |
| 2025-Q2 |  50,000   | 1,000.00 | 1,000.00 (2025-08-09)  | 2025-07-30 | paid in full, 10 d late|
| 2025-Q3 |  25,000   |   500.00 |   300.00 (2025-10-05)  | 2025-10-30 | short-paid             |
| 2025-Q4 |  10,000   |   200.00 | none                   | 2026-01-30 | missing                |

Scorecard for 2025: 4 periods owed; earned 3,700.00; received 3,300.00 → 89.2% received;
on time 1 of 4 → 25.0%; average days late (paid periods) 10; short-paid 1; missing 1.
A claim of 200.00 for Q4 → open claims 1 (200.00); recovered 0.00 of 200.00 claimed → 0.0%.
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

YEAR = {"period_from": "2025-01-01", "period_to": "2025-12-31"}


def _book(c: Any) -> None:
    imp(
        c,
        "purchases",
        "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\n"
        "ACME,I4,1,A,1,25000.00,07/15/2025\nACME,I5,1,A,1,10000.00,10/10/2025\n",
        PURCHASE_COLS,
    )
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\n"
        "ACME,CM-1,04/20/2025,2000.00,ACME-1,Q1 2025\n"
        "ACME,CM-2,08/09/2025,1000.00,ACME-1,Q2 2025\n"
        "ACME,CM-3,10/05/2025,300.00,ACME-1,Q3 2025\n",
        CREDIT_COLS,
    )
    run(c, "2025-01-01", "2025-12-31")


def _preview(c: Any, **params: str) -> dict[str, Any]:
    r = c.get("/api/v1/reports/preview", params={"report": "supplier_scorecard", **YEAR, **params})
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_scorecard_hand_worked(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, _aid = world_setup
    _book(c)
    q4 = next(
        r for r in c.get("/api/v1/reconciliation").json() if r["period_start"] == "2025-10-01"
    )
    assert q4["status"] == "MISSING"
    assert c.post("/api/v1/claims", json={"result_ids": [q4["result_id"]]}).status_code == 201

    body = _preview(c)
    [row] = body["rows"]
    assert row == {
        "supplier": "Acme",
        "periods": "4",
        "earned": "3700.00",
        "received": "3300.00",
        "received_pct": "89.2",
        "on_time_pct": "25.0",
        "avg_days_late": "10",
        "short_paid": "1",
        "missing": "1",
        "open_claims": "1",
        "open_claim_amount": "200.00",
        "recovery_pct": "0.0",
    }, row
    assert _preview(c, supplier_id=sid)["rows"][0]["supplier"] == "Acme"


def test_no_owed_periods_shows_dashes_not_errors(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    body = _preview(c, period_from="2030-01-01", period_to="2030-12-31")
    assert body["rows"] == []
