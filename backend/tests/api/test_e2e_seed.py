"""The E2E seed creates users who can complete a real MFA sign-in, and never runs in production."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.core.config import Environment, get_settings
from app.services.e2e_seed import seed_e2e


def test_seeded_owner_can_sign_in_with_totp(app_client: TestClient) -> None:
    data = seed_e2e()
    owner = data["users"]["owner"]
    r = app_client.post(
        "/api/v1/auth/login", json={"email": owner["email"], "password": owner["password"]}
    )
    assert r.status_code == 200 and r.json()["state"] == "pending_mfa"
    r = app_client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": pyotp.TOTP(owner["totp_secret"]).now()},
        headers={"X-CSRF-Token": r.json()["csrf_token"]},
    )
    assert r.status_code == 200 and r.json()["state"] == "active"
    me = app_client.get("/api/v1/auth/session").json()
    assert me["organization"]["role"] == "owner"
    assert data["users"]["admin"]["email"] != owner["email"]
    ops = data["users"]["ops"]
    r = app_client.post(
        "/api/v1/auth/login", json={"email": ops["email"], "password": ops["password"]}
    )
    assert r.json()["is_platform_admin"] is True


def test_refuses_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "env", Environment.PRODUCTION)
    with pytest.raises(SystemExit, match="refuses"):
        seed_e2e()
