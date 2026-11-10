"""Members, invites, settings, support access, audit chain."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.emails.service import RenderedEmail
from tests.api.conftest import PASSWORD, World, login, step_up


def _token(outbox: list[RenderedEmail], to: str) -> str:
    email = next(e for e in reversed(outbox) if e.to == to)
    m = re.search(r"token=([A-Za-z0-9_\-]+)", email.text)
    assert m
    return m.group(1)


def _client(app_client: TestClient) -> TestClient:
    return TestClient(
        app_client.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    )


def test_invite_new_user_and_accept(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    t = world.tenant("Acme")
    admin = world.member(t, "admin")
    login(app_client, admin)
    r = app_client.post(
        "/api/v1/org/invites", json={"email": "New.Person@Example.com", "role": "analyst"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "new.person@example.com"
    token = _token(outbox, "new.person@example.com")
    anon = _client(app_client)
    preview = anon.post("/api/v1/auth/invites/preview", json={"token": token}).json()
    assert preview == {
        "organization_name": "Acme",
        "email": "new.person@example.com",
        "role": "analyst",
        "has_account": False,
    }
    r = anon.post(
        "/api/v1/auth/invites/accept",
        json={"token": token, "name": "New Person", "password": "a long enough passphrase"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["organization"]["role"] == "analyst"
    assert (
        anon.post(
            "/api/v1/auth/invites/accept",
            json={"token": token, "name": "X", "password": "a long enough passphrase"},
        ).json()["code"]
        == "TOKEN_INVALID"
    )
    events = [e["action"] for e in app_client.get("/api/v1/org/audit-events").json()["items"]]
    assert {"invite.created", "invite.accepted"} <= set(events)


def test_invite_existing_account_adds_membership(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    """SPEC §9 case 41: no duplicate user; membership added after acceptance."""
    t1, t2 = world.tenant("One"), world.tenant("Two")
    existing = world.member(t1, "viewer")
    admin = world.member(t2, "admin")
    login(app_client, admin)
    assert (
        app_client.post(
            "/api/v1/org/invites", json={"email": existing.email, "role": "viewer"}
        ).status_code
        == 201
    )
    token = _token(outbox, existing.email)
    anon = _client(app_client)
    assert (
        anon.post("/api/v1/auth/invites/preview", json={"token": token}).json()["has_account"]
        is True
    )
    wrong = anon.post(
        "/api/v1/auth/invites/accept", json={"token": token, "password": "not the password"}
    )
    assert wrong.status_code == 401
    r = anon.post("/api/v1/auth/invites/accept", json={"token": token, "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert {o["name"] for o in r.json()["organizations"]} == {"One", "Two"}
    assert world.sql("SELECT count(*) FROM rl.users WHERE email = :e", e=existing.email)[0][0] == 1


def test_invite_rules(app_client: TestClient, world: World) -> None:
    t = world.tenant(allowed_invite_domains=["acme.com"])
    admin = world.member(t, "admin")
    member = world.member(t, "viewer", email="v@acme.com")
    login(app_client, admin)
    r = app_client.post("/api/v1/org/invites", json={"email": "x@gmail.com", "role": "viewer"})
    assert r.json()["code"] == "DOMAIN_NOT_ALLOWED"
    assert (
        app_client.post(
            "/api/v1/org/invites", json={"email": "o@acme.com", "role": "owner"}
        ).status_code
        == 403
    )
    assert (
        app_client.post(
            "/api/v1/org/invites", json={"email": member.email, "role": "viewer"}
        ).json()["code"]
        == "ALREADY_MEMBER"
    )
    inv = app_client.post(
        "/api/v1/org/invites", json={"email": "a@acme.com", "role": "viewer"}
    ).json()
    assert app_client.post(f"/api/v1/org/invites/{inv['id']}/resend").status_code == 200
    pending = app_client.get("/api/v1/org/invites").json()
    assert len(pending) == 1  # resend revoked the older invite
    assert app_client.delete(f"/api/v1/org/invites/{pending[0]['id']}").status_code == 200
    assert app_client.get("/api/v1/org/invites").json() == []


def test_last_owner_protection_and_owner_rules(app_client: TestClient, world: World) -> None:
    t = world.tenant()
    owner = world.member(t, "owner")
    admin = world.member(t, "admin")
    login(app_client, owner)
    step_up(app_client, owner)
    r = app_client.patch(f"/api/v1/org/members/{owner.membership_id}", json={"role": "admin"})
    assert r.json()["code"] == "LAST_OWNER"
    assert (
        app_client.post(f"/api/v1/org/members/{owner.membership_id}/deactivate").json()["code"]
        == "CANNOT_DEACTIVATE_SELF"
    )
    assert (
        app_client.patch(
            f"/api/v1/org/members/{admin.membership_id}", json={"role": "owner"}
        ).status_code
        == 200
    )
    # Now two owners, so demoting the first one works.
    assert (
        app_client.patch(
            f"/api/v1/org/members/{owner.membership_id}", json={"role": "admin"}
        ).status_code
        == 200
    )

    admin2 = world.member(t, "admin")
    other = _client(app_client)
    login(other, admin2)
    step_up(other, admin2)
    r = other.patch(f"/api/v1/org/members/{admin.membership_id}", json={"role": "viewer"})
    assert r.status_code == 403  # admin cannot demote an owner


def test_role_change_requires_step_up_and_revokes_sessions(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    t = world.tenant()
    owner = world.member(t, "owner")
    analyst = world.member(t, "analyst")
    analyst_client = _client(app_client)
    login(analyst_client, analyst)
    login(app_client, owner)
    r = app_client.patch(f"/api/v1/org/members/{analyst.membership_id}", json={"role": "viewer"})
    assert r.json()["code"] == "STEP_UP_REQUIRED"
    step_up(app_client, owner)
    assert (
        app_client.patch(
            f"/api/v1/org/members/{analyst.membership_id}", json={"role": "viewer"}
        ).status_code
        == 200
    )
    assert analyst_client.get("/api/v1/org").status_code == 401
    assert any(e.to == analyst.email and "role changed" in e.subject.lower() for e in outbox)


def test_member_removed_mid_session(app_client: TestClient, world: World) -> None:
    """SPEC §9 case 42: next request in that org is refused; other orgs unaffected."""
    t1, t2 = world.tenant("One"), world.tenant("Two")
    user = world.member(t1, "analyst")
    world.add_membership(t2, user.user_id, "viewer")
    login(app_client, user)
    assert app_client.get("/api/v1/org").json()["name"] == "One"
    world.sql(
        "UPDATE rl.memberships SET status = 'deactivated' WHERE id = :m", m=user.membership_id
    )
    r = app_client.get("/api/v1/org")
    assert (r.status_code, r.json()["code"]) == (403, "NO_MEMBERSHIP")
    r = app_client.post("/api/v1/auth/switch-organization", json={"organization_id": str(t2)})
    assert r.status_code == 200
    assert app_client.get("/api/v1/org").json()["name"] == "Two"
    assert (
        app_client.post(
            "/api/v1/auth/switch-organization", json={"organization_id": str(t1)}
        ).status_code
        == 404
    )


def test_deactivate_and_reactivate(app_client: TestClient, world: World) -> None:
    t = world.tenant()
    admin = world.member(t, "admin")
    viewer = world.member(t, "viewer")
    vc = _client(app_client)
    login(vc, viewer)
    login(app_client, admin)
    assert (
        app_client.post(f"/api/v1/org/members/{viewer.membership_id}/deactivate").status_code == 200
    )
    assert vc.get("/api/v1/org").status_code == 401
    vc.cookies.clear()
    assert (
        vc.post(
            "/api/v1/auth/login", json={"email": viewer.email, "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        app_client.post(f"/api/v1/org/members/{viewer.membership_id}/reactivate").status_code == 200
    )
    login(vc, viewer)
    statuses = {m["email"]: m["status"] for m in app_client.get("/api/v1/org/members").json()}
    assert statuses[viewer.email] == "active"


def test_support_access_grant_and_revoke(app_client: TestClient, world: World) -> None:
    t = world.tenant()
    admin = world.member(t, "admin")
    viewer = world.member(t, "viewer")
    login(app_client, admin)
    assert (
        app_client.post("/api/v1/org/support-access", json={"hours": 24}).json()["code"]
        == "STEP_UP_REQUIRED"
    )
    step_up(app_client, admin)
    assert app_client.post("/api/v1/org/support-access", json={"hours": 500}).status_code == 422
    g = app_client.post(
        "/api/v1/org/support-access",
        json={"hours": 24, "scope": "read_only", "reason": "Ticket 42"},
    )
    assert g.status_code == 201, g.text
    vc = _client(app_client)
    login(vc, viewer)
    assert len(vc.get("/api/v1/org/support-access").json()) == 1  # banner data for every member
    assert app_client.delete(f"/api/v1/org/support-access/{g.json()['id']}").status_code == 200
    assert vc.get("/api/v1/org/support-access").json() == []


def test_settings_update_and_audit_export(app_client: TestClient, world: World) -> None:
    t = world.tenant()
    admin = world.member(t, "admin")
    login(app_client, admin)
    etag = app_client.get("/api/v1/org").headers["ETag"]
    r = app_client.patch(
        "/api/v1/org/settings/profile", json={"timezone": "Mars/Base"}, headers={"If-Match": etag}
    )
    assert r.json()["code"] == "TIMEZONE_INVALID"
    r = app_client.patch(
        "/api/v1/org/settings/profile",
        json={"name": '=HYPERLINK("x")', "fiscal_year_start_month": 7},
        headers={"If-Match": etag},
    )
    assert r.status_code == 200, r.text
    r = app_client.patch(
        "/api/v1/org/settings/reconciliation",
        json={"pct_tolerance": "0.0100", "abs_tolerance": "-1"},
        headers={"If-Match": r.headers["ETag"]},
    )
    assert r.json()["code"] == "NEGATIVE_NOT_ALLOWED"
    csv = app_client.get("/api/v1/org/audit-events/export.csv")
    assert csv.headers["content-disposition"].startswith("attachment")
    assert "settings.profile.updated" in csv.text
    page = app_client.get("/api/v1/org/audit-events", params={"limit": 1}).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    nxt = app_client.get(
        "/api/v1/org/audit-events", params={"limit": 1, "cursor": page["next_cursor"]}
    ).json()
    assert nxt["items"][0]["seq"] < page["items"][0]["seq"]


def test_audit_chain_verifies_and_detects_tampering(app_client: TestClient, world: World) -> None:
    from app.db.session import tenant_session
    from app.services.audit import verify_chain

    t = world.tenant()
    admin = world.member(t, "admin")
    login(app_client, admin)
    for i in range(3):
        app_client.post(
            "/api/v1/org/invites", json={"email": f"p{i}@example.com", "role": "viewer"}
        )
    with tenant_session(t) as db:
        check = verify_chain(db, str(t))
    assert check.ok and check.events >= 4
    world.sql(
        'UPDATE rl.audit_events SET summary = \'{"role": "owner"}\' WHERE tenant_id = :t AND seq = 2',
        t=t,
    )
    with tenant_session(t) as db:
        check = verify_chain(db, str(t))
    assert not check.ok and check.first_bad_seq == 2
