"""Phase 4 end-to-end: import → run → reconcile → claim → recover → dashboard (PHASES §4)."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.emails.service import RenderedEmail
from tests.api.conftest import World, login
from tests.api.factories import TERMS

PURCHASE_COLS = {
    "supplier_code": "Vendor",
    "invoice_number": "Invoice",
    "line_number": "Line",
    "sku": "Item",
    "quantity": "Qty",
    "amount": "Ext",
    "invoice_date": "Inv Date",
}
CREDIT_COLS = {
    "supplier_code": "Vendor",
    "credit_reference": "Memo",
    "credit_date": "Date",
    "amount": "Amount",
    "agreement_reference": "Program",
    "period_label": "Period",
}


def _client(c: TestClient) -> TestClient:
    return TestClient(
        c.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    )


def imp(
    c: TestClient, kind: str, csv: str, cols: dict[str, str], date_format: str = "MM/DD/YYYY"
) -> str:
    r = c.post(
        "/api/v1/imports",
        files={"file": (f"{kind}-{uuid.uuid4().hex}.csv", csv.encode(), "text/csv")},
        data={"import_type": kind},
    )
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    assert (
        c.put(
            f"/api/v1/imports/{bid}/config", json={"columns": cols, "date_format": date_format}
        ).status_code
        == 200
    )
    c.post(f"/api/v1/imports/{bid}/validate")
    r = c.post(f"/api/v1/imports/{bid}/commit", json={"mode": "all_or_nothing"})
    assert r.status_code == 202, r.text
    batch = c.get(f"/api/v1/imports/{bid}").json()
    assert batch["status"] == "committed", batch
    return str(bid)


def run(
    c: TestClient, start: str = "2025-01-01", end: str = "2025-06-30", **scope: Any
) -> dict[str, Any]:
    r = c.post(
        "/api/v1/runs",
        json={"scope": scope or {"type": "all"}, "period_start": start, "period_end": end},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 202, r.text
    assert r.headers["Location"].startswith("/api/v1/jobs/")
    out = c.get(f"/api/v1/runs/{r.json()['id']}").json()
    assert out["status"] == "succeeded", out
    return dict(out)


@pytest.fixture
def world_setup(
    app_client: TestClient, world: World
) -> tuple[TestClient, World, uuid.UUID, str, str]:
    """ACME: 2% flat, quarterly, 30-day terms; Q1 2025 purchases 100,000 → expected 2,000.00."""
    t = world.tenant(abs_tolerance="1.00", pct_tolerance="0.005")
    analyst = world.member(t, "analyst")
    login(app_client, analyst)
    sid = app_client.post("/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME"]}).json()[
        "id"
    ]
    terms = {**TERMS, "effective_from": "2025-01-01"}
    a = app_client.post(
        "/api/v1/agreements",
        json={
            "supplier_id": sid,
            "name": "Acme base",
            "external_reference": "ACME-1",
            "terms": terms,
        },
    ).json()
    assert (
        app_client.post(
            f"/api/v1/agreement-versions/{a['versions'][0]['id']}/activate", json={}
        ).status_code
        == 200
    )
    purchases = "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\nACME,I1,1,A,1,60000.00,01/15/2025\nACME,I2,1,A,1,40000.00,03/20/2025\nACME,I3,1,A,1,50000.00,04/10/2025\n"
    imp(app_client, "purchases", purchases, PURCHASE_COLS)
    return app_client, world, t, sid, a["id"]


def test_end_to_end_short_paid_claim_recovered(world_setup: Any) -> None:
    c, world, t, sid, aid = world_setup
    # Supplier paid 1,500.00 for Q1 (expected 2,000.00), referencing the program → auto-match.
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,CM-1,04/20/2025,1500.00,ACME-1,Q1 2025\n",
        CREDIT_COLS,
    )
    r1 = run(c)
    assert r1["totals"]["results"] == 2
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    q1, q2 = rows["2025-01-01"], rows["2025-04-01"]
    assert (q1["expected"], q1["received"], q1["variance"], q1["status"]) == (
        "2000.00",
        "1500.0000",
        "-500.0000",
        "SHORT_PAID",
    )
    assert (q2["expected"], q2["status"]) == (
        "1000.00",
        "MISSING",
    )  # 50,000 × 2%; no credit, past due
    disc = c.get("/api/v1/discrepancies").json()
    assert {d["status"] for d in disc} == {"SHORT_PAID", "MISSING"}
    assert disc[0]["status"] == "MISSING"  # sorted by absolute variance: 1,000 > 500

    claim = c.post("/api/v1/claims", json={"result_ids": [q1["result_id"]]}).json()
    assert (claim["identified_amount"], claim["claimed_amount"], claim["status"]) == (
        "500.0000",
        "500.0000",
        "draft",
    )
    assert (
        c.post("/api/v1/claims", json={"result_ids": [q1["result_id"]]}).json()["code"]
        == "ALREADY_CLAIMED"
    )
    assert (
        c.post(f"/api/v1/claims/{claim['id']}/transition", json={"to": "submitted"}).json()[
            "status"
        ]
        == "submitted"
    )
    assert (
        c.post(
            f"/api/v1/claims/{claim['id']}/transition", json={"to": "resolved_recovered"}
        ).json()["code"]
        == "RECOVERY_INCOMPLETE"
    )
    detail = c.post(
        f"/api/v1/claims/{claim['id']}/recoveries",
        json={
            "new_credit": {"reference": "CM-REC-1", "credit_date": "2025-08-01", "amount": "500.00"}
        },
    ).json()
    assert detail["recovered_amount"] == "500.0000"
    done = c.post(
        f"/api/v1/claims/{claim['id']}/transition", json={"to": "resolved_recovered"}
    ).json()
    assert done["status"] == "resolved_recovered" and done["allowed_transitions"] == []
    assert [e["type"] for e in done["events"]] == [
        "created",
        "status_changed",
        "recovery_linked",
        "status_changed",
    ]

    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    assert (rows["2025-01-01"]["received"], rows["2025-01-01"]["status"]) == (
        "2000.0000",
        "MATCHED",
    )
    assert rows["2025-01-01"]["stale"] is True  # allocation changed → prompt to re-run
    dash = c.get("/api/v1/dashboard").json()
    assert dash["identified_open_variance"]["amount"] == "1000.00"  # only Q2 still open
    assert (
        dash["recovered_this_year"]["amount"] == "0.00"
    )  # recovery credit dated 2025, dashboard year is current
    from app.core.clock import today_in

    world.sql(
        "UPDATE rl.credit_lines SET credit_date = :d WHERE credit_reference = 'CM-REC-1'",
        d=today_in("America/Chicago"),
    )
    assert c.get("/api/v1/dashboard").json()["recovered_this_year"]["amount"] == "500.00"
    assert c.get("/api/v1/dashboard").json()["open_claims"]["count"] == 0

    trace = c.get(f"/api/v1/results/{q1['result_id']}").json()
    assert [s["step"] for s in trace["trace"]] == list(range(1, 11)) and trace["run_number"] == r1[
        "number"
    ]
    _ = (sid, aid, t)


def test_stale_detection_for_every_trigger(world_setup: Any) -> None:
    c, world, _, sid, aid = world_setup
    run(c)

    def stale_reasons() -> dict[str, str | None]:
        return {
            r["period_start"]: r["stale_reason"] for r in c.get("/api/v1/reconciliation").json()
        }

    assert stale_reasons() == {"2025-01-01": None, "2025-04-01": None}
    # 1. new import overlapping the period
    bid = imp(
        c,
        "purchases",
        "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\nACME,I9,1,A,1,10.00,02/01/2025\n",
        PURCHASE_COLS,
    )
    assert stale_reasons()["2025-01-01"] == "new import overlapping the period"
    run(c)
    # 2. voided batch used by the latest run
    assert c.post(f"/api/v1/imports/{bid}/void", json={"reason": "wrong"}).status_code == 200
    assert stale_reasons()["2025-01-01"] == "an import used by this run was voided"
    run(c)
    # 3. new active version
    t2 = {**TERMS, "effective_from": "2025-07-01"}
    v2 = c.post(f"/api/v1/agreements/{aid}/versions", json=t2).json()
    c.post(f"/api/v1/agreement-versions/{v2['id']}/activate", json={})
    assert set(stale_reasons().values()) == {"version 2 activated"}
    run(c)
    # 4. credit allocation change
    credit = c.post(
        "/api/v1/credits",
        json={
            "supplier_id": sid,
            "reference": "MAN-1",
            "credit_date": "2025-05-01",
            "amount": "100.00",
        },
    ).json()
    r = c.post(
        f"/api/v1/credits/{credit['id']}/allocations",
        json={
            "parts": [
                {
                    "agreement_id": aid,
                    "period_start": "2025-01-01",
                    "period_end": "2025-03-31",
                    "amount": "100.00",
                }
            ]
        },
    )
    assert r.status_code == 201, r.text
    assert stale_reasons()["2025-01-01"] == "credit allocation changed"
    assert stale_reasons()["2025-04-01"] is None
    _ = world


def test_runs_queue_and_diff(world_setup: Any) -> None:
    c, world, t, _, _ = world_setup
    r1 = run(c)
    imp(
        c,
        "purchases",
        "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\nACME,I8,1,A,1,1000.00,02/01/2025\n",
        PURCHASE_COLS,
    )
    r2 = run(c)
    diff = c.get(f"/api/v1/runs/{r1['id']}/diff/{r2['id']}").json()
    assert (diff["from_run"], diff["to_run"]) == (r1["number"], r2["number"])
    changed = diff["results_changed"]
    assert len(changed) == 1 and (changed[0]["before"], changed[0]["after"]) == (
        "2000.0000",
        "2020.0000",
    )
    assert len(diff["batches_added"]) == 1
    history = c.get(
        f"/api/v1/results/{c.get('/api/v1/reconciliation').json()[0]['result_id']}/history"
    ).json()
    assert [h["expected"] for h in history] == ["2020.0000", "2000.0000"]

    # Two runs at once: the second queues behind the first (SPEC §9 case 44).
    from app.workers import jobs

    blocker = world.sql("SELECT job_id FROM rl.calculation_runs WHERE id = :r", r=r2["id"])[0][0]
    world.sql("UPDATE rl.jobs SET status = 'running' WHERE id = :j", j=blocker)
    r = c.post(
        "/api/v1/runs",
        json={"scope": {"type": "all"}, "period_start": "2025-01-01", "period_end": "2025-03-31"},
    )
    queued = c.get(f"/api/v1/runs/{r.json()['id']}").json()
    assert queued["status"] == "queued"
    assert c.get(f"/api/v1/jobs/{queued['job_id']}").json()["status"] == "queued"
    world.sql("UPDATE rl.jobs SET status = 'succeeded' WHERE id = :j", j=blocker)
    jobs.run_job(uuid.UUID(queued["job_id"]), t)  # what the broker's retry does
    assert c.get(f"/api/v1/runs/{queued['id']}").json()["status"] == "succeeded"


def test_split_allocation_and_unmatched_suggestions(world_setup: Any) -> None:
    """SPEC §9 case 31: one credit pays several quarters; remainder tracked; suggestions shown."""
    c, _, _, sid, aid = world_setup
    imp(
        c,
        "credits",
        "Vendor,Memo,Date,Amount,Program,Period\nACME,BULK,08/15/2025,2500.00,,\nACME,NEAR,04/25/2025,1999.50,,\n",
        CREDIT_COLS,
    )
    run(c)
    unmatched = {u["credit_reference"]: u for u in c.get("/api/v1/credits/unmatched").json()}
    assert set(unmatched) == {"BULK", "NEAR"}
    near = unmatched["NEAR"]["suggestions"]
    assert near and near[0]["period_start"] == "2025-01-01" and "within" in near[0]["explanation"]
    bulk = unmatched["BULK"]["id"]
    parts = [
        {
            "agreement_id": aid,
            "period_start": "2025-01-01",
            "period_end": "2025-03-31",
            "amount": "1500.00",
        },
        {
            "agreement_id": aid,
            "period_start": "2025-04-01",
            "period_end": "2025-06-30",
            "amount": "900.00",
        },
    ]
    r = c.post(f"/api/v1/credits/{bulk}/allocations", json={"parts": parts})
    assert r.status_code == 201 and r.json()["unallocated"] == "100.0000"
    too_much = c.post(
        f"/api/v1/credits/{bulk}/allocations", json={"parts": [{**parts[0], "amount": "100.01"}]}
    )
    assert too_much.json()["code"] == "ALLOCATION_EXCEEDS_CREDIT"
    wrong = c.post(
        f"/api/v1/credits/{bulk}/allocations",
        json={"parts": [{**parts[0], "period_start": "2025-02-01"}]},
    )
    assert wrong.json()["code"] == "PERIOD_NOT_CALCULATED"
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    assert rows["2025-04-01"]["status"] == "SHORT_PAID"
    alloc_id = r.json()["allocations"][1]["id"]
    assert c.delete(f"/api/v1/allocations/{alloc_id}").status_code == 200
    assert c.get(f"/api/v1/credits/{bulk}").json()["unallocated"] == "1000.0000"
    _ = sid


def test_due_date_boundary_in_tenant_timezone(
    world_setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC §9 case 36: PENDING through the due date (Q1 2025 + 30 days = Apr 30), MISSING after."""
    c, _, _, _, _ = world_setup
    run(c)
    monkeypatch.setattr("app.core.clock.today_in", lambda tz: date(2025, 4, 30))
    assert {r["period_start"]: r["status"] for r in c.get("/api/v1/reconciliation").json()}[
        "2025-01-01"
    ] == "PENDING"
    monkeypatch.setattr("app.core.clock.today_in", lambda tz: date(2025, 5, 1))
    assert {r["period_start"]: r["status"] for r in c.get("/api/v1/reconciliation").json()}[
        "2025-01-01"
    ] == "MISSING"


def test_write_off_four_eyes_and_over_recovery(
    app_client: TestClient, world: World, world_setup: Any
) -> None:
    c, _, t, _, _ = world_setup
    world.sql("UPDATE rl.tenants SET four_eyes_writeoff = true WHERE id = :t", t=t)
    run(c)
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    claim = c.post(
        "/api/v1/claims",
        json={"result_ids": [rows["2025-04-01"]["result_id"]], "claimed_amount": "900.00"},
    ).json()
    assert claim["code"] == "REASON_REQUIRED"
    claim = c.post(
        "/api/v1/claims",
        json={
            "result_ids": [rows["2025-04-01"]["result_id"]],
            "claimed_amount": "900.00",
            "claimed_amount_reason": "supplier dispute on one invoice",
        },
    ).json()
    r = c.post(f"/api/v1/claims/{claim['id']}/transition", json={"to": "written_off"})
    assert r.json()["code"] == "REASON_REQUIRED"
    r = c.post(
        f"/api/v1/claims/{claim['id']}/transition",
        json={"to": "written_off", "note": "supplier insolvent"},
    )
    assert r.json()["pending_write_off"] is True and r.json()["status"] == "draft"
    approval = c.get("/api/v1/approvals").json()[0]
    admin = world.member(t, "admin")
    ac = _client(app_client)
    login(ac, admin)
    assert (
        ac.post(
            f"/api/v1/approvals/{approval['id']}/decision", json={"decision": "approve"}
        ).status_code
        == 200
    )
    assert c.get(f"/api/v1/claims/{claim['id']}").json()["status"] == "written_off"

    # Recovered more than claimed (SPEC §9 case 37): allowed, overage noted.
    claim2 = c.post("/api/v1/claims", json={"result_ids": [rows["2025-01-01"]["result_id"]]}).json()
    c.post(f"/api/v1/claims/{claim2['id']}/transition", json={"to": "submitted"})
    detail = c.post(
        f"/api/v1/claims/{claim2['id']}/recoveries",
        json={
            "new_credit": {"reference": "OVER", "credit_date": "2025-08-01", "amount": "2100.00"}
        },
    ).json()
    assert detail["recovered_amount"] == "2100.0000"
    assert detail["events"][-1]["data"]["overage"] == "100.0000"
    assert (
        c.post(
            f"/api/v1/claims/{claim2['id']}/transition", json={"to": "resolved_recovered"}
        ).json()["status"]
        == "resolved_recovered"
    )


def test_needs_review_and_version_resolution(world_setup: Any) -> None:
    c, _, _, _, aid = world_setup
    v2 = c.post(
        f"/api/v1/agreements/{aid}/versions",
        json={
            **TERMS,
            "effective_from": "2025-02-15",
            "components": [{"key": "base", "type": "flat_percent", "rate": "0.03"}],
        },
    ).json()
    c.post(f"/api/v1/agreement-versions/{v2['id']}/activate", json={})
    run(c)
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    q1 = rows["2025-01-01"]
    assert q1["status"] == "NEEDS_REVIEW" and q1["expected"] is None
    assert c.get("/api/v1/dashboard").json()["needs_review"]["count"] == 1
    assert (
        c.post("/api/v1/claims", json={"result_ids": [q1["result_id"]]}).json()["code"]
        == "NOT_CLAIMABLE"
    )
    assert (
        c.put(
            "/api/v1/version-resolutions",
            json={
                "agreement_id": aid,
                "period_start": "2025-01-01",
                "period_end": "2025-03-31",
                "choice": "split",
            },
        ).status_code
        == 200
    )
    run(c)
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    # v1 Jan 1–Feb 14: 60,000 × 2% = 1,200; v2 Feb 15–Mar 31: 40,000 × 3% = 1,200
    assert (rows["2025-01-01"]["expected"], rows["2025-02-15"]["expected"]) == (
        "1200.00",
        "1200.00",
    )


def test_notifications_preferences_and_unsubscribe(
    world_setup: Any, outbox: list[RenderedEmail]
) -> None:
    c, _, _, _, _ = world_setup
    run(c)
    notes = c.get("/api/v1/notifications").json()
    assert notes["unread"] == 1 and notes["items"][0]["type"] == "run_finished"
    mail = next(e for e in outbox if e.subject.startswith("Run"))
    assert "unsubscribe" in mail.html
    token = re.search(r"unsubscribe\?token=([A-Za-z0-9_\-.]+)", mail.text)
    assert token
    anon = _client(c)
    assert anon.post("/api/v1/unsubscribe", json={"token": token.group(1)}).json() == {
        "unsubscribed_from": "Calculation run finished"
    }
    prefs = {p["type"]: p for p in c.get("/api/v1/notification-preferences").json()}
    assert prefs["run_finished"]["email"] is False and prefs["run_finished"]["in_app"] is True
    assert (
        anon.post("/api/v1/unsubscribe", json={"token": "x" * 20}).json()["code"] == "TOKEN_INVALID"
    )
    assert c.post("/api/v1/notifications/read", json={}).status_code == 200
    assert c.get("/api/v1/notifications").json()["unread"] == 0
    before = len(outbox)
    run(c)
    assert not any(
        e.subject.startswith("Run") for e in outbox[before:]
    )  # unsubscribed from run emails
    assert (
        c.put("/api/v1/notification-preferences", json={"type": "security", "email": False}).json()[
            "code"
        ]
        == "PREFERENCE_UNKNOWN"
    )


def test_tier_tracker_and_reminders(
    app_client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import tiers

    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    c = app_client
    sid = c.post("/api/v1/suppliers", json={"name": "Tiered", "codes": ["TIER"]}).json()["id"]
    terms = {
        **TERMS,
        "effective_from": "2025-01-01",
        "components": [
            {
                "key": "t",
                "type": "tiered_all_units",
                "tiers": [
                    {"threshold": "100000", "rate": "0.02"},
                    {"threshold": "200000", "rate": "0.03"},
                ],
            }
        ],
    }
    a = c.post(
        "/api/v1/agreements", json={"supplier_id": sid, "name": "Tiered", "terms": terms}
    ).json()
    c.post(f"/api/v1/agreement-versions/{a['versions'][0]['id']}/activate", json={})
    imp(
        c,
        "purchases",
        "Vendor,Invoice,Line,Item,Qty,Ext,Inv Date\nTIER,I1,1,A,1,150000.00,04/05/2025\n",
        PURCHASE_COLS,
    )
    monkeypatch.setattr(tiers, "today_in", lambda tz: date(2025, 5, 16))
    rows = c.get("/api/v1/tiers").json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["current_tier"], row["next_tier"], row["next_threshold"], row["gap"]) == (
        1,
        2,
        "200000",
        "50000.0000",
    )
    assert row["days_remaining"] == 45 and row["is_estimate"] is True
    assert row["potential_additional"] == "2000.00"  # (3% − 2%) × 200,000
    assert row["expected_to_date"] == "3000.00"


def test_claim_follow_up_and_aging_reminders(world_setup: Any) -> None:
    from app.db.session import tenant_session
    from app.workers.jobs import enqueue

    c, world, t, _, _ = world_setup
    run(c)
    rows = {r["period_start"]: r for r in c.get("/api/v1/reconciliation").json()}
    claim = c.post(
        "/api/v1/claims",
        json={"result_ids": [rows["2025-04-01"]["result_id"]], "follow_up_date": "2025-09-01"},
    ).json()
    c.post(f"/api/v1/claims/{claim['id']}/transition", json={"to": "submitted"})
    world.sql(
        "UPDATE rl.claims SET submitted_at = now() - interval '65 days' WHERE id = :c",
        c=claim["id"],
    )
    for _ in range(2):  # second run sends nothing new
        with tenant_session(t) as db:
            enqueue(db, tenant_id=t, job_type="claim_reminders")
    titles = sorted(
        n["title"]
        for n in c.get("/api/v1/notifications").json()["items"]
        if n["type"].startswith("claim")
    )
    assert titles == ["Claim CL-0001 is 60+ days old", "Follow up claim CL-0001"]
