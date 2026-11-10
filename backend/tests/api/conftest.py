"""Fixtures for API and database tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app.core import ratelimit
from app.core.config import get_settings
from app.core.security import encrypt_secret, hash_password, new_totp_secret
from app.emails.service import MemoryAdapter, RenderedEmail, set_adapter

BACKEND = Path(__file__).resolve().parents[2]
PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    url = get_settings().migration_database_url
    assert url is not None
    engine = create_engine(url.get_secret_value(), connect_args={"options": "-c search_path=rl"})
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS rl CASCADE"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()
    from app.db.session import get_engine

    get_engine().dispose()
    ratelimit.client().close()


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> Iterator[None]:
    if "owner_engine" not in request.fixturenames:
        yield
        return
    engine: Engine = request.getfixturevalue("owner_engine")
    with engine.begin() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'rl' AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        conn.execute(text("TRUNCATE " + ", ".join(f"rl.{t}" for t in tables) + " CASCADE"))
    ratelimit.client().flushdb()
    yield


@pytest.fixture
def outbox() -> list[RenderedEmail]:
    adapter = MemoryAdapter()
    set_adapter(adapter)
    return adapter.outbox


@pytest.fixture
def app_client(owner_engine: Engine, outbox: list[RenderedEmail]) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(
        create_app(), base_url="https://testserver", headers={"Origin": "https://testserver"}
    ) as c:
        yield c


@dataclass
class Member:
    user_id: uuid.UUID
    email: str
    password: str
    role: str
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    totp_secret: str | None = None
    _step: int = field(default=0)

    def code(self) -> str:
        """A fresh TOTP code, never the same timestep twice (replay protection)."""
        assert self.totp_secret is not None
        totp = pyotp.TOTP(self.totp_secret)
        import time

        current = int(time.time()) // 30
        self._step = max(self._step + 1, current - 1)
        return totp.generate_otp(self._step)


class World:
    """Builds tenants/users directly as the owner role (bypassing RLS) for test setup."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def tenant(self, name: str = "Acme Supply", **values: Any) -> uuid.UUID:
        tid = uuid.uuid7()
        cols = {
            "id": tid,
            "name": name,
            "timezone": "America/Chicago",
            "fiscal_year_start_month": 1,
            "currency": "USD",
            "require_mfa_all": False,
            "session_idle_minutes": 30,
            "allowed_invite_domains": [],
            "abs_tolerance": "1.00",
            "pct_tolerance": "0.005",
            "default_payment_terms_days": 60,
            "data_freshness_days": 45,
            "tier_alert_pct": "0.10",
            "tier_alert_days": 21,
            "four_eyes_activation": False,
            "four_eyes_writeoff": False,
            "onboarding": "{}",
            "is_demo": False,
            "row_version": 1,
        }
        cols.update(values)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO rl.tenants ({', '.join(cols)}) VALUES ({', '.join(':' + k for k in cols)})"
                ),
                cols,
            )
        return tid

    def user(
        self, email: str, *, password: str = PASSWORD, name: str = "Test User", mfa: bool = False
    ) -> tuple[uuid.UUID, str | None]:
        uid = uuid.uuid7()
        secret = new_totp_secret() if mfa else None
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO rl.users (id, email, name, password_hash, email_verified_at, failed_login_count, must_reenroll_mfa, preferences) "
                    "VALUES (:id, :e, :n, :p, now(), 0, false, '{}')"
                ),
                {"id": uid, "e": email, "n": name, "p": hash_password(password)},
            )
            if secret:
                conn.execute(
                    text(
                        "INSERT INTO rl.mfa_factors (id, user_id, secret_encrypted, confirmed_at) VALUES (:id, :u, :s, now())"
                    ),
                    {"id": uuid.uuid7(), "u": uid, "s": encrypt_secret(secret)},
                )
        return uid, secret

    def member(
        self, tenant_id: uuid.UUID, role: str, email: str | None = None, *, mfa: bool | None = None
    ) -> Member:
        email = email or f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        needs_mfa = role in ("owner", "admin") if mfa is None else mfa
        uid, secret = self.user(email, mfa=needs_mfa)
        mid = self.add_membership(tenant_id, uid, role)
        return Member(uid, email, PASSWORD, role, tenant_id, mid, secret)

    def add_membership(self, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str) -> uuid.UUID:
        mid = uuid.uuid7()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO rl.memberships (id, tenant_id, user_id, role, status) VALUES (:id, :t, :u, :r, 'active')"
                ),
                {"id": mid, "t": tenant_id, "u": user_id, "r": role},
            )
        return mid

    def platform_admin(self, email: str = "ops@example.com") -> Member:
        uid, secret = self.user(email, mfa=True)
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO rl.platform_admins (user_id) VALUES (:u)"), {"u": uid})
        return Member(uid, email, PASSWORD, "platform", uuid.UUID(int=0), uuid.UUID(int=0), secret)

    def sql(self, statement: str, **params: Any) -> list[Any]:
        with self.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return list(result.all()) if result.returns_rows else []


@pytest.fixture
def world(owner_engine: Engine) -> World:
    return World(owner_engine)


def login(client: TestClient, m: Member, *, expect_state: str = "active") -> dict[str, Any]:
    """Sign in (completing MFA if enrolled) and install the CSRF header."""
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"email": m.email, "password": m.password})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    if body["state"] == "pending_mfa":
        r = client.post(
            "/api/v1/auth/mfa/verify",
            json={"code": m.code()},
            headers={"X-CSRF-Token": body["csrf_token"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
    assert body["state"] == expect_state, body
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


def step_up(client: TestClient, m: Member) -> None:
    payload: dict[str, str] = {"password": m.password}
    if m.totp_secret:
        payload["code"] = m.code()
    r = client.post("/api/v1/auth/step-up", json=payload)
    assert r.status_code == 200, r.text
