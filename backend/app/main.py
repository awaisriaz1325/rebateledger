"""FastAPI application factory."""

from __future__ import annotations

import importlib
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    app_error_handler,
    http_handler,
    unhandled_handler,
    validation_handler,
)
from app.core.logging import configure_logging
from app.services.audit import RequestMeta, request_meta

log = structlog.get_logger("http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Frame-Options": "DENY",
    # The API only returns JSON/CSV/PDF; nothing it serves may run scripts or be framed.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}
_REQUEST_ID_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def _request_id(raw: str | None) -> str:
    if raw and 8 <= len(raw) <= 80 and set(raw) <= _REQUEST_ID_OK:
        return raw
    return str(uuid.uuid4())


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json_logs=settings.env.value != "local")
    importlib.import_module("app.services.registry")  # registers job handlers

    application = FastAPI(
        title=f"{settings.product_name} API",
        version="1.0.0",
        docs_url=None if settings.is_production_like else "/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_handler)
    application.add_exception_handler(StarletteHTTPException, http_handler)
    application.add_exception_handler(Exception, unhandled_handler)

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = _request_id(request.headers.get("x-request-id"))
        request.state.request_id = rid
        token = request_meta.set(
            RequestMeta(
                rid,
                request.client.host if request.client else "",
                request.headers.get("user-agent", ""),
            )
        )
        structlog.contextvars.bind_contextvars(request_id=rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_meta.reset(token)
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if settings.is_production_like:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        log.info(
            "request",
            method=request.method,
            route=request.scope.get("route").path if request.scope.get("route") else "unmatched",  # type: ignore[union-attr]
            status=response.status_code,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            user_id=getattr(request.state, "user_id", None),
        )
        structlog.contextvars.clear_contextvars()
        return response

    from app.api.routes import ROUTERS

    for router in ROUTERS:
        application.include_router(router)
    return application
