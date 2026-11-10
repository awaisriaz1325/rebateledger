"""The signed-in user's own account (SPEC §4.1 flows, §4.13 notifications)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from app.api.deps import Authenticated, Ctx
from app.api.routes.auth import set_session_cookie
from app.api.schemas.common import Email, In, Name, Ok, Out, Password
from app.services import auth as auth_service

router = APIRouter(prefix="/api/v1/me", tags=["me"])
Me = Annotated[Ctx, Depends(Authenticated())]


class ProfileIn(In):
    name: Name | None = None
    preferences: dict[str, str | bool] | None = None


class ProfileOut(Out):
    id: uuid.UUID
    email: str
    name: str
    preferences: dict[str, Any]


class PasswordChangeIn(In):
    current_password: Password
    new_password: Password


class EmailChangeIn(In):
    new_email: Email
    password: Password


class SessionOut(Out):
    id: uuid.UUID
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


ALLOWED_PREFERENCES = {"theme", "date_format", "density"}


@router.get("", response_model=ProfileOut)
def get_me(ctx: Me) -> ProfileOut:
    return ProfileOut.model_validate(ctx.user)


@router.patch("", response_model=ProfileOut)
def update_me(body: ProfileIn, ctx: Me) -> ProfileOut:
    if body.name is not None:
        ctx.user.name = body.name
    if body.preferences is not None:
        unknown = set(body.preferences) - ALLOWED_PREFERENCES
        if unknown:
            from app.core.errors import invalid

            raise invalid(
                "UNKNOWN_PREFERENCE",
                f"Unknown preference: {', '.join(sorted(unknown))}",
                "preferences",
            )
        ctx.user.preferences = {**ctx.user.preferences, **body.preferences}
    return ProfileOut.model_validate(ctx.user)


@router.post("/password", response_model=Ok)
def change_password(body: PasswordChangeIn, response: Response, ctx: Me) -> Ok:
    token = auth_service.change_password(
        ctx.db, ctx.session, ctx.user, body.current_password, body.new_password
    )
    set_session_cookie(response, token)
    return Ok()


@router.post("/email", response_model=Ok, status_code=202)
def change_email(body: EmailChangeIn, ctx: Me) -> Ok:
    auth_service.request_email_change(ctx.db, ctx.user, body.new_email, body.password)
    return Ok()


@router.post("/verify-email/resend", response_model=Ok, status_code=202)
def resend_verification(ctx: Me) -> Ok:
    if ctx.user.email_verified_at is None:
        auth_service.send_verification(ctx.db, ctx.user)
    return Ok()


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(ctx: Me) -> list[SessionOut]:
    return [
        SessionOut(
            id=s.id,
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            current=s.id == ctx.session.id,
        )
        for s in auth_service.list_sessions(ctx.db, ctx.user.id)
    ]


@router.delete("/sessions/{session_id}", response_model=Ok)
def revoke_session(session_id: uuid.UUID, ctx: Me) -> Ok:
    auth_service.revoke_session(ctx.db, ctx.user.id, session_id)
    return Ok()
