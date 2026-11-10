"""Liveness and readiness (SPEC §12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DB, Public
from app.core import ratelimit
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz", dependencies=[Depends(Public())])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", dependencies=[Depends(Public())], response_model=None)
def readyz(db: DB) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - readiness reports any failure as "fail"
        checks["database"] = "fail"
    try:
        ratelimit.client().ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001 - readiness reports any failure as "fail"
        checks["redis"] = "fail"
    storage = get_settings().storage_dir
    try:
        storage.mkdir(parents=True, exist_ok=True)
        checks["storage"] = "ok" if storage.is_dir() else "fail"
    except OSError:
        checks["storage"] = "fail"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "fail", "checks": checks}, status_code=200 if ok else 503
    )
