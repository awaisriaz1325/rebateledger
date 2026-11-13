"""Authorization matrix: every permission-guarded route × role × own/other tenant (SPEC §8.1–8.2).

Generated from the route table, so new endpoints are covered automatically:
- unauthenticated → 401
- role without the permission → 403 FORBIDDEN
- role with the permission + another tenant's object id → 404 (never 403, never 2xx)

Path parameters are filled from ``OTHER_TENANT_OBJECTS``; a route with an unknown
parameter name fails the test so its factory must be added.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from app.api.deps import PlatformAdminOnly, Requires
from app.core.permissions import permissions_for
from tests.api.conftest import World, login

ROLES = ("owner", "admin", "analyst", "viewer")


def _requires(dep: Dependant) -> Requires | None:
    if isinstance(dep.call, Requires):
        return dep.call
    for sub in dep.dependencies:
        found = _requires(sub)
        if found:
            return found
    return None


def _is_platform(dep: Dependant) -> bool:
    return isinstance(dep.call, PlatformAdminOnly) or any(_is_platform(s) for s in dep.dependencies)


def guarded_routes() -> list[tuple[str, str, Requires]]:
    from app.main import create_app

    out = []
    for c in iter_route_contexts(create_app().routes):
        r = c.original_route
        if not isinstance(r, APIRoute):
            continue
        req = _requires(r.dependant)
        if req is None:
            continue
        for method in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
            out.append((method, r.path, req))
    return out


def platform_routes() -> list[tuple[str, str]]:
    from app.main import create_app

    out: list[tuple[str, str]] = []
    for c in iter_route_contexts(create_app().routes):
        r = c.original_route
        if isinstance(r, APIRoute) and _is_platform(r.dependant):
            out.extend((m, r.path) for m in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}))
    return out


ObjectFactory = Callable[[World, uuid.UUID], uuid.UUID]


def _membership(w: World, t: uuid.UUID) -> uuid.UUID:
    return w.member(t, "viewer").membership_id


def _invite(w: World, t: uuid.UUID) -> uuid.UUID:
    iid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.invites (id, tenant_id, email, role, token_hash, expires_at) VALUES (:i, :t, 'b@example.com', 'viewer', :h, now() + interval '1 day')",
        i=iid,
        t=t,
        h=uuid.uuid4().bytes + uuid.uuid4().bytes,
    )
    return iid


def _grant(w: World, t: uuid.UUID) -> uuid.UUID:
    gid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.support_access_grants (id, tenant_id, scope, reason, granted_by, expires_at) VALUES (:g, :t, 'read_only', '', :u, now() + interval '1 day')",
        g=gid,
        t=t,
        u=uuid.uuid7(),
    )
    return gid


def _job(w: World, t: uuid.UUID) -> uuid.UUID:
    jid = uuid.uuid7()
    w.sql(
        "INSERT INTO rl.jobs (id, tenant_id, type, status, progress, payload, attempts, max_attempts, cancel_requested) VALUES (:j, :t, 'noop', 'succeeded', 0, '{}', 1, 3, false)",
        j=jid,
        t=t,
    )
    return jid


OTHER_TENANT_OBJECTS: dict[str, ObjectFactory] = {
    "membership_id": _membership,
    "invite_id": _invite,
    "grant_id": _grant,
    "job_id": _job,
}
EXTRA_FACTORIES: dict[str, ObjectFactory] = {}
"""Later phases register factories here from their own test modules."""


def factories() -> dict[str, ObjectFactory]:
    from tests.api import factories as later  # noqa: F401  (registers phase 3+ factories)

    return {**OTHER_TENANT_OBJECTS, **EXTRA_FACTORIES}


def _fill(path: str, ids: dict[str, uuid.UUID]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in ids:
            pytest.fail(f"no other-tenant factory for path parameter '{name}' in {path}")
        return str(ids[name])

    return re.sub(r"\{([a-z_]+)(?::[a-z]+)?\}", sub, path)


SAMPLE_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/api/v1/org/members/{membership_id}"): {"role": "viewer"},
    ("POST", "/api/v1/imports/{batch_id}/preset"): {"preset_id": "p21-purchases"},
    ("PUT", "/api/v1/suppliers/{supplier_id}/members"): {"supplier_ids": []},
}
"""Valid bodies so permitted calls reach the object lookup (not 422). Later phases add more."""


SAMPLE_FILES: dict[tuple[str, str], dict[str, Any]] = {}
"""Multipart routes: (files, form data)."""


def _call(client: TestClient, method: str, path: str, template: str = "") -> Any:
    kwargs: dict[str, Any] = {"headers": {"If-Match": '"v1"', "Idempotency-Key": str(uuid.uuid4())}}
    if (method, template) in SAMPLE_FILES:
        kwargs.update(SAMPLE_FILES[(method, template)])
    elif method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = SAMPLE_BODIES.get((method, template), {})
    return client.request(method, path, **kwargs)


def test_matrix(app_client: TestClient, world: World) -> None:
    routes = guarded_routes()
    assert routes
    tenant_a, tenant_b = world.tenant("Tenant A"), world.tenant("Tenant B")
    all_factories = factories()
    names = {n for _, p, _ in routes for n in re.findall(r"\{([a-z_]+)", p)}
    other_ids = {n: all_factories[n](world, tenant_b) for n in names if n in all_factories}

    anon = TestClient(
        app_client.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    )
    for method, path, _ in routes:
        r = _call(anon, method, _fill(path, other_ids), path)
        assert r.status_code == 401, (method, path, r.status_code)

    failures: list[str] = []
    for role in ROLES:
        member = world.member(tenant_a, role)
        client = TestClient(
            app_client.app, base_url="https://testserver", headers={"Origin": "https://testserver"}
        )
        login(client, member)
        granted = permissions_for(role)
        for method, path, req in routes:
            r = _call(client, method, _fill(path, other_ids), path)
            body = (
                r.json()
                if r.headers.get("content-type", "").startswith("application/") and r.content
                else None
            )
            code = body.get("code") if isinstance(body, dict) else None
            if req.permission not in granted:
                if (r.status_code, code) != (403, "FORBIDDEN"):
                    failures.append(
                        f"{role} {method} {path}: expected 403 FORBIDDEN, got {r.status_code} {code}"
                    )
            elif "{" in path:
                if r.status_code != 404:
                    failures.append(
                        f"{role} {method} {path} with other-tenant id: expected 404, got {r.status_code} {code}"
                    )
            elif r.status_code == 403 and code == "FORBIDDEN":
                failures.append(f"{role} {method} {path}: permitted role got 403")
    assert not failures, "\n".join(failures)


def test_platform_routes_hidden_from_tenant_users(app_client: TestClient, world: World) -> None:
    routes = platform_routes()
    owner = world.member(world.tenant(), "owner")
    login(app_client, owner)
    for method, path in routes:
        filled = re.sub(r"\{[a-z_]+\}", str(uuid.uuid7()), path)
        r = _call(app_client, method, filled)
        assert r.status_code == 404, (method, path, r.status_code)
