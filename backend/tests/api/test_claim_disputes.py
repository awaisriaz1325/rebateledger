"""Dispute tracking on claims (v1.3 Phase 27).

A submitted (or acknowledged) claim can be marked disputed with the supplier's reason and,
optionally, the amount the supplier accepts. From disputed it can be acknowledged, resubmitted,
resolved, rejected or written off. The register shows the reason, the supplier's amount and how
long the dispute has been open.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.api.test_workflow import (
    CREDIT_COLS,
    imp,
    run,
    world_setup,  # noqa: F401 - shared pytest fixture
)


@pytest.fixture
def submitted(world_setup: Any) -> Any:  # noqa: F811
    c, *_ = world_setup
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    run(c)
    q1 = next(
        r for r in c.get("/api/v1/reconciliation").json() if r["period_start"] == "2025-01-01"
    )
    claim = c.post("/api/v1/claims", json={"result_ids": [q1["result_id"]]}).json()
    r = c.post(f"/api/v1/claims/{claim['id']}/transition", json={"to": "submitted"})
    assert r.status_code == 200, r.text
    return c, claim["id"]


def _to(c: Any, cid: str, **body: Any) -> Any:
    return c.post(f"/api/v1/claims/{cid}/transition", json=body)


def test_dispute_records_reason_and_supplier_amount(submitted: Any) -> None:
    c, cid = submitted
    r = _to(c, cid, to="disputed", dispute_reason="rate_or_tier", dispute_amount="300.00",
            note="Supplier says tier 2 starts at 120,000")  # fmt: skip
    assert r.status_code == 200, r.text
    claim = r.json()
    assert claim["status"] == "disputed"
    assert claim["dispute_reason"] == "rate_or_tier"
    assert claim["dispute_amount"] in ("300.00", "300.0000")
    assert claim["disputed_at"] is not None
    assert "acknowledged" in claim["allowed_transitions"]
    assert "submitted" in claim["allowed_transitions"]  # resubmit with corrected evidence
    events = [e for e in claim["events"] if e["type"] == "status_changed"]
    assert "Rate or tier" in events[-1]["text"] and "300.00" in events[-1]["text"]


def test_dispute_needs_a_reason_and_a_sent_claim(submitted: Any, world_setup: Any) -> None:  # noqa: F811
    c, cid = submitted
    r = _to(c, cid, to="disputed")
    assert r.status_code == 422, r.text
    r = _to(c, cid, to="disputed", dispute_reason="made_up")
    assert r.status_code == 422
    r = _to(c, cid, to="disputed", dispute_reason="timing", dispute_amount="-5.00")
    assert r.status_code == 422
    # A draft claim has not been sent, so it cannot be disputed.
    q2 = next(
        r for r in c.get("/api/v1/reconciliation").json() if r["period_start"] == "2025-04-01"
    )
    draft = c.post("/api/v1/claims", json={"result_ids": [q2["result_id"]]}).json()
    r = _to(c, draft["id"], to="disputed", dispute_reason="timing")
    assert r.status_code == 409 and r.json()["code"] == "TRANSITION_NOT_ALLOWED"
    # Dispute fields only make sense when moving to disputed.
    r = _to(c, draft["id"], to="submitted", dispute_reason="timing")
    assert r.status_code == 422


def test_register_shows_open_disputes(submitted: Any) -> None:
    c, cid = submitted
    assert _to(c, cid, to="disputed", dispute_reason="eligibility").status_code == 200
    r = c.get("/api/v1/reports/preview", params={"report": "claims_register"})
    assert r.status_code == 200, r.text
    [row] = r.json()["rows"]
    assert row["status"] == "disputed"
    assert row["dispute_reason"] == "Eligibility"
    assert row["dispute_days"] == "0"
    # Leaving the dispute keeps its history but stops the clock.
    assert _to(c, cid, to="acknowledged").status_code == 200
    [row] = c.get("/api/v1/reports/preview", params={"report": "claims_register"}).json()["rows"]
    assert row["dispute_reason"] == "Eligibility" and row["dispute_days"] == ""
