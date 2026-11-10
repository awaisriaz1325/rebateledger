"""Every route declares its access policy (SPEC §8.2)."""

from __future__ import annotations

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from app.api.deps import Authenticated, PlatformAdminOnly, Public, Requires

POLICIES = (Requires, Public, Authenticated, PlatformAdminOnly)


def _policies(dep: Dependant) -> list[object]:
    found: list[object] = [dep.call] if isinstance(dep.call, POLICIES) else []
    for sub in dep.dependencies:
        found.extend(_policies(sub))
    return found


def test_every_route_declares_exactly_one_policy() -> None:
    from app.main import create_app

    app = create_app()
    routes = [
        c.original_route
        for c in iter_route_contexts(app.routes)
        if isinstance(c.original_route, APIRoute)
    ]
    assert len(routes) > 20
    missing = [
        f"{sorted(r.methods or set())} {r.path}" for r in routes if len(_policies(r.dependant)) != 1
    ]
    assert not missing, "routes without exactly one access policy:\n" + "\n".join(missing)


def test_walker_detects_a_route_without_policy() -> None:
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/x")
    def x() -> None: ...

    route = next(r for r in app.routes if isinstance(r, APIRoute))
    assert _policies(route.dependant) == []
