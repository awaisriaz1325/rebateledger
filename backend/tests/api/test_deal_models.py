"""Deal modelling (v1.1 Phase 13): hand-worked expectations over the workflow fixture.

Fixture (tests.api.test_workflow.world_setup): supplier ACME, purchases
Q1 2025 = 100,000.00 (60,000 on 15 Jan + 40,000 on 20 Mar), Q2 2025 = 50,000.00 (10 Apr).
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine.models import PurchaseLine
from app.services import deal_models
from app.services.agreement_terms import VersionTermsIn, to_snapshot
from tests.api.conftest import login
from tests.api.factories import TERMS
from tests.api.test_workflow import world_setup  # noqa: F401 - shared pytest fixture

WINDOW = {"window_start": "2025-01-01", "window_end": "2025-06-30"}


def flat() -> dict[str, Any]:
    return {**copy.deepcopy(TERMS), "effective_from": "2027-01-01"}


def tiered() -> dict[str, Any]:
    t = flat()
    t["components"] = [
        {
            "key": "volume",
            "type": "tiered_all_units",
            "tiers": [
                {"threshold": "60000", "rate": "0.01"},
                {"threshold": "90000", "rate": "0.03"},
            ],
        }
    ]
    return t


def evaluate(c: Any, sid: str, options: list[tuple[str, dict[str, Any]]], **window: str) -> Any:
    return c.post(
        "/api/v1/deal-models/evaluate",
        json={
            "supplier_id": sid,
            **(window or WINDOW),
            "options": [{"label": label, "terms": terms} for label, terms in options],
        },
    )


def test_flat_option_matches_the_real_preview_and_hand_worked_totals(
    world_setup: Any,  # noqa: F811 - the fixture imported above
) -> None:
    c, _w, _t, sid, aid = world_setup
    r = evaluate(c, sid, [("Current 2%", flat())])
    assert r.status_code == 200, r.text
    opt = r.json()["options"][0]
    assert [(p["label"], p["expected"]) for p in opt["periods"]] == [
        ("2025-Q1", "2000.00"),
        ("2025-Q2", "1000.00"),
    ]
    assert opt["total_expected"] == "3000.00"
    assert opt["total_spend"] == "150000.0000"  # engine precision for spend
    assert opt["effective_rate"] == "0.020000"
    assert opt["complete"] is True
    assert "2.00%" in opt["summary"]

    # Same rules on the same data as the activated agreement's own preview.
    version_id = c.get(f"/api/v1/agreements/{aid}").json()["versions"][0]["id"]
    real = c.post(
        f"/api/v1/agreement-versions/{version_id}/preview", json={"period_containing": "2025-02-15"}
    ).json()
    assert real["expected"] == opt["periods"][0]["expected"]

    # Spend scaled within the window only; flat 2% scales linearly.
    sens = {s["factor"]: s["total_expected"] for s in opt["sensitivity"]}
    assert sens == {"0.8": "2400.00", "0.9": "2700.00", "1.1": "3300.00", "1.2": "3600.00"}


def test_tiered_option_is_compared_side_by_side_with_tier_jumps_in_sensitivity(
    world_setup: Any,  # noqa: F811
) -> None:
    c, _w, _t, sid, _aid = world_setup
    r = evaluate(c, sid, [("Flat", flat()), ("Tiered", tiered())])
    assert r.status_code == 200, r.text
    flat_opt, tier_opt = r.json()["options"]
    assert flat_opt["label"] == "Flat" and tier_opt["label"] == "Tiered"
    # Q1 100,000 reaches tier 2 (3% all units) = 3,000.00; Q2 50,000 reaches no tier = 0.00.
    assert [(p["expected"], p["tier_reached"]) for p in tier_opt["periods"]] == [
        ("3000.00", 2),
        ("0.00", None),
    ]
    assert tier_opt["total_expected"] == "3000.00"
    sens = {s["factor"]: s["total_expected"] for s in tier_opt["sensitivity"]}
    # 0.8: Q1 80,000 → tier 1 (1%) 800.00; Q2 40,000 → 0.     Total   800.00
    # 0.9: Q1 90,000 → tier 2 (3%) 2,700.00; Q2 45,000 → 0.   Total 2,700.00
    # 1.1: Q1 110,000 → 3,300.00; Q2 55,000 → 0.              Total 3,300.00
    # 1.2: Q1 120,000 → 3,600.00; Q2 60,000 → tier 1 600.00.  Total 4,200.00
    assert sens == {"0.8": "800.00", "0.9": "2700.00", "1.1": "3300.00", "1.2": "4200.00"}


def test_window_and_option_limits(world_setup: Any) -> None:  # noqa: F811
    c, _w, _t, sid, _aid = world_setup
    r = evaluate(c, sid, [("A", flat())], window_start="2023-01-01", window_end="2025-06-30")
    assert r.status_code == 422 and r.json()["code"] == "WINDOW_INVALID"
    r = evaluate(c, sid, [("A", flat())], window_start="2025-06-30", window_end="2025-01-01")
    assert r.status_code == 422 and r.json()["code"] == "WINDOW_INVALID"
    r = evaluate(c, sid, [("A", flat())], window_start="2025-01-15", window_end="2025-03-31")
    assert r.status_code == 422 and r.json()["code"] == "WINDOW_TOO_SHORT"
    r = evaluate(c, sid, [(str(i), flat()) for i in range(5)])
    assert r.status_code == 422
    custom = flat()
    custom["period_type"] = "custom"
    custom["custom_periods"] = [{"start": "2027-01-01", "end": "2027-06-30", "label": "H1"}]
    r = evaluate(c, sid, [("A", custom)])
    assert r.status_code == 422 and r.json()["code"] == "CUSTOM_PERIODS_NOT_SUPPORTED"


def test_nothing_is_saved_and_viewers_cannot_model(world_setup: Any) -> None:  # noqa: F811
    c, w, t, sid, _aid = world_setup
    before = len(c.get("/api/v1/agreements").json()["items"])
    assert evaluate(c, sid, [("A", flat())]).status_code == 200
    assert len(c.get("/api/v1/agreements").json()["items"]) == before
    login(c, w.member(t, "viewer"))
    assert evaluate(c, sid, [("A", flat())]).status_code == 403


def test_other_tenant_supplier_is_not_found(world_setup: Any) -> None:  # noqa: F811
    c, w, _t, sid, _aid = world_setup
    other = w.tenant()
    login(c, w.member(other, "owner"))
    r = evaluate(c, sid, [("A", flat())])
    assert r.status_code == 404


def test_sensitivity_never_scales_lines_outside_the_window() -> None:
    terms = VersionTermsIn.model_validate(flat())
    snap = to_snapshot(
        terms,
        agreement_id="m",
        version_id="m",
        version_no=1,
        supplier_id="s",
        fiscal_start=1,
    )
    before = PurchaseLine(
        "a", "s", Decimal("1"), Decimal("100.00"), invoice_date=date(2024, 12, 31)
    )
    inside = PurchaseLine("b", "s", Decimal("2"), Decimal("200.00"), invoice_date=date(2025, 1, 1))
    undated = PurchaseLine("c", "s", Decimal("1"), Decimal("50.00"))
    out = deal_models._scaled(
        [before, inside, undated], snap, date(2025, 1, 1), date(2025, 6, 30), Decimal("1.1")
    )
    assert out[0] == before
    assert out[1].amount == Decimal("220.000") and out[1].quantity == Decimal("2.2")
    assert out[2] == undated
