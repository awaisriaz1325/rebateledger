"""Authentication endpoints (SPEC §4.1). Handlers stay thin: parse, authorize, call a service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import DB, SESSION_COOKIE, Authenticated, Ctx, Public
from app.api.schemas.common import Code, Email, In, Name, Ok, Out, Password, Token
from app.core.config import get_settings
from app.core.permissions import MFA_REQUIRED_ROLES, permissions_for
from app.core.security import csrf_token_for
from app.db.models.identity import Role, SessionState, SupportAccessGrant, Tenant
from app.services import auth as auth_service
from app.services import org as org_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def client_meta(request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else ""
    return request.headers.get("user-agent", "")[:400], ip


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=get_settings().session_absolute_hours * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


# --------------------------------------------------------------------------- schemas


class OrgSummary(Out):
    id: uuid.UUID
    name: str
    role: str


class ActiveOrg(OrgSummary):
    permissions: list[str]
    timezone: str
    fiscal_year_start_month: int


class SupportAccessInfo(Out):
    scope: str
    expires_at: datetime


class UserInfo(Out):
    id: uuid.UUID
    email: str
    name: str
    email_verified: bool
    mfa_enabled: bool
    must_reenroll_mfa: bool


class SessionInfo(Out):
    authenticated: bool
    state: str | None = None
    csrf_token: str | None = None
    user: UserInfo | None = None
    is_platform_admin: bool = False
    organization: ActiveOrg | None = None
    organizations: list[OrgSummary] = Field(default_factory=list)
    support_access: SupportAccessInfo | None = None
    mfa_required: bool = False


def session_info(db: Session, request: Request, ctx: Ctx | None = None) -> SessionInfo:
    if ctx is None:
        resolved = auth_service.resolve(db, request.cookies.get(SESSION_COOKIE))
        if resolved is None:
            return SessionInfo(authenticated=False)
        s, user = resolved
    else:
        s, user = ctx.session, ctx.user
    has_mfa = auth_service.has_mfa(db, user.id)
    info = SessionInfo(
        authenticated=True,
        state=s.state,
        csrf_token=csrf_token_for(str(s.id)),
        user=UserInfo(
            id=user.id,
            email=user.email,
            name=user.name,
            email_verified=user.email_verified_at is not None,
            mfa_enabled=has_mfa,
            must_reenroll_mfa=user.must_reenroll_mfa,
        ),
        is_platform_admin=s.is_platform,
    )
    if s.is_platform:
        info.mfa_required = True
        if s.active_tenant_id:
            from app.db.session import set_platform_context

            set_platform_context(db, True)
            tenant = db.get(Tenant, s.active_tenant_id)
            grants = (
                list(org_service.active_support_grants(db, s.active_tenant_id)) if tenant else []
            )
            if tenant and grants:
                g: SupportAccessGrant = grants[0]
                perms = (
                    ["view_data", "export"]
                    if g.scope == "read_only"
                    else sorted(p.value for p in permissions_for(Role.ANALYST.value))
                )
                info.organization = ActiveOrg(
                    id=tenant.id,
                    name=tenant.name,
                    role="support",
                    permissions=perms,
                    timezone=tenant.timezone,
                    fiscal_year_start_month=tenant.fiscal_year_start_month,
                )
                info.support_access = SupportAccessInfo(scope=g.scope, expires_at=g.expires_at)
        return info
    memberships = auth_service.active_memberships(db, user.id)
    info.organizations = [OrgSummary(id=t.id, name=t.name, role=m.role) for m, t in memberships]
    for m, t in memberships:
        if t.id == s.active_tenant_id:
            info.organization = ActiveOrg(
                id=t.id,
                name=t.name,
                role=m.role,
                permissions=sorted(p.value for p in permissions_for(m.role)),
                timezone=t.timezone,
                fiscal_year_start_month=t.fiscal_year_start_month,
            )
            info.mfa_required = Role(m.role) in MFA_REQUIRED_ROLES or t.require_mfa_all
    return info


class LoginIn(In):
    email: Email
    password: Password


class MfaVerifyIn(In):
    code: Code | None = None
    recovery_code: Annotated[str | None, Field(max_length=20)] = None


class MfaSetupOut(Out):
    secret: str
    otpauth_uri: str


class RecoveryCodesOut(Out):
    recovery_codes: list[str]


class MfaConfirmIn(In):
    code: Code


class StepUpIn(In):
    password: Password
    code: Code | None = None


class ForgotIn(In):
    email: Email


class ResetIn(In):
    token: Token
    password: Password


class TokenIn(In):
    token: Token


class SwitchOrgIn(In):
    organization_id: uuid.UUID


class InvitePreviewOut(Out):
    organization_name: str
    email: str
    role: str
    has_account: bool


class AcceptInviteIn(In):
    token: Token
    name: Name | None = None
    password: Password


# --------------------------------------------------------------------------- routes


@router.get("/session", response_model=SessionInfo, dependencies=[Depends(Public())])
def get_session(request: Request, db: DB) -> SessionInfo:
    return session_info(db, request)


@router.post("/login", response_model=SessionInfo, dependencies=[Depends(Public())])
def login(body: LoginIn, request: Request, response: Response, db: DB) -> SessionInfo:
    ua, ip = client_meta(request)
    issued = auth_service.login(db, body.email, body.password, user_agent=ua, ip=ip)
    set_session_cookie(response, issued.token)
    request.cookies[SESSION_COOKIE] = issued.token
    return session_info(db, request)


@router.post("/logout", response_model=Ok)
def logout(
    response: Response, ctx: Annotated[Ctx, Depends(Authenticated(allow_pending=True))]
) -> Ok:
    auth_service.revoke_session(ctx.db, ctx.user.id, ctx.session.id)
    clear_session_cookie(response)
    return Ok()


@router.post("/mfa/verify", response_model=SessionInfo)
def mfa_verify(
    body: MfaVerifyIn,
    request: Request,
    response: Response,
    ctx: Annotated[Ctx, Depends(Authenticated(allow_pending=True))],
) -> SessionInfo:
    token = auth_service.complete_mfa(
        ctx.db, ctx.session, ctx.user, code=body.code, recovery_code=body.recovery_code
    )
    set_session_cookie(response, token)
    return session_info(ctx.db, request, ctx)


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(ctx: Annotated[Ctx, Depends(Authenticated(allow_pending=True))]) -> MfaSetupOut:
    if ctx.session.state == SessionState.PENDING_MFA.value:
        from app.core.errors import AppError

        raise AppError(
            403,
            "MFA_REQUIRED",
            "Two-factor authentication required",
            "Enter your current code first.",
        )
    secret, uri = auth_service.start_enrollment(ctx.db, ctx.user)
    return MfaSetupOut(secret=secret, otpauth_uri=uri)


@router.post("/mfa/confirm", response_model=RecoveryCodesOut)
def mfa_confirm(
    body: MfaConfirmIn,
    response: Response,
    ctx: Annotated[Ctx, Depends(Authenticated(allow_pending=True))],
) -> RecoveryCodesOut:
    if ctx.session.state == SessionState.PENDING_MFA.value:
        from app.core.errors import AppError

        raise AppError(
            403,
            "MFA_REQUIRED",
            "Two-factor authentication required",
            "Enter your current code first.",
        )
    codes, token = auth_service.confirm_enrollment(ctx.db, ctx.user, ctx.session, body.code)
    set_session_cookie(response, token)
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/mfa/recovery-codes", response_model=RecoveryCodesOut)
def regenerate_recovery_codes(ctx: Annotated[Ctx, Depends(Authenticated())]) -> RecoveryCodesOut:
    auth_service.require_recent_step_up(ctx.session)
    return RecoveryCodesOut(recovery_codes=auth_service.replace_recovery_codes(ctx.db, ctx.user))


@router.post("/mfa/disable", response_model=Ok)
def mfa_disable(response: Response, ctx: Annotated[Ctx, Depends(Authenticated())]) -> Ok:
    auth_service.require_recent_step_up(ctx.session)
    roles = [Role(m.role) for m, _ in auth_service.active_memberships(ctx.db, ctx.user.id)]
    tenants = [t for _, t in auth_service.active_memberships(ctx.db, ctx.user.id)]
    requiring = (
        ctx.is_platform
        or any(r in MFA_REQUIRED_ROLES for r in roles)
        or any(t.require_mfa_all for t in tenants)
    )
    auth_service.disable_mfa(ctx.db, ctx.user, requiring)
    clear_session_cookie(response)
    return Ok()


@router.post("/step-up", response_model=Ok)
def step_up(body: StepUpIn, ctx: Annotated[Ctx, Depends(Authenticated())]) -> Ok:
    auth_service.step_up(ctx.db, ctx.session, ctx.user, body.password, body.code)
    return Ok()


@router.post(
    "/password/forgot", status_code=202, response_model=Ok, dependencies=[Depends(Public())]
)
def forgot_password(body: ForgotIn, request: Request, db: DB) -> Ok:
    auth_service.forgot_password(db, body.email, client_meta(request)[1])
    return Ok()


@router.post("/password/reset", response_model=Ok, dependencies=[Depends(Public())])
def reset_password(body: ResetIn, response: Response, db: DB) -> Ok:
    auth_service.reset_password(db, body.token, body.password)
    clear_session_cookie(response)
    return Ok()


@router.post("/email/verify", response_model=Ok, dependencies=[Depends(Public())])
def verify_email(body: TokenIn, db: DB) -> Ok:
    auth_service.verify_email(db, body.token)
    return Ok()


@router.post("/email/confirm-change", response_model=Ok, dependencies=[Depends(Public())])
def confirm_email_change(body: TokenIn, response: Response, db: DB) -> Ok:
    auth_service.confirm_email_change(db, body.token)
    clear_session_cookie(response)
    return Ok()


@router.post("/switch-organization", response_model=SessionInfo)
def switch_organization(
    body: SwitchOrgIn,
    request: Request,
    response: Response,
    ctx: Annotated[Ctx, Depends(Authenticated())],
) -> SessionInfo:
    token = auth_service.switch_tenant(ctx.db, ctx.session, ctx.user, body.organization_id)
    set_session_cookie(response, token)
    return session_info(ctx.db, request, ctx)


@router.post("/invites/preview", response_model=InvitePreviewOut, dependencies=[Depends(Public())])
def preview_invite(body: TokenIn, db: DB) -> InvitePreviewOut:
    return InvitePreviewOut(**org_service.preview_invite(db, body.token))


@router.post("/invites/accept", response_model=SessionInfo, dependencies=[Depends(Public())])
def accept_invite(
    body: AcceptInviteIn, request: Request, response: Response, db: DB
) -> SessionInfo:
    ua, ip = client_meta(request)
    issued = org_service.accept_invite(
        db, body.token, name=body.name, password=body.password, user_agent=ua, ip=ip
    )
    set_session_cookie(response, issued.token)
    request.cookies[SESSION_COOKIE] = issued.token
    return session_info(db, request)
