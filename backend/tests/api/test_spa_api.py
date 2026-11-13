"""Ship-and-debit / SPA claims through the API (v1.1 Phase 17). Hand-worked values.

SPA-100 (ACME, customer "Hospital Build", 2025, 60-day claim deadline):
  WIRE book 10.00 / SPA 7.50 → 2.50 per unit ; BOX book 40.00 / SPA 31.25 → 8.75, cap 100.
Sales:
  I1 WIRE 10  → 25.00 OK
  I2 BOX  60  → 525.00 OK
  I3 BOX  60  → only 40 fit the cap → 350.00 OK (CAP_PARTIAL)
  I4 WIRE 5, no customer → NEEDS_REVIEW CUSTOMER_MISSING
  I5 WIRE 4 at cost 9.80 → NEEDS_REVIEW COST_MISMATCH (amount 10.00 from book cost)
  I6 WIRE 3 for "Other Co" → not a SPA sale
Unclaimed OK = 25.00 + 525.00 + 350.00 = 900.00
"""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import World, login
from tests.api.test_workflow import imp

SALES_COLS = {
    "supplier_code": "Vendor",
    "invoice_number": "Invoice",
    "line_number": "Line",
    "invoice_date": "Date",
    "customer": "Customer",
    "sku": "Item",
    "quantity": "Qty",
    "unit_cost": "Cost",
}
SALES = (
    "Vendor,Invoice,Line,Date,Customer,Item,Qty,Cost\n"
    "ACME,I1,1,02/01/2025,Hospital Build,WIRE,10,10.00\n"
    "ACME,I2,1,02/05/2025,Hospital Build,BOX,60,40.00\n"
    "ACME,I3,1,02/06/2025,hospital build,BOX,60,\n"
    "ACME,I4,1,02/07/2025,,WIRE,5,10.00\n"
    "ACME,I5,1,02/08/2025,Hospital Build,WIRE,4,9.80\n"
    "ACME,I6,1,02/09/2025,Other Co,WIRE,3,10.00\n"
)
SPA: dict[str, Any] = {
    "spa_number": "SPA-100",
    "customer": "Hospital Build",
    "valid_from": "2025-01-01",
    "valid_to": "2025-12-31",
    "claim_deadline_days": 60,
    "items": [
        {"sku": "WIRE", "book_cost": "10.00", "spa_cost": "7.50"},
        {"sku": "BOX", "book_cost": "40.00", "spa_cost": "31.25", "quantity_cap": "100"},
    ],
}


@pytest.fixture
def spa_setup(app_client: TestClient, world: World) -> Any:
    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    c = app_client
    sid = c.post("/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME"]}).json()["id"]
    r = c.post("/api/v1/spas", json={**SPA, "supplier_id": sid})
    assert r.status_code == 201, r.text
    imp(c, "sales", SALES, SALES_COLS)
    return c, world, t, sid, r.json()["id"]


def _matches(c: TestClient, **params: Any) -> list[dict[str, Any]]:
    return list(c.get("/api/v1/spa/matches", params=params).json())


def test_sales_are_matched_with_reasons(spa_setup: Any) -> None:
    c, _w, _t, sid, _spa = spa_setup
    rows = {m["invoice_number"]: m for m in _matches(c)}
    assert set(rows) == {"I1", "I2", "I3", "I4", "I5"}  # I6 is not a SPA sale
    assert (rows["I1"]["status"], rows["I1"]["claimable_amount"], rows["I1"]["spa_number"]) == (
        "ok",
        "25.00",
        "SPA-100",
    )
    assert rows["I1"]["deadline"] == "2025-04-02"  # 1 Feb + 60 days
    assert (rows["I2"]["claimable_quantity"], rows["I2"]["claimable_amount"]) == (
        "60.0000",
        "525.00",
    )
    assert (rows["I3"]["claimable_quantity"], rows["I3"]["claimable_amount"]) == (
        "40.0000",
        "350.00",
    )
    assert [x["code"] for x in rows["I3"]["reasons"]] == ["CAP_PARTIAL"]
    assert (rows["I4"]["status"], [x["code"] for x in rows["I4"]["reasons"]]) == (
        "needs_review",
        ["CUSTOMER_MISSING"],
    )
    assert (rows["I5"]["status"], rows["I5"]["claimable_amount"]) == ("needs_review", "10.00")
    assert [x["code"] for x in rows["I5"]["reasons"]] == ["COST_MISMATCH"]
    [s] = c.get("/api/v1/spa/summary").json()
    assert (
        s["supplier_id"],
        s["unclaimed_amount"],
        s["unclaimed_lines"],
        s["needs_review_lines"],
    ) == (sid, "900.00", 3, 2)


def test_claim_lifecycle_with_partial_then_full_payment(spa_setup: Any) -> None:
    c, _w, _t, sid, _spa = spa_setup
    key = str(uuid.uuid4())
    r = c.post(
        "/api/v1/spa-claims",
        json={"supplier_id": sid, "through_date": "2025-02-28"},
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    claim = r.json()
    assert (claim["number"], claim["status"], claim["total"], claim["line_count"]) == (
        1,
        "draft",
        "900.00",
        3,
    )
    again = c.post(
        "/api/v1/spa-claims",
        json={"supplier_id": sid, "through_date": "2025-02-28"},
        headers={"Idempotency-Key": key},
    )
    assert again.json()["id"] == claim["id"]  # replay, not a second claim
    assert _matches(c, unclaimed=True, status="ok") == []

    evidence = c.get(f"/api/v1/spa-claims/{claim['id']}/evidence.csv")
    lines = list(csv.DictReader(io.StringIO(evidence.text)))
    assert [(x["Invoice"], x["Amount claimed"]) for x in lines] == [
        ("I1", "25.00"),
        ("I2", "525.00"),
        ("I3", "350.00"),
    ]
    assert {x["SPA"] for x in lines} == {"SPA-100"}

    def step(body: dict[str, Any]) -> dict[str, Any]:
        etag = c.get(f"/api/v1/spa-claims/{claim['id']}").headers["ETag"]
        resp = c.post(
            f"/api/v1/spa-claims/{claim['id']}/transition", json=body, headers={"If-Match": etag}
        )
        assert resp.status_code == 200, resp.text
        return dict(resp.json())

    assert step({"to": "submitted"})["status"] == "submitted"
    part = step({"to": "paid", "paid_amount": "850.00", "credit_reference": "CM-9"})
    assert (part["status"], part["paid_amount"]) == ("partially_paid", "850.00")
    full = step({"to": "paid", "paid_amount": "50.00", "credit_reference": "CM-10"})
    assert (full["status"], full["paid_amount"]) == ("paid", "900.00")

    stale = c.post(
        f"/api/v1/spa-claims/{claim['id']}/transition",
        json={"to": "rejected"},
        headers={"If-Match": '"v1"'},
    )
    assert stale.status_code == 412


def test_rejected_claim_releases_its_lines(spa_setup: Any) -> None:
    c, _w, _t, sid, _spa = spa_setup
    claim = c.post(
        "/api/v1/spa-claims", json={"supplier_id": sid, "through_date": "2025-02-03"}
    ).json()
    assert claim["total"] == "25.00"
    etag = c.get(f"/api/v1/spa-claims/{claim['id']}").headers["ETag"]
    r = c.post(
        f"/api/v1/spa-claims/{claim['id']}/transition",
        json={"to": "rejected"},
        headers={"If-Match": etag},
    )
    assert r.json()["status"] == "rejected"
    ok = {m["invoice_number"] for m in _matches(c, unclaimed=True, status="ok")}
    assert ok == {"I1", "I2", "I3"}


def test_claimed_lines_stay_frozen_and_keep_using_the_cap(spa_setup: Any) -> None:
    c, _w, _t, sid, spa_id = spa_setup
    c.post("/api/v1/spa-claims", json={"supplier_id": sid, "through_date": "2025-02-28"})
    etag = c.get(f"/api/v1/spas/{spa_id}").headers["ETag"]
    changed = {k: v for k, v in SPA.items() if k != "spa_number"} | {
        "status": "active",
        "notes": "renegotiated",
    }
    changed["items"] = [
        {"sku": "WIRE", "book_cost": "10.00", "spa_cost": "7.00"},
        {"sku": "BOX", "book_cost": "40.00", "spa_cost": "31.25", "quantity_cap": "100"},
    ]
    r = c.put(f"/api/v1/spas/{spa_id}", json=changed, headers={"If-Match": etag})
    assert r.status_code == 200, r.text
    imp(
        c,
        "sales",
        "Vendor,Invoice,Line,Date,Customer,Item,Qty,Cost\nACME,I7,1,02/20/2025,Hospital Build,BOX,10,40.00\n",
        SALES_COLS,
    )
    rows = {m["invoice_number"]: m for m in _matches(c)}
    assert rows["I1"]["claimable_amount"] == "25.00"  # in a claim: not recalculated at 3.00/unit
    assert (rows["I7"]["status"], [x["code"] for x in rows["I7"]["reasons"]]) == (
        "not_claimable",
        ["CAP_REACHED"],
    )


def test_validation_and_permissions(spa_setup: Any) -> None:
    c, w, t, sid, _spa = spa_setup
    r = c.post("/api/v1/spas", json={**SPA, "supplier_id": sid})
    assert r.status_code == 409 and r.json()["code"] == "SPA_NUMBER_TAKEN"
    bad = {**SPA, "spa_number": "X", "supplier_id": sid, "valid_to": "2024-12-31"}
    assert c.post("/api/v1/spas", json=bad).json()["code"] == "SPA_DATES_INVALID"
    dup = {
        **SPA,
        "spa_number": "Y",
        "supplier_id": sid,
        "items": [SPA["items"][0], SPA["items"][0]],
    }
    assert c.post("/api/v1/spas", json=dup).json()["code"] == "SPA_ITEMS_INVALID"
    r = c.post("/api/v1/spa-claims", json={"supplier_id": sid, "through_date": "2024-01-01"})
    assert r.status_code == 422 and r.json()["code"] == "NOTHING_TO_CLAIM"
    login(c, w.member(t, "viewer"))
    assert c.get("/api/v1/spa/matches").status_code == 200
    assert (
        c.post(
            "/api/v1/spa-claims", json={"supplier_id": sid, "through_date": "2025-02-28"}
        ).status_code
        == 403
    )
