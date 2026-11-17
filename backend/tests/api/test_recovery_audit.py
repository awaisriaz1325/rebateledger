"""Look-back recovery audit (v1.2 Phase 20). Hand-worked values.

Fixture (tests.api.test_workflow.world_setup): ACME-1, 2% flat quarterly from 2025-01-01, 30-day
terms; Q1 purchases 100,000 → 2,000.00, Q2 50,000 → 1,000.00. A 1,500.00 credit for Q1.

Audit 2025-01-01 … 2025-06-30, as of today (well after both due dates):
- Q1 short-paid: 2,000.00 − 1,500.00 → shortfall 500.00
- Q2 missing:    1,000.00 − 0        → shortfall 1,000.00
- Identified total 1,500.00 (never called "recovered").
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.services.recovery_audit import gaps
from tests.api.conftest import login
from tests.api.test_exports import _download, _export
from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)

RANGE = {"period_from": "2025-01-01", "period_to": "2025-06-30"}


def test_gaps_are_the_uncovered_parts_of_the_range() -> None:
    d = date
    assert gaps([], d(2025, 1, 1), d(2025, 12, 31)) == [(d(2025, 1, 1), d(2025, 12, 31))]
    assert gaps([(d(2025, 3, 1), d(2025, 6, 30))], d(2025, 1, 1), d(2025, 12, 31)) == [
        (d(2025, 1, 1), d(2025, 2, 28)),
        (d(2025, 7, 1), d(2025, 12, 31)),
    ]
    # Overlapping and touching intervals leave no gap between them.
    assert (
        gaps(
            [
                (d(2024, 1, 1), d(2025, 3, 31)),
                (d(2025, 4, 1), d(2025, 9, 30)),
                (d(2025, 6, 1), d(2026, 1, 1)),
            ],
            d(2025, 1, 1),
            d(2025, 12, 31),
        )
        == []
    )


def _book(c: Any) -> None:
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)


def test_coverage_lists_gaps_and_late_history(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    r = c.get(
        "/api/v1/recovery-audit/coverage",
        params={"period_from": "2024-07-01", "period_to": "2025-06-30"},
    )
    assert r.status_code == 200, r.text
    [acme] = r.json()
    assert acme["name"] == "Acme" and acme["agreements"] == 1
    assert acme["gaps"] == [{"start": "2024-07-01", "end": "2024-12-31"}]
    assert acme["data_from"] == "2025-01-15" and acme["history_starts_late"] is True
    r = c.get(
        "/api/v1/recovery-audit/coverage",
        params={"period_from": "2022-01-01", "period_to": "2025-06-30"},
    )
    assert r.status_code == 422 and r.json()["code"] == "RANGE_TOO_LONG"


def test_audit_lists_shortfalls_with_hand_worked_total(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    _book(c)
    r = c.get("/api/v1/recovery-audit", params=RANGE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_shortfall"] == "1500.00"
    assert body["note"].startswith("Identified, not recovered")
    got = [(x["period_start"], x["status"], x["shortfall"], x["age"]) for x in body["rows"]]
    assert got == [
        ("2025-01-01", "SHORT_PAID", "500.00", "over 1 year"),
        ("2025-04-01", "MISSING", "1000.00", "over 1 year"),
    ]
    assert all(x["deadline"] == "" and x["claim"] == "" for x in body["rows"])


def test_claim_deadline_flags_but_never_drops(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, _sid, aid = world_setup
    _book(c)
    # Deadline that Q2 (ended 2025-06-30) still meets but Q1 (ended 2025-03-31) does not.
    days = (datetime.now(UTC).date() - date(2025, 6, 30)).days + 1  # +1: a day of tz slack
    a = c.get(f"/api/v1/agreements/{aid}")
    r = c.patch(
        f"/api/v1/agreements/{aid}",
        json={"claim_deadline_days": days},
        headers={"If-Match": a.headers["ETag"]},
    )
    assert r.status_code == 200 and r.json()["claim_deadline_days"] == days
    rows = c.get("/api/v1/recovery-audit", params=RANGE).json()["rows"]
    assert [x["deadline"] for x in rows] == ["May be time-barred: check the contract", ""]
    assert c.get("/api/v1/recovery-audit", params=RANGE).json()["total_shortfall"] == "1500.00"
    a = c.get(f"/api/v1/agreements/{aid}")
    r = c.patch(
        f"/api/v1/agreements/{aid}",
        json={"claim_deadline_days": None},
        headers={"If-Match": a.headers["ETag"]},
    )
    assert r.json()["claim_deadline_days"] is None
    a = c.get(f"/api/v1/agreements/{aid}")
    r = c.patch(
        f"/api/v1/agreements/{aid}",
        json={"claim_deadline_days": 0},
        headers={"If-Match": a.headers["ETag"]},
    )
    assert r.status_code == 422


def test_bulk_claims_one_per_supplier_then_marked(world_setup: Any) -> None:  # noqa: F811
    c, w, t, *_ = world_setup
    _book(c)
    rows = c.get("/api/v1/recovery-audit", params=RANGE).json()["rows"]
    ids = [x["result_id"] for x in rows]
    key = str(uuid.uuid4())
    r = c.post(
        "/api/v1/recovery-audit/claims", json={"result_ids": ids}, headers={"Idempotency-Key": key}
    )
    assert r.status_code == 201, r.text
    [claim_id] = r.json()["claim_ids"]
    claim = c.get(f"/api/v1/claims/{claim_id}").json()
    assert Decimal(claim["identified_amount"]) == Decimal("1500.00")
    again = c.post(
        "/api/v1/recovery-audit/claims", json={"result_ids": ids}, headers={"Idempotency-Key": key}
    )
    assert again.json() == r.json()  # replay, no second claim
    marked = c.get("/api/v1/recovery-audit", params=RANGE).json()["rows"]
    assert {x["claim"] for x in marked} == {f"CL-{claim['number']:04d}"}
    r = c.post("/api/v1/recovery-audit/claims", json={"result_ids": ids})
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_CLAIMED"
    login(c, w.member(t, "viewer"))
    assert c.post("/api/v1/recovery-audit/claims", json={"result_ids": ids}).status_code == 403


def test_audit_report_exports_and_needs_a_range(world_setup: Any) -> None:  # noqa: F811
    c, *_ = world_setup
    _book(c)
    pdf = _download(c, _export(c, "recovery_audit", "pdf", **RANGE))
    assert pdf.startswith(b"%PDF")
    csv_bytes = _download(c, _export(c, "recovery_audit", "csv", **RANGE))
    text = csv_bytes.decode("utf-8-sig")
    assert "Identified shortfall" in text.splitlines()[0]
    r = c.get("/api/v1/reports/preview", params={"report": "recovery_audit"})
    assert r.status_code == 422 and r.json()["code"] == "PERIOD_REQUIRED"
