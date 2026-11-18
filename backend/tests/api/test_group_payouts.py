"""Buying-group payouts (v1.2 Phase 23, ADR 0019 D3). Hand-worked values.

Fixture (tests.api.test_workflow.world_setup): ACME-1, 2% flat quarterly; Q1 2025 earned 2,000.00,
Q2 earned 1,000.00. Acme is a member of buying group AD; ACME-1 is paid through AD; AD keeps 10%.

- Q1 expected from AD = 2,000.00 × (1 − 0.10) = 1,800.00
- Q2 expected from AD = 1,000.00 × 0.90     =   900.00
Credits from AD (supplier code AD):
- CM-AD-1 1,800.00 for ACME-1 Q1 → auto-matched → MATCHED (variance 0.00)
- CM-AD-2   700.00 for ACME-1 Q2 → auto-matched → SHORT_PAID by 200.00
Report totals: earned 3,000.00, fee 300.00, expected 2,700.00, received 2,500.00, variance −200.00.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.group_payouts import fee_amount, net_expected
from tests.api.conftest import login
from tests.api.test_exports import _download, _export
from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)


def test_net_expected_rounds_half_up_once() -> None:
    assert net_expected(Decimal("2000.00"), Decimal("0.10")) == Decimal("1800.00")
    # 333.33 × 0.925 = 308.33025 → 308.33 ; fee = 25.00
    assert net_expected(Decimal("333.33"), Decimal("0.075")) == Decimal("308.33")
    assert fee_amount(Decimal("333.33"), Decimal("0.075")) == Decimal("25.00")
    # 10.10 × 0.95 = 9.595 → half-up 9.60
    assert net_expected(Decimal("10.10"), Decimal("0.05")) == Decimal("9.60")
    assert Decimal("9.595").quantize(Decimal("0.01"), ROUND_HALF_UP) == Decimal("9.60")
    assert net_expected(Decimal("10.00"), None) == Decimal("10.00")
    assert net_expected(None, Decimal("0.10")) is None


def _patch(c: Any, path: str, body: dict[str, Any]) -> Any:
    head = c.get(path)
    return c.patch(path, json=body, headers={"If-Match": head.headers["ETag"]})


def _group(c: Any, sid: str, aid: str, fee: str | None = "0.10") -> str:
    ad = c.post(
        "/api/v1/suppliers", json={"name": "AD", "codes": ["AD"], "kind": "buying_group"}
    ).json()["id"]
    assert c.put(f"/api/v1/suppliers/{ad}/members", json={"supplier_ids": [sid]}).status_code == 200
    if fee is not None:
        r = _patch(c, f"/api/v1/suppliers/{ad}", {"group_fee_pct": fee})
        assert r.status_code == 200 and r.json()["group_fee_pct"] == fee, r.text
    r = _patch(c, f"/api/v1/agreements/{aid}", {"paid_via_group_id": ad})
    assert r.status_code == 200 and r.json()["paid_via_group_id"] == ad, r.text
    return str(ad)


GROUP_CREDITS = (
    "Vendor,Memo,Date,Amount,Program,Period\n"
    "AD,CM-AD-1,04/20/2025,1800.00,ACME-1,Q1 2025\n"
    "AD,CM-AD-2,07/20/2025,700.00,ACME-1,Q2 2025\n"
)


def test_group_credits_reconcile_against_rebate_net_of_fee(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, aid = world_setup
    _group(c, sid, aid)
    imp(c, "credits", GROUP_CREDITS, CREDIT_COLS)
    run(c)
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    q1, q2 = rows["2025-01-01"], rows["2025-04-01"]

    def got(r: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, str]:
        return Decimal(r["expected"]), Decimal(r["received"]), Decimal(r["variance"]), r["status"]

    assert got(q1) == (Decimal("1800.00"), Decimal("1800.00"), Decimal(0), "MATCHED")
    assert got(q2) == (Decimal("900.00"), Decimal("700.00"), Decimal("-200.00"), "SHORT_PAID")


def test_report_shows_earned_fee_and_passed_through(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, aid = world_setup
    ad = _group(c, sid, aid)
    imp(c, "credits", GROUP_CREDITS, CREDIT_COLS)
    run(c)
    r = c.get("/api/v1/reports/preview", params={"report": "group_payouts", "supplier_id": ad})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(x["period_start"], x["earned"], x["fee"], x["expected"]) for x in body["rows"]] == [
        ("2025-01-01", "2000.00", "200.00", "1800.00"),
        ("2025-04-01", "1000.00", "100.00", "900.00"),
    ]
    assert body["totals"] == {
        "earned": "3000.00",
        "fee": "300.00",
        "expected": "2700.00",
        "received": "2500.00",
        "variance": "-200.00",
    }
    assert _download(c, _export(c, "group_payouts", "pdf")).startswith(b"%PDF")


def test_without_a_fee_the_full_rebate_is_expected(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, aid = world_setup
    _group(c, sid, aid, fee=None)
    imp(c, "credits", GROUP_CREDITS, CREDIT_COLS)
    run(c)
    q1 = next(
        r for r in c.get("/api/v1/reconciliation").json() if r["period_start"] == "2025-01-01"
    )
    assert (q1["expected"], q1["status"]) == ("2000.00", "SHORT_PAID")


def test_manual_split_of_one_group_credit_never_exceeds_it(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, aid = world_setup
    _group(c, sid, aid)
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nAD,CM-AD-9,08/01/2025,2700.00,,\n",
        CREDIT_COLS,
    )
    run(c)
    credit = next(
        x for x in c.get("/api/v1/credits").json()["items"] if x["credit_reference"] == "CM-AD-9"
    )
    too_much = [
        {
            "agreement_id": aid,
            "period_start": "2025-01-01",
            "period_end": "2025-03-31",
            "amount": "1800.00",
        },
        {
            "agreement_id": aid,
            "period_start": "2025-04-01",
            "period_end": "2025-06-30",
            "amount": "900.01",
        },
    ]
    r = c.post(f"/api/v1/credits/{credit['id']}/allocations", json={"parts": too_much})
    assert r.status_code == 422, r.text
    exact = [{**too_much[0]}, {**too_much[1], "amount": "900.00"}]
    r = c.post(f"/api/v1/credits/{credit['id']}/allocations", json={"parts": exact})
    assert r.status_code == 201, r.text
    statuses = {r["period_start"]: r["status"] for r in c.get("/api/v1/reconciliation").json()}
    assert statuses == {"2025-01-01": "MATCHED", "2025-04-01": "MATCHED"}


def test_guards(world_setup: Any) -> None:  # noqa: F811
    c, w, t, sid, aid = world_setup
    # A fee only on buying groups, and below 100%.
    assert (
        _patch(c, f"/api/v1/suppliers/{sid}", {"group_fee_pct": "0.10"}).json()["code"]
        == "GROUP_FEE_INVALID"
    )
    ad = _group(c, sid, aid)
    assert (
        _patch(c, f"/api/v1/suppliers/{ad}", {"group_fee_pct": "1"}).json()["code"]
        == "GROUP_FEE_INVALID"
    )
    assert (
        _patch(c, f"/api/v1/suppliers/{ad}", {"group_fee_pct": None}).json()["group_fee_pct"]
        is None
    )
    # Paid-via must be a buying group the agreement's supplier belongs to.
    other = c.post(
        "/api/v1/suppliers", json={"name": "G2", "codes": ["G2"], "kind": "buying_group"}
    ).json()["id"]
    assert (
        _patch(c, f"/api/v1/agreements/{aid}", {"paid_via_group_id": other}).json()["code"]
        == "NOT_A_GROUP_MEMBER"
    )
    assert (
        _patch(c, f"/api/v1/agreements/{aid}", {"paid_via_group_id": sid}).json()["code"]
        == "NOT_A_BUYING_GROUP"
    )
    assert (
        _patch(c, f"/api/v1/agreements/{aid}", {"paid_via_group_id": None}).json()[
            "paid_via_group_id"
        ]
        is None
    )
    # Without the link, a group credit cannot be allocated to the member's agreement.
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nAD,CM-AD-5,08/01/2025,10.00,,\n",
        CREDIT_COLS,
    )
    run(c)
    credit = next(
        x for x in c.get("/api/v1/credits").json()["items"] if x["credit_reference"] == "CM-AD-5"
    )
    part = {
        "agreement_id": aid,
        "period_start": "2025-01-01",
        "period_end": "2025-03-31",
        "amount": "10.00",
    }
    r = c.post(f"/api/v1/credits/{credit['id']}/allocations", json={"parts": [part]})
    assert r.status_code == 422 and r.json()["code"] == "SUPPLIER_MISMATCH"
    # Another tenant's group cannot be linked.
    other_t = w.tenant()
    login(c, w.member(other_t, "analyst"))
    foreign = c.post(
        "/api/v1/suppliers", json={"name": "X", "codes": ["XG"], "kind": "buying_group"}
    ).json()["id"]
    login(c, w.member(t, "analyst"))
    assert _patch(c, f"/api/v1/agreements/{aid}", {"paid_via_group_id": foreign}).status_code == 404


def test_accrual_receivable_is_net_of_the_group_fee(world_setup: Any) -> None:  # noqa: F811
    """Bug fix: the month-end accrual booked the group's fee as money receivable.

    Closing 2025-05-31, AD keeps 10%:
    - Q1 closed: 2,000.00 earned → 1,800.00 expected from AD; 1,800.00 received → nothing outstanding
    - Q2 open (Apr–May): 50,000 × 2% = 1,000.00 to date → 900.00 expected from AD; none received
    Outstanding 900.00 (before the fix: 200.00 + 1,000.00 = 1,200.00).
    """
    c, _w, _t, sid, aid = world_setup
    _group(c, sid, aid)
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nAD,CM-AD-1,04/20/2025,1800.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    j = c.get("/api/v1/accruals/journal", params={"closing_date": "2025-05-31"}).json()
    assert [(ln["period_start"], ln["outstanding"]) for ln in j["lines"]] == [
        ("2025-04-01", "900.00")
    ]


def test_statement_from_the_paying_group_matches_and_compares_net(world_setup: Any) -> None:  # noqa: F811
    """A buying group's statement about a member's program (paid through it) matches that program
    and is compared with what the group owes: Q1 2,000.00 × 0.90 = 1,800.00."""
    c, _w, _t, sid, aid = world_setup
    _group(c, sid, aid)
    run(c)
    imp(
        c,
        "statements",
        "Vendor,Program,From,To,Rebate,Statement\nAD,ACME-1,01/01/2025,03/31/2025,1800.00,AD-ST-1\n"
        "AD,,04/01/2025,06/30/2025,850.00,AD-ST-2\n",
        {
            "supplier_code": "Vendor",
            "agreement_reference": "Program",
            "period_start": "From",
            "period_end": "To",
            "supplier_rebate": "Rebate",
            "statement_reference": "Statement",
        },
    )
    rows = {r["statement_reference"]: r for r in c.get("/api/v1/statements").json()}
    st1 = rows["AD-ST-1"]
    assert (st1["match_status"], st1["status"], st1["ours"], st1["difference"]) == (
        "matched",
        "agrees",
        "1800.00",
        "0.00",
    )
    # No reference: the group passes through one program, so it is suggested; confirm it.
    assert rows["AD-ST-2"]["match_status"] == "suggested"
    r = c.put(f"/api/v1/statements/{rows['AD-ST-2']['id']}/agreement", json={"agreement_id": aid})
    assert r.status_code == 200, r.text
    assert (r.json()["ours"], r.json()["difference"], r.json()["status"]) == (
        "900.00",
        "50.00",
        "rate_or_tier_differs",
    )
