"""Authentication flows and security properties (PHASES §2 acceptance)."""

from __future__ import annotations

import re
import time
from typing import Any

import pyotp
from fastapi.testclient import TestClient

from app.emails.service import RenderedEmail
from tests.api.conftest import PASSWORD, World, login, step_up


def _link_token(email: RenderedEmail) -> str:
    m = re.search(r"token=([A-Za-z0-9_\-]+)", email.text)
    assert m, email.text
    return m.group(1)


def test_login_logout_and_session_info(app_client: TestClient, world: World) -> None:
    t = world.tenant()
    analyst = world.member(t, "analyst")
    info = login(app_client, analyst)
    assert info["organization"]["role"] == "analyst"
    assert "run_reconciliation" in info["organization"]["permissions"]
    assert app_client.get("/api/v1/me").status_code == 200
    assert app_client.post("/api/v1/auth/logout").status_code == 200
    assert app_client.get("/api/v1/me").status_code == 401


def test_cookie_attributes(app_client: TestClient, world: World) -> None:
    m = world.member(world.tenant(), "viewer")
    r = app_client.post("/api/v1/auth/login", json={"email": m.email, "password": PASSWORD})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-rl_session=")
    for attr in ("HttpOnly", "Secure", "Path=/", "SameSite=lax"):
        assert attr.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()


def test_no_user_enumeration(app_client: TestClient, world: World) -> None:
    m = world.member(world.tenant(), "viewer")
    timings: dict[str, float] = {}
    bodies: dict[str, Any] = {}
    for label, email in (("wrong_password", m.email), ("unknown", "nobody@example.com")):
        start = time.perf_counter()
        r = app_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password-123"}
        )
        timings[label] = time.perf_counter() - start
        assert r.status_code == 401
        body = r.json()
        bodies[label] = (body["code"], body["detail"])
    assert bodies["wrong_password"] == bodies["unknown"]
    # Both paths run one argon2 verification; allow generous noise.
    ratio = timings["wrong_password"] / timings["unknown"]
    assert 0.33 < ratio < 3.0, timings

    r1 = app_client.post("/api/v1/auth/password/forgot", json={"email": m.email})
    r2 = app_client.post("/api/v1/auth/password/forgot", json={"email": "nobody@example.com"})
    assert (r1.status_code, r1.json()) == (r2.status_code, r2.json()) == (202, {"ok": True})


def test_lockout_after_ten_failures(app_client: TestClient, world: World) -> None:
    m = world.member(world.tenant(), "viewer")
    for _ in range(10):
        world.sql("DELETE FROM rl.users WHERE false")  # no-op; keep loop explicit
        from app.core import ratelimit

        ratelimit.client().flushdb()  # isolate the DB lockout from the Redis progressive delay
        r = app_client.post(
            "/api/v1/auth/login", json={"email": m.email, "password": "wrong-password-123"}
        )
        assert r.status_code == 401
    locked = world.sql("SELECT locked_until IS NOT NULL FROM rl.users WHERE id = :u", u=m.user_id)[
        0
    ][0]
    assert locked
    from app.core import ratelimit

    ratelimit.client().flushdb()
    r = app_client.post("/api/v1/auth/login", json={"email": m.email, "password": PASSWORD})
    assert r.status_code == 401  # correct password still refused while locked, same message
    world.sql(
        "UPDATE rl.users SET locked_until = now() - interval '1 minute' WHERE id = :u", u=m.user_id
    )
    login(app_client, m)


def test_progressive_delay(app_client: TestClient, world: World) -> None:
    for _ in range(3):
        assert (
            app_client.post(
                "/api/v1/auth/login", json={"email": "x@example.com", "password": "nope-nope-nope"}
            ).status_code
            == 401
        )
    r = app_client.post(
        "/api/v1/auth/login", json={"email": "x@example.com", "password": "nope-nope-nope"}
    )
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_mfa_required_for_admin_enrollment_flow(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    t = world.tenant()
    admin = world.member(t, "admin", mfa=False)
    info = login(app_client, admin, expect_state="pending_enrollment")
    assert info["mfa_required"]
    assert app_client.get("/api/v1/org").json()["code"] == "MFA_ENROLLMENT_REQUIRED"
    setup = app_client.post("/api/v1/auth/mfa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(setup["secret"])
    bad = app_client.post("/api/v1/auth/mfa/confirm", json={"code": "000000"})
    assert bad.status_code == 401
    old_cookie = app_client.cookies.get("__Host-rl_session")
    r = app_client.post("/api/v1/auth/mfa/confirm", json={"code": totp.now()})
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert app_client.cookies.get("__Host-rl_session") != old_cookie  # rotated
    assert app_client.get("/api/v1/org").status_code == 200
    assert any("Two-factor authentication enabled" in e.subject for e in outbox)

    # Next login needs MFA; a recovery code works once and forces re-enrollment.
    app_client.cookies.clear()
    body = app_client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
    ).json()
    assert body["state"] == "pending_mfa"
    app_client.headers["X-CSRF-Token"] = body["csrf_token"]
    assert app_client.get("/api/v1/me").json()["code"] == "MFA_REQUIRED"
    r = app_client.post("/api/v1/auth/mfa/verify", json={"recovery_code": codes[0].upper()})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["must_reenroll_mfa"] is True
    app_client.cookies.clear()
    body = app_client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
    ).json()
    app_client.headers["X-CSRF-Token"] = body["csrf_token"]
    assert (
        app_client.post("/api/v1/auth/mfa/verify", json={"recovery_code": codes[0]}).status_code
        == 401
    )


def test_totp_replay_rejected(app_client: TestClient, world: World) -> None:
    owner = world.member(world.tenant(), "owner")
    login(app_client, owner)
    assert owner.totp_secret
    used = pyotp.TOTP(owner.totp_secret).generate_otp(owner._step)
    app_client.cookies.clear()
    body = app_client.post(
        "/api/v1/auth/login", json={"email": owner.email, "password": PASSWORD}
    ).json()
    r = app_client.post(
        "/api/v1/auth/mfa/verify", json={"code": used}, headers={"X-CSRF-Token": body["csrf_token"]}
    )
    assert r.status_code == 401


def test_session_rotation_on_login_and_switch(app_client: TestClient, world: World) -> None:
    t1, t2 = world.tenant("One"), world.tenant("Two")
    m = world.member(t1, "analyst")
    world.add_membership(t2, m.user_id, "viewer")
    info = login(app_client, m)
    assert {o["name"] for o in info["organizations"]} == {"One", "Two"}
    first = app_client.cookies.get("__Host-rl_session")
    r = app_client.post("/api/v1/auth/switch-organization", json={"organization_id": str(t2)})
    assert r.status_code == 200, r.text
    assert r.json()["organization"]["role"] == "viewer"
    assert app_client.cookies.get("__Host-rl_session") != first
    # The old token no longer works.
    other = TestClient(app_client.app, base_url="https://testserver")
    other.cookies.set("__Host-rl_session", first or "")
    assert other.get("/api/v1/me").status_code == 401


def test_password_change_revokes_other_sessions(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    m = world.member(world.tenant(), "analyst")
    second = TestClient(
        app_client.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    )
    login(second, m)
    login(app_client, m)
    sessions = app_client.get("/api/v1/me/sessions").json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    r = app_client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "a much better passphrase 42"},
    )
    assert r.status_code == 200, r.text
    assert app_client.get("/api/v1/me").status_code == 200
    assert second.get("/api/v1/me").status_code == 401
    assert any("password was changed" in e.subject.lower() for e in outbox)


def test_reset_password_revokes_all_sessions(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    m = world.member(world.tenant(), "analyst")
    login(app_client, m)
    anon = TestClient(
        app_client.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    )
    assert anon.post("/api/v1/auth/password/forgot", json={"email": m.email}).status_code == 202
    token = _link_token(next(e for e in outbox if "Reset" in e.subject))
    weak = anon.post("/api/v1/auth/password/reset", json={"token": token, "password": "short"})
    assert weak.status_code == 422 and weak.json()["code"] == "WEAK_PASSWORD"
    # The failed attempt rolled back, so the token is still usable.
    r = anon.post(
        "/api/v1/auth/password/reset", json={"token": token, "password": "brand new passphrase 77"}
    )
    assert r.status_code == 200, r.text
    assert app_client.get("/api/v1/me").status_code == 401
    assert (
        anon.post(
            "/api/v1/auth/password/reset",
            json={"token": token, "password": "brand new passphrase 78"},
        ).json()["code"]
        == "TOKEN_INVALID"
    )


def test_breached_password_rejected(app_client: TestClient, world: World) -> None:
    m = world.member(world.tenant(), "analyst")
    login(app_client, m)
    r = app_client.post(
        "/api/v1/me/password", json={"current_password": PASSWORD, "new_password": "Password1234"}
    )
    assert r.status_code == 422
    assert "breached" in r.json()["detail"]


def test_csrf_token_and_origin_required(app_client: TestClient, world: World) -> None:
    m = world.member(world.tenant(), "analyst")
    login(app_client, m)
    token = app_client.headers.pop("X-CSRF-Token")
    r = app_client.patch("/api/v1/me", json={"name": "X"})
    assert (r.status_code, r.json()["code"]) == (403, "CSRF_TOKEN")
    r = app_client.patch("/api/v1/me", json={"name": "X"}, headers={"X-CSRF-Token": "0" * 64})
    assert r.json()["code"] == "CSRF_TOKEN"
    r = app_client.patch(
        "/api/v1/me",
        json={"name": "X"},
        headers={"X-CSRF-Token": token, "Origin": "https://evil.example"},
    )
    assert r.json()["code"] == "CSRF_ORIGIN"
    r = app_client.post(
        "/api/v1/auth/login",
        json={"email": m.email, "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.json()["code"] == "CSRF_ORIGIN"
    assert (
        app_client.patch(
            "/api/v1/me", json={"name": "X"}, headers={"X-CSRF-Token": token}
        ).status_code
        == 200
    )


def test_security_headers_present(app_client: TestClient) -> None:
    r = app_client.get("/healthz")
    for header in (
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Content-Security-Policy",
        "X-Request-ID",
    ):
        assert header in r.headers
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    r = app_client.get("/healthz", headers={"X-Request-ID": "abc-12345-req"})
    assert r.headers["X-Request-ID"] == "abc-12345-req"
    r = app_client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["X-Request-ID"] != "bad id with spaces"


def test_problem_details_shape(app_client: TestClient) -> None:
    r = app_client.get("/api/v1/me")
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert {"type", "title", "status", "code", "instance", "request_id"} <= set(body)
    r = app_client.post(
        "/api/v1/auth/login", json={"email": "x@example.com", "password": "p", "extra": 1}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "extra"


def test_readyz(app_client: TestClient) -> None:
    r = app_client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {
        "database": "ok",
        "redis": "ok",
        "storage": "ok",
    }


def test_step_up_required_for_security_settings(app_client: TestClient, world: World) -> None:
    owner = world.member(world.tenant(), "owner")
    login(app_client, owner)
    etag = app_client.get("/api/v1/org").headers["ETag"]
    r = app_client.patch(
        "/api/v1/org/settings/security", json={"require_mfa_all": True}, headers={"If-Match": etag}
    )
    assert r.json()["code"] == "STEP_UP_REQUIRED"
    step_up(app_client, owner)
    r = app_client.patch(
        "/api/v1/org/settings/security", json={"require_mfa_all": True}, headers={"If-Match": etag}
    )
    assert r.status_code == 200, r.text
    assert r.headers["ETag"] != etag
    stale = app_client.patch(
        "/api/v1/org/settings/reconciliation",
        json={"abs_tolerance": "2.00"},
        headers={"If-Match": etag},
    )
    assert stale.status_code == 412
    missing = app_client.patch(
        "/api/v1/org/settings/reconciliation", json={"abs_tolerance": "2.00"}
    )
    assert missing.status_code == 428
    money_as_number = app_client.patch(
        "/api/v1/org/settings/reconciliation",
        json={"abs_tolerance": 2.0},
        headers={"If-Match": r.headers["ETag"]},
    )
    assert money_as_number.status_code == 422


def test_email_verification_and_change(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    m = world.member(world.tenant(), "analyst")
    world.sql("UPDATE rl.users SET email_verified_at = NULL WHERE id = :u", u=m.user_id)
    login(app_client, m)
    assert app_client.post("/api/v1/me/verify-email/resend").status_code == 202
    token = _link_token(next(e for e in outbox if "Confirm your email" in e.subject))
    assert app_client.post("/api/v1/auth/email/verify", json={"token": token}).status_code == 200
    r = app_client.post(
        "/api/v1/me/email", json={"new_email": "new@example.com", "password": PASSWORD}
    )
    assert r.status_code == 202
    change = next(e for e in outbox if e.to == "new@example.com")
    assert any(e.to == m.email and "Email change requested" in e.subject for e in outbox)
    assert (
        app_client.post(
            "/api/v1/auth/email/confirm-change", json={"token": _link_token(change)}
        ).status_code
        == 200
    )
    assert (
        world.sql("SELECT email FROM rl.users WHERE id = :u", u=m.user_id)[0][0]
        == "new@example.com"
    )
    assert any(e.to == m.email and "sign-in email was changed" in e.subject for e in outbox)


def test_new_device_notification(
    app_client: TestClient, world: World, outbox: list[RenderedEmail]
) -> None:
    m = world.member(world.tenant(), "viewer")
    login(app_client, m)
    login(app_client, m)
    notices = [e for e in outbox if "New sign-in" in e.subject]
    assert len(notices) == 1
    assert notices[0].html.count("<p>") >= 1 and notices[0].text
