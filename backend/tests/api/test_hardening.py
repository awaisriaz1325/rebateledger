"""Phase 10 hardening checks (PHASES §10.2): body limits, error leakage, random-id sweep."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import World, login
from tests.api.test_authz_matrix import _call, guarded_routes


def test_oversized_json_body_is_refused_before_parsing(
    app_client: TestClient, world: World
) -> None:
    login(app_client, world.member(world.tenant(), "analyst"))
    huge = '{"name": "' + "x" * (2 * 1024 * 1024) + '"}'
    r = app_client.post(
        "/api/v1/suppliers", content=huge, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_streamed_body_without_length_is_also_capped(app_client: TestClient, world: World) -> None:
    login(app_client, world.member(world.tenant(), "analyst"))

    def chunks() -> Any:
        for _ in range(3):
            yield b"x" * (1024 * 1024)

    r = app_client.post(
        "/api/v1/suppliers", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413


def test_upload_routes_keep_their_larger_limit(app_client: TestClient, world: World) -> None:
    login(app_client, world.member(world.tenant(), "analyst"))
    body = b"supplier,amount\n" + b"ACME,1.00\n" * (300 * 1024)  # ~3 MB, above the JSON cap
    r = app_client.post(
        "/api/v1/imports",
        files={"file": ("p.csv", body, "text/csv")},
        data={"import_type": "purchases"},
    )
    assert r.status_code == 201, r.text


def test_unhandled_errors_never_leak_internals(
    app_client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import suppliers

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            'SELECT secret FROM rl.users WHERE password_hash = "x" -- /srv/app/secret.py'
        )

    monkeypatch.setattr(suppliers, "select", boom)
    login(app_client, world.member(world.tenant(), "analyst"))
    client = TestClient(
        app_client.app,
        raise_server_exceptions=False,
        base_url="https://testserver",
        headers=dict(app_client.headers),
    )
    client.cookies = app_client.cookies
    r = client.get("/api/v1/suppliers")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "INTERNAL_ERROR" and body["request_id"]
    assert not re.search(r"SELECT|password|secret|/srv|Traceback|RuntimeError", r.text)


def test_unknown_route_and_method_use_problem_details(app_client: TestClient) -> None:
    r = app_client.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
    r = app_client.delete("/healthz")
    assert r.status_code == 405 and r.json()["status"] == 405


def test_random_ids_never_cause_server_errors(app_client: TestClient, world: World) -> None:
    """Fuzz every guarded route with random ids as an Owner: 404/409/422/4xx, never 5xx."""
    owner = world.member(world.tenant(), "owner")
    login(app_client, owner)
    failures = []
    for method, path, _ in guarded_routes():
        filled = re.sub(r"\{[a-z_]+\}", lambda _: str(uuid.uuid4()), path)
        r = _call(app_client, method, filled, path)
        if r.status_code >= 500:
            failures.append(f"{method} {path}: {r.status_code}")
    assert not failures, failures


def test_unmatched_credits_query_count_does_not_grow_with_credits(
    app_client: TestClient, world: World
) -> None:
    """Regression (Phase 10 load test): one remainder query per credit made the list O(n)
    in round trips and took minutes at 100k credits."""
    from sqlalchemy import event

    from app.db.session import get_engine

    t = world.tenant()
    login(app_client, world.member(t, "analyst"))
    sid = app_client.post("/api/v1/suppliers", json={"name": "Acme", "codes": ["ACME"]}).json()[
        "id"
    ]
    for i in range(40):
        world.sql(
            "INSERT INTO rl.credit_lines (id, tenant_id, supplier_id, credit_reference, credit_date, amount, memo, possible_duplicate, voided, created_at) "
            "VALUES (:i, :t, :s, :r, '2025-04-20', 100, '', false, false, now())",
            i=uuid.uuid7(),
            t=t,
            s=sid,
            r=f"CM-{i}",
        )
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2])[:40])

    eng = get_engine()
    event.listen(eng, "before_cursor_execute", count)
    try:
        rows = app_client.get("/api/v1/credits/unmatched").json()
    finally:
        event.remove(eng, "before_cursor_execute", count)
    assert len(rows) == 40
    assert len(statements) < 25, f"{len(statements)} statements for 40 credits"
    assert len(app_client.get("/api/v1/credits/unmatched", params={"limit": 10}).json()) == 10
