"""Phase 8: invoices, ops console, support access, suspended read-only (PHASES §8)."""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.clock import utcnow
from app.db.models.billing import Invoice
from app.db.session import session_factory, set_platform_context
from app.services import billing
from app.services.audit import Actor
from tests.api.conftest import Member, World, login, step_up
from tests.api.test_workflow import _client

SELLER = {
    "seller": {
        "name": "Example Seller LLC",
        "address": "1 Test St, Testville",
        "email": "billing@seller.example",
    },
    "payment_instructions": "Bank transfer to account 000-TEST (placeholder for tests).",
}


def _ops(c: TestClient, world: World) -> tuple[TestClient, Member]:
    admin = world.platform_admin(f"ops-{uuid.uuid4().hex[:6]}@example.com")
    oc = _client(c)
    login(oc, admin)
    return oc, admin


def _configure(oc: TestClient) -> None:
    assert oc.put("/api/v1/ops/billing-settings", json=SELLER).status_code == 200


def _subscribe(world: World, t: uuid.UUID, status: str = "active") -> None:
    world.sql(
        "INSERT INTO rl.subscriptions (id, tenant_id, plan_id, status, limit_overrides, billing_contact_name, billing_contact_email, row_version) "
        "SELECT :i, :t, id, :s, '{}', 'Accounts Payable', 'ap@billed.example', 1 FROM rl.plans WHERE code = 'growth'",
        i=uuid.uuid7(),
        t=t,
        s=status,
    )


def _tenant_with_billing(world: World, name: str = "Billed Co") -> uuid.UUID:
    t = world.tenant(name)
    _subscribe(world, t)
    return t


def _draft(oc: TestClient, tenant_id: uuid.UUID, price: str = "499.00") -> dict[str, Any]:
    r = oc.post(
        "/api/v1/ops/invoices",
        json={
            "tenant_id": str(tenant_id),
            "lines": [
                {"description": "Growth plan — monthly", "quantity": "1", "unit_price": price}
            ],
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_invoice_numbers_never_collide_or_skip_under_concurrency(
    app_client: TestClient, world: World
) -> None:
    oc, admin = _ops(app_client, world)
    _configure(oc)
    tenants = [_tenant_with_billing(world, f"Co {i}") for i in range(3)]
    drafts = [_draft(oc, tenants[i % 3])["id"] for i in range(12)]
    year = utcnow().date().year
    world.sql("DELETE FROM rl.invoice_sequences WHERE year = :y", y=year)
    ctx = SimpleNamespace(
        actor=Actor("platform_admin", admin.user_id, admin.email),
        user=SimpleNamespace(id=admin.user_id),
    )
    barrier = threading.Barrier(len(drafts))
    errors: list[BaseException] = []

    def issue(invoice_id: str) -> None:
        try:
            with session_factory()() as db, db.begin():
                set_platform_context(db, True)
                inv = db.get(Invoice, uuid.UUID(invoice_id))
                assert inv is not None
                barrier.wait(timeout=30)
                billing.issue(db, ctx, inv)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=issue, args=(d,)) for d in drafts]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert not errors, errors
    numbers = sorted(
        r[0]
        for r in world.sql(
            "SELECT number FROM rl.invoices WHERE id = ANY(:ids)",
            ids=[uuid.UUID(d) for d in drafts],
        )
    )
    assert numbers == [f"RL-{year}-{n:04d}" for n in range(1, 13)]

    # A failed issue (rolled back) does not consume a number.
    late = _draft(oc, tenants[0])["id"]
    with session_factory()() as db, pytest.raises(RuntimeError), db.begin():
        set_platform_context(db, True)
        billing.next_number(db, year, "RL")
        raise RuntimeError("crash after numbering")
    assert oc.post(f"/api/v1/ops/invoices/{late}/issue").json()["number"] == f"RL-{year}-0013"


def test_invoice_lifecycle_and_immutability(app_client: TestClient, world: World) -> None:
    oc, _ = _ops(app_client, world)
    t = _tenant_with_billing(world)
    draft = _draft(oc, t)
    assert (
        oc.post(f"/api/v1/ops/invoices/{draft['id']}/issue").json()["code"]
        == "BILLING_NOT_CONFIGURED"
    )
    _configure(oc)
    inv = oc.post(f"/api/v1/ops/invoices/{draft['id']}/issue").json()
    assert (
        inv["status"] == "issued" and inv["total"] == "499.0000" and inv["number"].startswith("RL-")
    )
    assert inv["seller"]["name"] == "Example Seller LLC"
    assert oc.get(f"/api/v1/ops/invoices/{inv['id']}/pdf").content.startswith(b"%PDF")
    # Issued invoices cannot be edited through the API or directly in the database.
    body = {
        "tenant_id": str(t),
        "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}],
    }
    assert (
        oc.put(f"/api/v1/ops/invoices/{inv['id']}", json=body).json()["code"] == "INVOICE_NOT_DRAFT"
    )
    with pytest.raises(DBAPIError, match="immutable"), session_factory()() as db, db.begin():
        set_platform_context(db, True)
        db.execute(text("UPDATE rl.invoices SET total = 1 WHERE id = :i"), {"i": inv["id"]})
    with pytest.raises(DBAPIError, match="immutable"), session_factory()() as db, db.begin():
        set_platform_context(db, True)
        db.execute(
            text("UPDATE rl.invoice_lines SET amount = 1 WHERE invoice_id = :i"),
            {"i": inv["id"]},
        )

    # Tenant owners see issued invoices (never drafts) and download the PDF; other tenants cannot.
    owner = world.member(t, "owner")
    tc = _client(app_client)
    login(tc, owner)
    _draft(oc, t)  # another draft stays invisible
    listed = tc.get("/api/v1/billing/invoices").json()
    assert [i["number"] for i in listed] == [inv["number"]]
    assert tc.get(f"/api/v1/billing/invoices/{inv['id']}/pdf").content.startswith(b"%PDF")
    analyst = world.member(t, "analyst")
    ac = _client(app_client)
    login(ac, analyst)
    assert ac.get("/api/v1/billing/invoices").status_code == 403

    # Void + reissue; mark paid; paid invoices cannot be voided.
    assert (
        oc.post(
            f"/api/v1/ops/invoices/{inv['id']}/void", json={"reason": "wrong amount"}
        ).status_code
        == 200
    )
    new = oc.post(f"/api/v1/ops/invoices/{inv['id']}/reissue").json()
    assert (
        new["status"] == "draft" and new["replaces_id"] == inv["id"] and new["total"] == "499.0000"
    )
    issued = oc.post(f"/api/v1/ops/invoices/{new['id']}/issue").json()
    paid = oc.post(
        f"/api/v1/ops/invoices/{issued['id']}/paid",
        json={"paid_on": utcnow().date().isoformat(), "reference": "WIRE-123"},
    ).json()
    assert paid["status"] == "paid"
    assert (
        oc.post(f"/api/v1/ops/invoices/{issued['id']}/void", json={"reason": "late"}).json()["code"]
        == "INVOICE_NOT_ISSUED"
    )
    tenant_log = world.sql(
        "SELECT action FROM rl.audit_events WHERE tenant_id = :t AND action LIKE 'invoice.%'", t=t
    )
    assert ("invoice.issued",) in [tuple(r) for r in tenant_log]


def test_lapse_marks_past_due_and_payment_clears_it(app_client: TestClient, world: World) -> None:
    oc, _ = _ops(app_client, world)
    _configure(oc)
    t = _tenant_with_billing(world)
    inv = oc.post(f"/api/v1/ops/invoices/{_draft(oc, t)['id']}/issue").json()
    world.sql("ALTER TABLE rl.invoices DISABLE TRIGGER guard_invoice")
    world.sql(
        "UPDATE rl.invoices SET due_date = :d WHERE id = :i",
        d=utcnow().date() - timedelta(days=3),
        i=inv["id"],
    )
    world.sql("ALTER TABLE rl.invoices ENABLE TRIGGER guard_invoice")
    from app.workers.jobs import JobContext

    with session_factory()() as db, db.begin():
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)})
        result = billing._lapse(db, JobContext(uuid.uuid7(), t, {}, None))
    assert result is not None and result["overdue"] == 1 and result["reminders"] == 1
    assert (
        world.sql("SELECT status FROM rl.subscriptions WHERE tenant_id = :t", t=t)[0][0]
        == "past_due"
    )
    oc.post(
        f"/api/v1/ops/invoices/{inv['id']}/paid",
        json={"paid_on": utcnow().date().isoformat(), "reference": "ACH-9"},
    )
    assert (
        world.sql("SELECT status FROM rl.subscriptions WHERE tenant_id = :t", t=t)[0][0] == "active"
    )


def test_suspended_tenant_is_read_only_but_can_export(app_client: TestClient, world: World) -> None:
    oc, _ = _ops(app_client, world)
    t = world.tenant()
    _subscribe(world, t)
    analyst = world.member(t, "analyst")
    c = _client(app_client)
    login(c, analyst)
    sid = c.post("/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME"]}).json()["id"]
    assert (
        oc.patch(f"/api/v1/ops/tenants/{t}/subscription", json={"status": "suspended"}).json()[
            "status"
        ]
        == "suspended"
    )
    # Every member's session knows, so the UI can show the read-only banner.
    assert c.get("/api/v1/auth/session").json()["organization"]["billing_status"] == "suspended"

    assert (
        c.post("/api/v1/suppliers", json={"name": "Other", "codes": ["OTH"]}).json()["code"]
        == "TENANT_READ_ONLY"
    )
    assert (
        c.patch(f"/api/v1/suppliers/{sid}", json={"name": "X"}, headers={"If-Match": '"1"'}).json()[
            "code"
        ]
        == "TENANT_READ_ONLY"
    )
    r = c.post(
        "/api/v1/runs",
        json={"scope": {"type": "all"}, "period_start": "2025-01-01", "period_end": "2025-03-31"},
    )
    assert r.json()["code"] == "TENANT_READ_ONLY"
    assert c.get("/api/v1/suppliers").status_code == 200
    r = c.post(
        "/api/v1/exports",
        json={"report": "agreement_register", "format": "csv"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert (
        r.status_code == 202
        and c.get(f"/api/v1/exports/{r.json()['id']}").json()["status"] == "succeeded"
    )
    oc.patch(f"/api/v1/ops/tenants/{t}/subscription", json={"status": "active"})
    assert c.post("/api/v1/suppliers", json={"name": "Other", "codes": ["OTH"]}).status_code == 201


def test_platform_admin_needs_an_active_grant_for_business_data(
    app_client: TestClient, world: World
) -> None:
    t = world.tenant()
    owner = world.member(t, "owner")
    tc = _client(app_client)
    login(tc, owner)
    tc.post("/api/v1/suppliers", json={"name": "Secret Supplier", "codes": ["SEC"]})
    oc, _ = _ops(app_client, world)

    # Console shows metadata and aggregate usage only.
    detail = oc.get(f"/api/v1/ops/tenants/{t}").json()
    assert detail["members"] == 1 and "Secret Supplier" not in str(detail)
    # Business routes and direct reads are refused without a grant.
    assert oc.get("/api/v1/suppliers").status_code in (403, 404)
    assert (
        oc.post("/api/v1/ops/support/enter", json={"tenant_id": str(t)}).json()["code"]
        == "SUPPORT_ACCESS_REQUIRED"
    )
    with session_factory()() as db, db.begin():
        set_platform_context(db, True)
        assert (
            db.execute(text("SELECT count(*) FROM rl.suppliers")).scalar() == 0
        )  # RLS: no platform policy
        assert db.execute(text("SELECT count(*) FROM rl.purchase_lines")).scalar() == 0

    # With a read-only grant: read allowed, writes refused, every request audited.
    step_up(tc, owner)
    grant = tc.post(
        "/api/v1/org/support-access", json={"hours": 2, "scope": "read_only", "reason": "help"}
    )
    assert grant.status_code == 201, grant.text
    assert oc.post("/api/v1/ops/support/enter", json={"tenant_id": str(t)}).status_code == 200
    assert [s["name"] for s in oc.get("/api/v1/suppliers").json()["items"]] == ["Secret Supplier"]
    assert oc.post("/api/v1/suppliers", json={"name": "Nope", "codes": ["NO"]}).status_code == 403
    actions = [
        r[0] for r in world.sql("SELECT action FROM rl.audit_events WHERE tenant_id = :t", t=t)
    ]
    assert "support.entered" in actions and "support.request" in actions

    # Revoking ends access immediately: the operator's session is detached from the tenant.
    tc.delete(f"/api/v1/org/support-access/{grant.json()['id']}")
    r = oc.get("/api/v1/suppliers")
    assert r.status_code == 403 and r.json()["code"] == "NO_ORGANIZATION"
    assert (
        oc.post("/api/v1/ops/support/enter", json={"tenant_id": str(t)}).json()["code"]
        == "SUPPORT_ACCESS_REQUIRED"
    )


def test_ops_console_tenants_flags_pilots_announcements_jobs(
    app_client: TestClient, world: World
) -> None:
    oc, _ = _ops(app_client, world)
    r = oc.post(
        "/api/v1/ops/tenants",
        json={
            "name": "New Distributor",
            "plan_code": "growth",
            "owner_email": "first.owner@newdist.example",
        },
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["plan"] == "Growth" and r.json()["status"] == "pilot"
    assert world.sql("SELECT email, role FROM rl.invites WHERE tenant_id = :t", t=tid)[0] == (
        "first.owner@newdist.example",
        "owner",
    )
    assert any(t["id"] == tid for t in oc.get("/api/v1/ops/tenants").json())

    assert (
        oc.put(
            f"/api/v1/ops/tenants/{tid}/flags", json={"key": "beta_reports", "enabled": True}
        ).status_code
        == 200
    )
    assert oc.get(f"/api/v1/ops/tenants/{tid}").json()["flags"]["beta_reports"] is True
    assert (
        oc.put(f"/api/v1/ops/tenants/{tid}/flags", json={"key": "nope", "enabled": True}).json()[
            "code"
        ]
        == "FLAG_UNKNOWN"
    )

    anon = _client(app_client)
    assert (
        anon.post(
            "/api/v1/pilot-requests",
            json={
                "name": "Pat",
                "email": "pat@dist.example",
                "company": "Dist Co",
                "consent": True,
            },
        ).status_code
        == 202
    )
    assert (
        anon.post(
            "/api/v1/pilot-requests",
            json={
                "name": "Bot",
                "email": "b@x.example",
                "company": "X",
                "website": "spam",
                "consent": True,
            },
        ).status_code
        == 202
    )
    inbox = oc.get("/api/v1/ops/pilot-requests").json()
    assert [p["company"] for p in inbox if p["email"] in ("pat@dist.example", "b@x.example")] == [
        "Dist Co"
    ]
    assert (
        oc.patch(
            f"/api/v1/ops/pilot-requests/{inbox[0]['id']}", json={"status": "contacted"}
        ).json()["status"]
        == "contacted"
    )

    a = oc.post(
        "/api/v1/ops/announcements",
        json={"message": "Maintenance Sunday 02:00 UTC", "level": "warning"},
    ).json()
    member = world.member(world.tenant(), "viewer")
    mc = _client(app_client)
    login(mc, member)
    assert any(x["id"] == a["id"] for x in mc.get("/api/v1/announcements").json())
    assert mc.get("/api/v1/ops/tenants").status_code == 404  # hidden from tenant users

    jobs = oc.get("/api/v1/ops/jobs").json()
    assert set(jobs["counts"]) >= {"queued", "running", "dead"}
    assert any(e["action"] == "ops.tenant_created" for e in oc.get("/api/v1/ops/audit").json())


def test_pilot_request_reaches_inbox_and_sends_both_emails(
    app_client: TestClient, world: World, outbox: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ops_notify_email", "ops-inbox@rebateledger.invalid")
    anon = _client(app_client)
    body = {
        "name": "Riley",
        "email": f"riley-{uuid.uuid4().hex[:6]}@distributor.example",
        "company": "Riley Wholesale",
        "role": "Controller",
        "segment": "Electrical",
        "erp_system": "Epicor Eclipse",
        "supplier_count": "20-50",
        "message": "We have ~30 programs.",
        "consent": True,
    }
    missing_consent = {k: v for k, v in body.items() if k != "consent"}
    assert anon.post("/api/v1/pilot-requests", json=missing_consent).status_code == 422
    assert anon.post("/api/v1/pilot-requests", json={**body, "consent": False}).status_code == 422
    assert anon.post("/api/v1/pilot-requests", json=body).status_code == 202

    to_requester = [e for e in outbox if e.to == body["email"]]
    to_ops = [e for e in outbox if e.to == "ops-inbox@rebateledger.invalid"]
    assert len(to_requester) == 1 and "received your" in to_requester[0].subject
    assert body["message"] not in to_requester[0].text  # nothing reflected back
    assert (
        len(to_ops) == 1
        and "Riley Wholesale" in to_ops[0].subject
        and "/ops/requests" in to_ops[0].text
    )

    oc, _ = _ops(app_client, world)
    stored = next(
        p for p in oc.get("/api/v1/ops/pilot-requests").json() if p["email"] == body["email"]
    )
    assert (stored["segment"], stored["erp_system"], stored["status"]) == (
        "Electrical",
        "Epicor Eclipse",
        "new",
    )
    # Per-email limit: 3 per day.
    for _ in range(2):
        anon.post("/api/v1/pilot-requests", json=body)
    assert anon.post("/api/v1/pilot-requests", json=body).status_code == 429


def test_public_plans_lists_only_public_plans(app_client: TestClient) -> None:
    anon = _client(app_client)
    plans = anon.get("/api/v1/public/plans").json()
    assert plans and all(
        set(p)
        == {
            "code",
            "name",
            "monthly_price",
            "max_active_agreements",
            "max_users",
            "max_import_rows_per_month",
        }
        for p in plans
    )
