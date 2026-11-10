"""RFC 9457 Problem Details with stable error codes (catalogue: docs/error-codes.md)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    """Raise from services; converted to a Problem Details response."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str = "",
        *,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {detail or title}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors or []
        self.headers = headers or {}
        self.extra = extra or {}


def not_found(what: str = "Resource") -> AppError:
    """404 for missing AND other-tenant objects, so existence is never revealed (SPEC §8.1)."""
    return AppError(404, "NOT_FOUND", f"{what} not found")


def forbidden(detail: str = "You do not have permission to do this.") -> AppError:
    return AppError(403, "FORBIDDEN", "Forbidden", detail)


def conflict(code: str, detail: str) -> AppError:
    return AppError(409, code, "Conflict", detail)


def invalid(code: str, detail: str, field: str | None = None) -> AppError:
    errors = [{"field": field, "code": code, "message": detail}] if field else []
    return AppError(422, code, "Invalid request", detail, errors=errors)


def _body(
    request: Request, status: int, code: str, title: str, detail: str, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"https://docs.rebateledger.invalid/errors/{code}",
        "title": title,
        "status": status,
        "code": code,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", ""),
    }
    if detail:
        body["detail"] = detail
    body.update({k: v for k, v in extra.items() if v})
    return body


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    body = _body(
        request, exc.status, exc.code, exc.title, exc.detail, errors=exc.errors, **exc.extra
    )
    return JSONResponse(body, status_code=exc.status, media_type=PROBLEM_JSON, headers=exc.headers)


async def validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header")]
        errors.append(
            {
                "field": ".".join(loc),
                "code": str(err.get("type", "invalid")).upper(),
                "message": str(err.get("msg", "")),
            }
        )
    body = _body(
        request,
        422,
        "VALIDATION_ERROR",
        "Invalid request",
        "Some fields are invalid.",
        errors=errors,
    )
    return JSONResponse(body, status_code=422, media_type=PROBLEM_JSON)


_HTTP_CODES = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
}


async def http_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    body = _body(
        request, exc.status_code, code, str(exc.detail) if exc.status_code < 500 else "Error", ""
    )
    return JSONResponse(body, status_code=exc.status_code, media_type=PROBLEM_JSON)


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak stack traces, SQL or paths."""
    import structlog

    structlog.get_logger("app").exception("unhandled_error", error_type=type(exc).__name__)
    body = _body(
        request,
        500,
        "INTERNAL_ERROR",
        "Something went wrong",
        "The error was logged. Try again; if it persists, contact support with the request id.",
    )
    return JSONResponse(body, status_code=500, media_type=PROBLEM_JSON)
