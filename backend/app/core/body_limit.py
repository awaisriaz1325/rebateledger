"""Request body size limits (ASVS 13.1 / DoS). Pure ASGI so it runs before any parsing.

JSON endpoints accept at most ``JSON_LIMIT``; the multipart upload endpoints accept the
largest file they allow plus multipart overhead. Requests that declare a larger
``Content-Length`` are refused immediately; streamed bodies are counted as they arrive.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.imports.detect import MAX_UPLOAD_BYTES

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

JSON_LIMIT = 1024 * 1024
OVERHEAD = 1024 * 1024
UPLOADS = [
    (re.compile(r"^/api/v1/imports$"), MAX_UPLOAD_BYTES + OVERHEAD),
    (re.compile(r"^/api/v1/agreements/[^/]+/attachments$"), 20 * 1024 * 1024 + OVERHEAD),
    (re.compile(r"^/api/v1/claims/[^/]+/attachments$"), 20 * 1024 * 1024 + OVERHEAD),
]


def limit_for(path: str) -> int:
    for pattern, limit in UPLOADS:
        if pattern.match(path):
            return limit
    return JSON_LIMIT


async def _reject(send: Send) -> None:
    body = json.dumps(
        {
            "type": "https://docs.rebateledger.invalid/errors/PAYLOAD_TOO_LARGE",
            "title": "Request too large",
            "status": 413,
            "code": "PAYLOAD_TOO_LARGE",
            "detail": "The request body is larger than this endpoint accepts.",
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["path"])
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _reject(send)
            return
        received = 0
        started = False
        too_large = False

        async def counted_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer now and tell the app the client went away; it never sees the excess.
                    too_large = True
                    if not started:
                        await _reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if too_large:
                return  # the 413 has already been sent
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not too_large:
                raise
