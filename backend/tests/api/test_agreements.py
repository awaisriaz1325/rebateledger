"""Suppliers and agreements (PHASES §3 acceptance: immutability, four-eyes)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from tests.api.conftest import World, login, step_up
from tests.api.factories import TERMS


def _client(c: TestClient) -> TestClient:
    return TestClient(
        c.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    )


def tiered_terms() -> dict[str, Any]:
    t = copy.deepcopy(TERMS)
    t["components"] = [
        {
            "key": "volume",
            "type": "tiered_all_units",
            "tiers": [
                {"threshold": "250000", "rate": "0.02"},
                {"threshold": "500000", "rate": "0.03"},
            ],
        }
    ]
    t["eligibility"] = [
        {"key": "no-spa", "action": "exclude", "field": "flag", "flag": "special_pricing"}
    ]
    return t


@pytest.fixture
def setup(app_client: TestClient, world: World) -> tuple[TestClient, World, uuid.UUID, str]:
    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    sid = app_client.post(
        "/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME", "acme-2"]}
    ).json()["id"]
    return app_client, world, t, sid


def create(
    c: TestClient, sid: str, terms: dict[str, Any] | None = None, ref: str | None = "ACME-VOL"
) -> dict[str, Any]:
    r = c.post(
        "/api/v1/agreements",
        json={
            "supplier_id": sid,
            "name": "Volume",
            "external_reference": ref,
            "terms": terms or tiered_terms(),
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_supplier_codes_unique_and_detail(setup: Any) -> None:
    c, _, _, sid = setup
    assert (
        c.post("/api/v1/suppliers", json={"name": "Other", "codes": ["Acme"]}).json()["code"]
        == "CODE_IN_USE"
    )
    detail = c.get(f"/api/v1/suppliers/{sid}")
    assert (
        detail.json()["codes"] == ["ACME", "ACME-2"]
        and detail.json()["latest_purchase_date"] is None
    )
    r = c.patch(
        f"/api/v1/suppliers/{sid}",
        json={"codes": ["ACME"]},
        headers={"If-Match": detail.headers["ETag"]},
    )
    assert r.status_code == 200 and r.json()["codes"] == ["ACME"]
    assert (
        c.patch(
            f"/api/v1/suppliers/{sid}",
            json={"name": "x"},
            headers={"If-Match": detail.headers["ETag"]},
        ).status_code
        == 412
    )
    assert c.get("/api/v1/suppliers", params={"q": "acm"}).json()["items"][0]["id"] == sid


def test_summary_and_warnings(setup: Any) -> None:
    c, _, _, sid = setup
    terms = tiered_terms()
    terms["components"][0]["tiers"] = [
        {"threshold": "250000", "rate": "0.03"},
        {"threshold": "500000", "rate": "0.02"},
    ]
    a = create(c, sid, terms)
    v = a["versions"][0]
    assert v["warnings"] == ["Component volume: tier rates decrease as tiers rise."]
    assert v["summary"].startswith(
        "Pays 3.00% once quarterly eligible spend is at least $250,000.00; 2.00% once"
    )
    assert "Applies the reached tier to all eligible volume (all-units)." in v["summary"]
    assert "Excludes special pricing lines." in v["summary"]
    assert v["terms"]["components"][0]["tiers"][0]["rate"] == "0.03"


def test_invalid_terms_rejected(setup: Any) -> None:
    c, _, _, sid = setup
    bad = tiered_terms()
    bad["components"][0]["tiers"] = [
        {"threshold": "500", "rate": "0.02"},
        {"threshold": "100", "rate": "0.03"},
    ]
    r = c.post("/api/v1/agreements", json={"supplier_id": sid, "name": "X", "terms": bad})
    assert (r.status_code, r.json()["code"]) == (422, "TERMS_INVALID")
    float_rate = tiered_terms()
    float_rate["components"][0]["tiers"][0]["rate"] = 0.02
    assert (
        c.post(
            "/api/v1/agreements", json={"supplier_id": sid, "name": "X", "terms": float_rate}
        ).status_code
        == 422
    )
    missing = tiered_terms()
    del missing["threshold_comparison"]
    assert (
        c.post(
            "/api/v1/agreements", json={"supplier_id": sid, "name": "X", "terms": missing}
        ).status_code
        == 422
    )


def test_active_version_is_immutable_everywhere(setup: Any) -> None:
    c, world, t, sid = setup
    a = create(c, sid)
    vid = a["versions"][0]["id"]
    etag = c.get(f"/api/v1/agreement-versions/{vid}").headers["ETag"]
    assert (
        c.put(
            f"/api/v1/agreement-versions/{vid}", json=tiered_terms(), headers={"If-Match": etag}
        ).status_code
        == 200
    )
    r = c.post(f"/api/v1/agreement-versions/{vid}/activate", json={})
    assert r.status_code == 200 and r.json()["status"] == "active"
    etag = c.get(f"/api/v1/agreement-versions/{vid}").headers["ETag"]
    r = c.put(f"/api/v1/agreement-versions/{vid}", json=tiered_terms(), headers={"If-Match": etag})
    assert (r.status_code, r.json()["code"]) == (409, "VERSION_NOT_EDITABLE")
    assert c.delete(f"/api/v1/agreement-versions/{vid}").json()["code"] == "VERSION_NOT_EDITABLE"
    assert (
        c.post(f"/api/v1/agreement-versions/{vid}/activate", json={}).json()["code"]
        == "VERSION_NOT_DRAFT"
    )

    # Defence in depth: even direct SQL as the application role cannot change active terms.
    engine = create_engine(get_settings().database_url.get_secret_value())
    try:
        for stmt in (
            "UPDATE rl.agreement_versions SET payment_terms_days = 1 WHERE id = :v",
            "UPDATE rl.agreement_components SET rate = 0.5 WHERE version_id = :v",
            "DELETE FROM rl.eligibility_rules WHERE version_id = :v",
            "DELETE FROM rl.agreement_versions WHERE id = :v",
            "UPDATE rl.agreement_versions SET status = 'draft' WHERE id = :v",
        ):
            with pytest.raises(DBAPIError, match=r"immutable|cannot|draft"), engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)})
                conn.execute(text(stmt), {"v": vid})
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)})
            tier_ids = (
                conn.execute(
                    text(
                        "SELECT t.id FROM rl.agreement_tiers t JOIN rl.agreement_components c ON c.id = t.component_id WHERE c.version_id = :v"
                    ),
                    {"v": vid},
                )
                .scalars()
                .all()
            )
        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)})
            conn.execute(
                text("UPDATE rl.agreement_tiers SET rate = 0.9 WHERE id = :i"), {"i": tier_ids[0]}
            )
    finally:
        engine.dispose()
    _ = world


def test_new_version_supersedes_and_overlap_rules(setup: Any) -> None:
    c, _, _, sid = setup
    a = create(c, sid)
    aid, v1 = a["id"], a["versions"][0]["id"]
    c.post(f"/api/v1/agreement-versions/{v1}/activate", json={})
    t2 = tiered_terms()
    t2["effective_from"] = "2026-07-01"
    v2 = c.post(f"/api/v1/agreements/{aid}/versions", json=t2)
    assert v2.status_code == 201 and v2.json()["version_no"] == 2
    assert c.post(f"/api/v1/agreements/{aid}/versions", json=t2).json()["code"] == "DRAFT_EXISTS"
    assert (
        c.post(f"/api/v1/agreement-versions/{v2.json()['id']}/activate", json={}).json()["status"]
        == "active"
    )
    versions = {v["version_no"]: v for v in c.get(f"/api/v1/agreements/{aid}").json()["versions"]}
    assert versions[1]["status"] == "superseded" and versions[1]["effective_to"] == "2026-06-30"
    t3 = tiered_terms()
    t3["effective_from"] = "2026-03-01"  # inside superseded v1's range
    v3 = c.post(f"/api/v1/agreements/{aid}/versions", json=t3).json()
    assert (
        c.post(f"/api/v1/agreement-versions/{v3['id']}/activate", json={}).json()["code"]
        == "VERSION_OVERLAP"
    )
    assert c.delete(f"/api/v1/agreement-versions/{v3['id']}").status_code == 200


def test_four_eyes_self_approval_impossible_even_after_role_change(
    app_client: TestClient, world: World
) -> None:
    t = world.tenant(four_eyes_activation=True)
    analyst = world.member(t, "analyst")
    admin = world.member(t, "admin")
    login(app_client, analyst)
    sid = app_client.post("/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME"]}).json()[
        "id"
    ]
    a = create(app_client, sid)
    vid = a["versions"][0]["id"]
    r = app_client.post(
        f"/api/v1/agreement-versions/{vid}/activate", json={"note": "please approve"}
    )
    assert r.json()["status"] == "pending_approval"
    approval = app_client.get("/api/v1/approvals").json()[0]
    assert (
        app_client.post(
            f"/api/v1/approvals/{approval['id']}/decision", json={"decision": "approve"}
        ).status_code
        == 403
    )  # analyst lacks APPROVE

    # Promote the requester to Admin mid-flow: still cannot approve their own request.
    owner = world.member(t, "owner")
    oc = _client(app_client)
    login(oc, owner)
    step_up(oc, owner)
    assert (
        oc.patch(f"/api/v1/org/members/{analyst.membership_id}", json={"role": "admin"}).status_code
        == 200
    )
    analyst.totp_secret = None
    world.sql("DELETE FROM rl.mfa_factors WHERE user_id = :u", u=analyst.user_id)
    from app.core.security import encrypt_secret, new_totp_secret

    analyst.totp_secret = new_totp_secret()
    world.sql(
        "INSERT INTO rl.mfa_factors (id, user_id, secret_encrypted, confirmed_at) VALUES (:i, :u, :s, now())",
        i=uuid.uuid7(),
        u=analyst.user_id,
        s=encrypt_secret(analyst.totp_secret),
    )
    login(app_client, analyst)
    r = app_client.post(
        f"/api/v1/approvals/{approval['id']}/decision", json={"decision": "approve"}
    )
    assert (r.status_code, r.json()["code"]) == (403, "SELF_APPROVAL")
    # The database refuses it too.
    with pytest.raises(DBAPIError, match="no_self_approval"):
        world.sql(
            "UPDATE rl.approvals SET decided_by = requested_by WHERE id = :a", a=approval["id"]
        )

    ac = _client(app_client)
    login(ac, admin)
    r = ac.post(f"/api/v1/approvals/{approval['id']}/decision", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert ac.get(f"/api/v1/agreement-versions/{vid}").json()["status"] == "active"
    assert (
        ac.post(f"/api/v1/approvals/{approval['id']}/decision", json={"decision": "reject"}).json()[
            "code"
        ]
        == "APPROVAL_DECIDED"
    )


def test_reject_returns_to_draft(app_client: TestClient, world: World) -> None:
    t = world.tenant(four_eyes_activation=True)
    analyst, admin = world.member(t, "analyst"), world.member(t, "admin")
    login(app_client, analyst)
    sid = app_client.post("/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME"]}).json()[
        "id"
    ]
    agreement = create(app_client, sid)
    vid = agreement["versions"][0]["id"]
    app_client.post(f"/api/v1/agreement-versions/{vid}/activate", json={})
    ac = _client(app_client)
    login(ac, admin)
    ap = ac.get("/api/v1/approvals").json()[0]
    # The queue names what is being approved and links to it (no client-side id lookups).
    assert ap["label"] == "Activate Volume v1 (Acme)"
    assert ap["link"] == f"/app/agreements/{agreement['id']}"
    assert ap["decided_at"] is None
    assert (
        ac.post(
            f"/api/v1/approvals/{ap['id']}/decision",
            json={"decision": "reject", "note": "fix tiers"},
        ).status_code
        == 200
    )
    assert app_client.get(f"/api/v1/agreement-versions/{vid}").json()["status"] == "draft"


def test_preview_uses_imported_data(setup: Any) -> None:
    c, world, t, sid = setup
    bid = uuid.uuid7()
    world.sql(
        "INSERT INTO rl.import_batches (id, tenant_id, import_type, status, filename, file_format, size_bytes, file_hash, storage_key, config, stats, void_reason, row_version) VALUES (:b, :t, 'purchases', 'committed', 'x', 'csv', 1, 'h', 'k', '{}', '{}', '', 1)",
        b=bid,
        t=t,
    )
    for i, (amount, spa) in enumerate([("300000", False), ("250000", False), ("40000", True)]):
        world.sql(
            "INSERT INTO rl.purchase_lines (tenant_id, batch_id, source_row, supplier_id, dedupe_key, invoice_number, sku, description, quantity, amount, invoice_date, flags, is_return, voided) "
            "VALUES (:t, :b, :r, :s, :k, 'I', 'A', '', 1, :a, '2026-02-01', CAST(:f AS jsonb), false, false)",
            t=t,
            b=bid,
            r=i,
            s=sid,
            k=uuid.uuid4().bytes * 2,
            a=amount,
            f=f'{{"special_pricing": {str(spa).lower()}}}',
        )
    vid = create(c, sid)["versions"][0]["id"]
    r = c.post(
        f"/api/v1/agreement-versions/{vid}/preview", json={"period_containing": "2026-02-15"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 550,000 eligible (SPA line excluded) ≥ 500,000 → 3% all-units = 16,500.00
    assert (body["expected"], body["spend"], body["tier_reached"]) == ("16500.00", "550000.0000", 2)
    assert body["excluded_counts"] == {"EXCLUDED_BY_RULE": 1}
    assert [s["step"] for s in body["trace"]] == list(range(1, 11))
    assert (
        c.post(
            f"/api/v1/agreement-versions/{vid}/preview", json={"period_containing": "2025-02-15"}
        ).json()["code"]
        == "PERIOD_INVALID"
    )


def test_plan_limit_blocks_only_new_activation(setup: Any) -> None:
    c, world, t, sid = setup
    plan = world.sql("SELECT id FROM rl.plans WHERE code = 'lite'")[0][0]
    world.sql(
        "INSERT INTO rl.subscriptions (id, tenant_id, plan_id, status, limit_overrides, billing_contact_name, billing_contact_email, row_version) VALUES (:i, :t, :p, 'active', '{\"max_active_agreements\": 1}', '', '', 1)",
        i=uuid.uuid7(),
        t=t,
        p=plan,
    )
    v1 = create(c, sid)["versions"][0]["id"]
    assert c.post(f"/api/v1/agreement-versions/{v1}/activate", json={}).status_code == 200
    v2 = create(c, sid, ref="OTHER")["versions"][0]["id"]
    r = c.post(f"/api/v1/agreement-versions/{v2}/activate", json={})
    assert (r.status_code, r.json()["code"]) == (403, "PLAN_LIMIT_REACHED")
    assert (
        c.get(f"/api/v1/agreement-versions/{v1}").json()["status"] == "active"
    )  # existing untouched


def test_merge_suppliers(setup: Any) -> None:
    c, _, _, sid = setup
    other = c.post("/api/v1/suppliers", json={"name": "Acme Dup", "codes": ["ACME-OLD"]}).json()[
        "id"
    ]
    a1 = create(c, sid)
    a2 = create(c, other, ref="DUP")
    for a in (a1, a2):
        c.post(f"/api/v1/agreement-versions/{a['versions'][0]['id']}/activate", json={})
    r = c.post("/api/v1/suppliers/merge", json={"source_id": other, "target_id": sid})
    assert r.json()["code"] == "MERGE_OVERLAPPING_AGREEMENTS"
    c.post(f"/api/v1/agreements/{a2['id']}/archive")
    r = c.post("/api/v1/suppliers/merge", json={"source_id": other, "target_id": sid})
    assert r.status_code == 200 and "ACME-OLD" in r.json()["codes"]
    assert c.get(f"/api/v1/suppliers/{other}").status_code == 404
    assert c.get(f"/api/v1/agreements/{a2['id']}").json()["supplier_id"] == sid


def test_terms_check_returns_live_summary(setup: Any) -> None:
    c, _, _, _ = setup
    r = c.post("/api/v1/agreement-terms/check", json=tiered_terms())
    assert r.status_code == 200 and r.json()["valid"] is True
    assert r.json()["summary"].startswith("Pays 2.00% once quarterly")
    bad = tiered_terms()
    bad["components"][0]["tiers"] = [
        {"threshold": "500", "rate": "0.02"},
        {"threshold": "100", "rate": "0.03"},
    ]
    out = c.post("/api/v1/agreement-terms/check", json=bad).json()
    assert out["valid"] is False and "ascending" in out["error"]
