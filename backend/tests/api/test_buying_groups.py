"""Buying-group programs end to end (v1.1 Phase 16, ADR 0017 §3). Hand-worked values.

Group AFG (members ACME, BETA) runs a quarterly program: all-units tiers
>= 100,000 -> 1% ; >= 200,000 -> 2%. ACME also has its own exclusive 2% flat agreement.
Q1 2025 purchases: ACME 120,000 ; BETA 90,000 ; GAMMA (not a member) 50,000.
- Group: M = 210,000 -> tier 2 -> 2% x 210,000 = 4,200.00
- ACME own: 2% x 120,000 = 2,400.00 (counts for both: different payers)
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import World, login
from tests.api.factories import TERMS
from tests.api.test_workflow import CREDIT_COLS, PURCHASE_COLS, imp, run

GROUP_TERMS = {
    **TERMS,
    "effective_from": "2025-01-01",
    "components": [
        {
            "key": "vol",
            "type": "tiered_all_units",
            "tiers": [
                {"threshold": "100000", "rate": "0.01"},
                {"threshold": "200000", "rate": "0.02"},
            ],
        }
    ],
}


def _supplier(c: TestClient, name: str, code: str, kind: str = "supplier") -> str:
    r = c.post("/api/v1/suppliers", json={"name": name, "codes": [code], "kind": kind})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == kind
    return str(r.json()["id"])


def _agreement(c: TestClient, sid: str, name: str, terms: dict[str, Any], ref: str) -> str:
    a = c.post(
        "/api/v1/agreements",
        json={"supplier_id": sid, "name": name, "external_reference": ref, "terms": terms},
    ).json()
    r = c.post(f"/api/v1/agreement-versions/{a['versions'][0]['id']}/activate", json={})
    assert r.status_code == 200, r.text
    return str(a["id"])


@pytest.fixture
def group(app_client: TestClient, world: World) -> Any:
    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    c = app_client
    acme = _supplier(c, "Acme", "ACME")
    beta = _supplier(c, "Beta", "BETA")
    _supplier(c, "Gamma", "GAMMA")
    afg = _supplier(c, "Affiliated Group", "AFG", "buying_group")
    r = c.put(f"/api/v1/suppliers/{afg}/members", json={"supplier_ids": [acme, beta]})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["member_ids"]) == sorted([acme, beta])
    assert c.get(f"/api/v1/suppliers/{acme}").json()["group_ids"] == [afg]
    g_id = _agreement(c, afg, "AFG volume program", GROUP_TERMS, "AFG-1")
    own = {**TERMS, "effective_from": "2025-01-01", "stacking": "exclusive"}
    a_id = _agreement(c, acme, "Acme own", own, "ACME-1")
    imp(
        c,
        "purchases",
        "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\n"
        "ACME,I1,1,A,1,120000.00,01/15/2025\n"
        "BETA,I2,1,B,1,90000.00,02/10/2025\n"
        "GAMMA,I3,1,C,1,50000.00,02/11/2025\n",
        PURCHASE_COLS,
    )
    return (
        c,
        world,
        t,
        {"acme": acme, "beta": beta, "afg": afg, "group_agreement": g_id, "acme_agreement": a_id},
    )


def _q1(c: TestClient, agreement_id: str) -> dict[str, Any]:
    rows = c.get("/api/v1/reconciliation", params={"agreement_id": agreement_id}).json()
    return next(r for r in rows if r["period_start"] == "2025-01-01")


def test_group_program_counts_members_and_stacks_with_supplier_deal(group: Any) -> None:
    c, _w, _t, ids = group
    run(c)
    g = _q1(c, ids["group_agreement"])
    assert (g["expected"], g["engine_statuses"]) == ("4200.00", ["OK"])
    own = _q1(c, ids["acme_agreement"])
    assert (own["expected"], own["engine_statuses"]) == ("2400.00", ["OK"])


def test_group_credit_matches_the_group_program(group: Any) -> None:
    c, _w, _t, ids = group
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nAFG,CM-G1,04/25/2025,4200.00,AFG-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    g = _q1(c, ids["group_agreement"])
    assert (g["received"], g["status"]) == ("4200.0000", "MATCHED")


def test_purchases_under_a_group_code_are_rejected(group: Any) -> None:
    c, *_ = group
    r = c.post(
        "/api/v1/imports",
        files={
            "file": (
                f"p-{uuid.uuid4().hex}.csv",
                b"Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\nAFG,I9,1,A,1,10.00,01/20/2025\n",
                "text/csv",
            )
        },
        data={"import_type": "purchases"},
    )
    bid = r.json()["id"]
    c.put(
        f"/api/v1/imports/{bid}/config",
        json={"columns": PURCHASE_COLS, "date_format": "MM/DD/YYYY"},
    )
    rows = c.post(f"/api/v1/imports/{bid}/validate-preview").json()["rows"]
    assert [i["code"] for i in rows[0]["issues"]] == ["SUPPLIER_IS_BUYING_GROUP"]


def test_member_change_marks_group_results_stale_and_changes_the_result(group: Any) -> None:
    c, _w, _t, ids = group
    run(c)
    r = c.put(f"/api/v1/suppliers/{ids['afg']}/members", json={"supplier_ids": [ids["acme"]]})
    assert r.status_code == 200
    assert _q1(c, ids["group_agreement"])["stale"] is True
    assert _q1(c, ids["acme_agreement"])["stale"] is False
    run(c)
    # Only ACME now: M = 120,000 -> tier 1 -> 1% = 1,200.00
    assert _q1(c, ids["group_agreement"])["expected"] == "1200.00"


def test_member_rules(group: Any, app_client: TestClient) -> None:
    c, w, _t, ids = group
    r = c.put(f"/api/v1/suppliers/{ids['acme']}/members", json={"supplier_ids": [ids["beta"]]})
    assert r.status_code == 409 and r.json()["code"] == "NOT_A_BUYING_GROUP"
    other_group = _supplier(c, "Second group", "G2", "buying_group")
    r = c.put(f"/api/v1/suppliers/{ids['afg']}/members", json={"supplier_ids": [other_group]})
    assert r.status_code == 422 and r.json()["code"] == "MEMBER_INVALID"
    r = c.post("/api/v1/suppliers/merge", json={"source_id": ids["beta"], "target_id": ids["afg"]})
    assert r.status_code == 409 and r.json()["code"] == "MERGE_BUYING_GROUP"
    assert [
        s["name"]
        for s in c.get("/api/v1/suppliers", params={"kind": "buying_group"}).json()["items"]
    ] == [
        "Affiliated Group",
        "Second group",
    ]
    # Another tenant's supplier cannot be added (404, never leaked).
    other = w.tenant()
    login(c, w.member(other, "analyst"))
    foreign = _supplier(c, "Foreign", "FOR")
    login(c, w.member(_t, "analyst"))
    r = c.put(f"/api/v1/suppliers/{ids['afg']}/members", json={"supplier_ids": [foreign]})
    assert r.status_code == 404


def test_merging_a_member_moves_its_membership(group: Any) -> None:
    c, _w, _t, ids = group
    delta = _supplier(c, "Delta", "DELTA")
    r = c.post("/api/v1/suppliers/merge", json={"source_id": ids["beta"], "target_id": delta})
    assert r.status_code == 200, r.text
    members = c.get(f"/api/v1/suppliers/{ids['afg']}").json()["member_ids"]
    assert sorted(members) == sorted([ids["acme"], delta])


def test_deal_model_and_tier_tracker_read_member_purchases(
    group: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date

    from app.services import tiers

    c, _w, _t, ids = group
    r = c.post(
        "/api/v1/deal-models/evaluate",
        json={
            "supplier_id": ids["afg"],
            "window_start": "2025-01-01",
            "window_end": "2025-03-31",
            "options": [
                {"label": "Group", "terms": {**GROUP_TERMS, "effective_from": "2027-01-01"}}
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["options"][0]["total_expected"] == "4200.00"
    monkeypatch.setattr(tiers, "today_in", lambda tz: date(2025, 2, 20))
    row = next(
        x for x in c.get("/api/v1/tiers").json() if x["agreement_name"] == "AFG volume program"
    )
    assert row["current_measure"] == "210000.0000" and row["current_tier"] == 2
