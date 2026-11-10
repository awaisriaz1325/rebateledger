"""Authentication, sessions, MFA and account flows (SPEC §4.1)."""

from __future__ import annotations

import hmac
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import AppError, invalid
from app.core.permissions import MFA_REQUIRED_ROLES
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    needs_rehash,
    new_recovery_codes,
    new_token,
    new_totp_secret,
    normalise_recovery_code,
    password_problem,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.db.models.identity import (
    EmailToken,
    EmailTokenType,
    Membership,
    MembershipStatus,
    MfaFactor,
    PlatformAdmin,
    RecoveryCode,
    Role,
    SessionState,
    Tenant,
    User,
    UserSession,
)
from app.db.session import session_factory, set_tenant_context, set_user_context
from app.emails.service import queue_email
from app.services.audit import Actor, record

GENERIC_LOGIN_ERROR = (
    "Email or password is incorrect, or the account is temporarily locked. "
    "Try again later or reset your password."
)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _invalid_credentials() -> AppError:
    return AppError(401, "INVALID_CREDENTIALS", "Sign-in failed", GENERIC_LOGIN_ERROR)


@dataclass
class IssuedSession:
    token: str
    session: UserSession


# --------------------------------------------------------------------------- helpers


def is_platform_admin(db: Session, user_id: uuid.UUID) -> bool:
    return db.get(PlatformAdmin, user_id) is not None


def active_memberships(db: Session, user_id: uuid.UUID) -> list[tuple[Membership, Tenant]]:
    """All of a user's active memberships (uses the own_memberships RLS policy)."""
    set_user_context(db, user_id)
    rows = db.execute(
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE.value)
        .order_by(Tenant.name)
    ).all()
    return [(m, t) for m, t in rows]


def mfa_factor(db: Session, user_id: uuid.UUID) -> MfaFactor | None:
    return db.execute(select(MfaFactor).where(MfaFactor.user_id == user_id)).scalar_one_or_none()


def has_mfa(db: Session, user_id: uuid.UUID) -> bool:
    f = mfa_factor(db, user_id)
    return f is not None and f.confirmed_at is not None


def mfa_required(db: Session, user: User, tenant: Tenant | None, role: str | None) -> bool:
    if is_platform_admin(db, user.id):
        return True
    if role is not None and Role(role) in MFA_REQUIRED_ROLES:
        return True
    return bool(tenant and tenant.require_mfa_all)


def _create_session(
    db: Session,
    user: User,
    state: SessionState,
    *,
    tenant_id: uuid.UUID | None,
    idle_minutes: int,
    user_agent: str,
    ip: str,
    is_platform: bool,
    mfa_verified: bool,
) -> IssuedSession:
    now = utcnow()
    token = new_token()
    s = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        state=state.value,
        active_tenant_id=tenant_id,
        is_platform=is_platform,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=get_settings().session_absolute_hours),
        idle_minutes=idle_minutes,
        mfa_verified_at=now if mfa_verified else None,
        user_agent=user_agent[:400],
        ip=ip[:64],
    )
    db.add(s)
    db.flush()
    return IssuedSession(token, s)


def rotate(db: Session, s: UserSession) -> str:
    """New token for the same session (login completion, MFA, privilege change)."""
    token = new_token()
    s.token_hash = hash_token(token)
    return token


def revoke_all_sessions(
    db: Session, user_id: uuid.UUID, reason: str, *, except_id: uuid.UUID | None = None
) -> int:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )
    if except_id is not None:
        stmt = stmt.where(UserSession.id != except_id)
    return db.execute(stmt).rowcount  # type: ignore[attr-defined, no-any-return]


def security_notice(
    db: Session, user: User, headline: str, detail: str, *, to: str | None = None
) -> None:
    """Security notifications cannot be disabled (SPEC §4.1)."""
    queue_email(
        db,
        to=to or user.email,
        template="security_notice",
        context={
            "headline": headline,
            "detail": detail,
            "when": utcnow().strftime("%Y-%m-%d %H:%M"),
            "reset_url": f"{get_settings().app_base_url}/forgot-password",
        },
    )


def _record_failure(user_id: uuid.UUID) -> None:
    """Persist a failed attempt in its own transaction (the request will roll back)."""
    s = get_settings()
    with session_factory()() as db, db.begin():
        user = db.get(User, user_id, with_for_update=True)
        if user is None:  # pragma: no cover
            return
        now = utcnow()
        user.failed_login_count += 1
        user.last_failed_login_at = now
        if user.failed_login_count >= s.lockout_failures:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_login_count = 0


def _progressive_delay(email: str) -> None:
    """After 3 failures for an email (known or not), wait 2^(n-3) s between tries (≤ 60 s)."""
    client = ratelimit.client()
    key = "rl:loginfail:" + hash_token(email).hex()[:32]
    raw = client.hgetall(key)
    if not raw:
        return
    fails = int(raw.get(b"n", b"0"))
    last = float(raw.get(b"t", b"0"))
    if fails >= 3:
        wait = min(2 ** (fails - 3), 60)
        remaining = last + wait - time.time()
        if remaining > 0:
            secs = max(int(remaining + 0.999), 1)
            raise AppError(
                429,
                "RATE_LIMITED",
                "Too many requests",
                f"Too many attempts. Try again in {secs} seconds.",
                headers={"Retry-After": str(secs)},
            )


def _note_failure(email: str) -> None:
    client = ratelimit.client()
    key = "rl:loginfail:" + hash_token(email).hex()[:32]
    pipe = client.pipeline()
    pipe.hincrby(key, "n", 1)
    pipe.hset(key, "t", str(time.time()))
    pipe.expire(key, 15 * 60)
    pipe.execute()


def _clear_failures(email: str) -> None:
    ratelimit.client().delete("rl:loginfail:" + hash_token(email).hex()[:32])


# --------------------------------------------------------------------------- login


def login(db: Session, email: str, password: str, *, user_agent: str, ip: str) -> IssuedSession:
    email = normalise_email(email)
    ratelimit.hit("login-ip", ip or "unknown", 30, 300)
    ratelimit.hit("login-email", email, 20, 900)
    _progressive_delay(email)

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else None, password)
    now = utcnow()
    if (
        user is None
        or not ok
        or user.disabled_at is not None
        or (user.locked_until is not None and user.locked_until > now)
    ):
        _note_failure(email)
        if user is not None and not ok:
            _record_failure(user.id)
        raise _invalid_credentials()

    _clear_failures(email)
    user.failed_login_count = 0
    user.locked_until = None
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    platform = is_platform_admin(db, user.id)
    memberships = [] if platform else active_memberships(db, user.id)
    if not platform and not memberships:
        # A user with no active organization cannot do anything; same generic error.
        raise _invalid_credentials()
    tenant: Tenant | None = None
    role: str | None = None
    if memberships:
        preferred = user.preferences.get("last_tenant_id")
        chosen = next((mt for mt in memberships if str(mt[1].id) == preferred), memberships[0])
        role, tenant = chosen[0].role, chosen[1]

    if has_mfa(db, user.id):
        state = SessionState.PENDING_MFA
    elif mfa_required(db, user, tenant, role):
        state = SessionState.PENDING_ENROLLMENT
    else:
        state = SessionState.ACTIVE
    issued = _create_session(
        db,
        user,
        state,
        tenant_id=tenant.id if tenant else None,
        idle_minutes=tenant.session_idle_minutes
        if tenant
        else get_settings().session_idle_minutes_default,
        user_agent=user_agent,
        ip=ip,
        is_platform=platform,
        mfa_verified=False,
    )
    if state is SessionState.ACTIVE:
        _after_full_login(db, user, issued.session)
    return issued


def _after_full_login(db: Session, user: User, s: UserSession) -> None:
    seen = db.execute(
        select(UserSession.id)
        .where(
            UserSession.user_id == user.id,
            UserSession.user_agent == s.user_agent,
            UserSession.id != s.id,
            UserSession.mfa_verified_at.is_not(None)
            | (UserSession.state == SessionState.ACTIVE.value),
        )
        .limit(1)
    ).first()
    if seen is None:
        security_notice(
            db,
            user,
            "New sign-in to your account",
            f"A new device signed in: {s.user_agent or 'unknown browser'}.",
        )
    if s.active_tenant_id:
        set_tenant_context(db, s.active_tenant_id)
        record(
            db,
            tenant_id=s.active_tenant_id,
            actor=Actor("user", user.id, user.email),
            action="auth.login",
            object_type="session",
            object_id=s.id,
        )


def complete_mfa(
    db: Session, s: UserSession, user: User, *, code: str | None, recovery_code: str | None
) -> str:
    if s.state != SessionState.PENDING_MFA.value:
        raise AppError(
            409, "MFA_NOT_PENDING", "MFA not pending", "This session is not waiting for a code."
        )
    ratelimit.hit("mfa", str(user.id), 10, 300)
    factor = mfa_factor(db, user.id)
    assert factor is not None and factor.confirmed_at is not None
    used_recovery = False
    if code:
        step = verify_totp(decrypt_secret(factor.secret_encrypted), code, factor.last_used_timestep)
        if step is None:
            raise AppError(
                401,
                "MFA_INVALID",
                "Code not accepted",
                "The code is wrong or already used. Use the newest code from your app.",
            )
        factor.last_used_timestep = step
    elif recovery_code:
        wanted = hash_token(normalise_recovery_code(recovery_code))
        rc = next(
            (
                r
                for r in db.execute(
                    select(RecoveryCode).where(
                        RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
                    )
                ).scalars()
                if hmac.compare_digest(r.code_hash, wanted)
            ),
            None,
        )
        if rc is None:
            raise AppError(
                401,
                "MFA_INVALID",
                "Code not accepted",
                "That recovery code is wrong or already used.",
            )
        rc.used_at = utcnow()
        user.must_reenroll_mfa = True
        used_recovery = True
    else:
        raise invalid(
            "MFA_CODE_REQUIRED", "Enter a code from your authenticator app or a recovery code."
        )
    s.state = SessionState.ACTIVE.value
    s.mfa_verified_at = utcnow()
    token = rotate(db, s)
    if used_recovery:
        security_notice(
            db,
            user,
            "A recovery code was used",
            "Someone signed in with one of your MFA recovery codes. Set up your authenticator again and create new recovery codes.",
        )
    _after_full_login(db, user, s)
    return token


# --------------------------------------------------------------------------- MFA enrollment


def start_enrollment(db: Session, user: User) -> tuple[str, str]:
    factor = mfa_factor(db, user.id)
    if factor is not None and factor.confirmed_at is not None and not user.must_reenroll_mfa:
        raise AppError(
            409,
            "MFA_ALREADY_ENABLED",
            "MFA already enabled",
            "Disable MFA first to set up a new authenticator.",
        )
    secret = new_totp_secret()
    if factor is None:
        factor = MfaFactor(user_id=user.id, secret_encrypted=encrypt_secret(secret))
        db.add(factor)
    else:
        factor.secret_encrypted = encrypt_secret(secret)
        factor.confirmed_at = None
        factor.last_used_timestep = None
    db.flush()
    return secret, totp_uri(secret, user.email)


def confirm_enrollment(db: Session, user: User, s: UserSession, code: str) -> tuple[list[str], str]:
    ratelimit.hit("mfa", str(user.id), 10, 300)
    factor = mfa_factor(db, user.id)
    if factor is None or (factor.confirmed_at is not None and not user.must_reenroll_mfa):
        raise AppError(
            409, "MFA_NOT_STARTED", "No enrollment in progress", "Start MFA setup first."
        )
    step = verify_totp(decrypt_secret(factor.secret_encrypted), code, None)
    if step is None:
        raise AppError(
            401,
            "MFA_INVALID",
            "Code not accepted",
            "The code is wrong. Check your device clock and try the newest code.",
        )
    factor.confirmed_at = utcnow()
    factor.last_used_timestep = step
    user.must_reenroll_mfa = False
    codes = replace_recovery_codes(db, user)
    s.state = SessionState.ACTIVE.value
    s.mfa_verified_at = utcnow()
    token = rotate(db, s)
    security_notice(
        db,
        user,
        "Two-factor authentication enabled",
        "An authenticator app was set up for your account.",
    )
    return codes, token


def replace_recovery_codes(db: Session, user: User) -> list[str]:
    for rc in db.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id)).scalars():
        db.delete(rc)
    codes = new_recovery_codes()
    for c in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_token(c)))
    db.flush()
    return codes


def disable_mfa(db: Session, user: User, roles_requiring: bool) -> None:
    if roles_requiring:
        raise AppError(
            409,
            "MFA_REQUIRED_FOR_ROLE",
            "MFA is required",
            "Your role requires two-factor authentication, so it cannot be turned off.",
        )
    factor = mfa_factor(db, user.id)
    if factor is not None:
        db.delete(factor)
    for rc in db.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id)).scalars():
        db.delete(rc)
    revoke_all_sessions(db, user.id, "mfa_disabled")
    security_notice(
        db,
        user,
        "Two-factor authentication disabled",
        "Two-factor authentication was turned off for your account.",
    )


# --------------------------------------------------------------------------- sessions


def resolve(db: Session, token: str | None) -> tuple[UserSession, User] | None:
    if not token or len(token) > 100:
        return None
    s = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if s is None or s.revoked_at is not None:
        return None
    now = utcnow()
    if s.expires_at <= now:
        s.revoked_at, s.revoked_reason = now, "expired"
        return None
    if s.last_seen_at + timedelta(minutes=s.idle_minutes) <= now:
        s.revoked_at, s.revoked_reason = now, "idle"
        return None
    if (now - s.last_seen_at) > timedelta(seconds=30):
        s.last_seen_at = now
    user = db.get(User, s.user_id)
    if user is None or user.disabled_at is not None:
        return None
    return s, user


def step_up(db: Session, s: UserSession, user: User, password: str, code: str | None) -> None:
    ratelimit.hit("stepup", str(user.id), 10, 300)
    if not verify_password(user.password_hash, password):
        raise AppError(
            401, "STEP_UP_FAILED", "Re-authentication failed", "The password is incorrect."
        )
    factor = mfa_factor(db, user.id)
    if factor is not None and factor.confirmed_at is not None:
        step = verify_totp(
            decrypt_secret(factor.secret_encrypted), code or "", factor.last_used_timestep
        )
        if step is None:
            raise AppError(
                401,
                "STEP_UP_FAILED",
                "Re-authentication failed",
                "The authenticator code is wrong or already used.",
            )
        factor.last_used_timestep = step
    s.stepped_up_at = utcnow()


def require_recent_step_up(s: UserSession) -> None:
    window = timedelta(minutes=get_settings().step_up_minutes)
    if s.stepped_up_at is None or utcnow() - s.stepped_up_at > window:
        raise AppError(
            403,
            "STEP_UP_REQUIRED",
            "Confirm it's you",
            "Re-enter your password (and authenticator code) to continue.",
        )


def switch_tenant(db: Session, s: UserSession, user: User, tenant_id: uuid.UUID) -> str:
    match = next((mt for mt in active_memberships(db, user.id) if mt[1].id == tenant_id), None)
    if match is None:
        raise AppError(404, "NOT_FOUND", "Organization not found")
    membership, tenant = match
    s.active_tenant_id = tenant.id
    s.idle_minutes = tenant.session_idle_minutes
    if mfa_required(db, user, tenant, membership.role) and not has_mfa(db, user.id):
        s.state = SessionState.PENDING_ENROLLMENT.value
    user.preferences = {**user.preferences, "last_tenant_id": str(tenant.id)}
    return rotate(db, s)


# --------------------------------------------------------------------------- email tokens


def _issue_email_token(
    db: Session, user: User, kind: EmailTokenType, ttl: timedelta, new_email: str | None = None
) -> str:
    token = new_token()
    db.add(
        EmailToken(
            user_id=user.id,
            type=kind.value,
            token_hash=hash_token(token),
            new_email=new_email,
            expires_at=utcnow() + ttl,
        )
    )
    db.flush()
    return token


def _consume_email_token(db: Session, token: str, kind: EmailTokenType) -> EmailToken:
    et = db.execute(
        select(EmailToken)
        .where(EmailToken.token_hash == hash_token(token), EmailToken.type == kind.value)
        .with_for_update()
    ).scalar_one_or_none()
    if et is None or et.used_at is not None or et.expires_at <= utcnow():
        raise AppError(
            400,
            "TOKEN_INVALID",
            "Link not valid",
            "This link is invalid, expired or already used. Request a new one.",
        )
    et.used_at = utcnow()
    return et


def forgot_password(db: Session, email: str, ip: str) -> None:
    """Always the same response; similar work whether or not the account exists."""
    email = normalise_email(email)
    ratelimit.hit("reset-ip", ip or "unknown", 10, 3600)
    ratelimit.hit("reset-email", email, 5, 3600)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or user.disabled_at is not None:
        hash_token(new_token())
        return
    s = get_settings()
    token = _issue_email_token(
        db, user, EmailTokenType.RESET_PASSWORD, timedelta(minutes=s.reset_ttl_minutes)
    )
    queue_email(
        db,
        to=user.email,
        template="password_reset",
        context={
            "url": f"{s.app_base_url}/reset-password?token={token}",
            "ttl_minutes": s.reset_ttl_minutes,
        },
    )


def reset_password(db: Session, token: str, new_password: str) -> None:
    et = _consume_email_token(db, token, EmailTokenType.RESET_PASSWORD)
    user = db.get(User, et.user_id)
    assert user is not None
    _set_password(db, user, new_password)
    user.failed_login_count = 0
    user.locked_until = None
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()  # the reset link proves control of the address
    revoke_all_sessions(db, user.id, "password_reset")
    security_notice(
        db,
        user,
        "Your password was changed",
        "Your password was reset using a link sent to this address. All sessions were signed out.",
    )


def _set_password(db: Session, user: User, new_password: str) -> None:
    problem = password_problem(new_password, email=user.email, name=user.name)
    if problem:
        raise invalid("WEAK_PASSWORD", problem, "password")
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()


def change_password(
    db: Session, s: UserSession, user: User, current: str, new_password: str
) -> str:
    ratelimit.hit("pwchange", str(user.id), 10, 3600)
    if not verify_password(user.password_hash, current):
        raise invalid("WRONG_PASSWORD", "Your current password is incorrect.", "current_password")
    _set_password(db, user, new_password)
    revoke_all_sessions(db, user.id, "password_changed", except_id=s.id)
    security_notice(
        db,
        user,
        "Your password was changed",
        "Your password was changed and your other sessions were signed out.",
    )
    return rotate(db, s)


def send_verification(db: Session, user: User) -> None:
    s = get_settings()
    token = _issue_email_token(
        db, user, EmailTokenType.VERIFY_EMAIL, timedelta(hours=s.verify_ttl_hours)
    )
    queue_email(
        db,
        to=user.email,
        template="verify_email",
        context={"url": f"{s.app_base_url}/verify-email?token={token}"},
    )


def verify_email(db: Session, token: str) -> None:
    et = _consume_email_token(db, token, EmailTokenType.VERIFY_EMAIL)
    user = db.get(User, et.user_id)
    assert user is not None
    user.email_verified_at = utcnow()


def request_email_change(db: Session, user: User, new_email: str, password: str) -> None:
    ratelimit.hit("emailchange", str(user.id), 5, 3600)
    if not verify_password(user.password_hash, password):
        raise invalid("WRONG_PASSWORD", "Your password is incorrect.", "password")
    new_email = normalise_email(new_email)
    if new_email == user.email:
        raise invalid("EMAIL_UNCHANGED", "That is already your email address.", "new_email")
    s = get_settings()
    # Do not reveal whether the new address is taken; the confirmation step checks again.
    token = _issue_email_token(
        db, user, EmailTokenType.CHANGE_EMAIL, timedelta(hours=s.verify_ttl_hours), new_email
    )
    queue_email(
        db,
        to=new_email,
        template="change_email",
        context={"url": f"{s.app_base_url}/confirm-email-change?token={token}"},
    )
    security_notice(
        db,
        user,
        "Email change requested",
        f"A change of your sign-in email to {new_email} was requested. It takes effect only after confirmation.",
    )


def confirm_email_change(db: Session, token: str) -> None:
    et = _consume_email_token(db, token, EmailTokenType.CHANGE_EMAIL)
    user = db.get(User, et.user_id)
    assert user is not None and et.new_email
    if db.execute(select(User.id).where(User.email == et.new_email)).first():
        raise AppError(
            409,
            "EMAIL_TAKEN",
            "Email unavailable",
            "That email address can't be used. Contact support if you think this is a mistake.",
        )
    old = user.email
    user.email = et.new_email
    user.email_verified_at = utcnow()
    security_notice(
        db,
        user,
        "Your sign-in email was changed",
        f"Your sign-in email was changed to {et.new_email}.",
        to=old,
    )
    revoke_all_sessions(db, user.id, "email_changed")


def list_sessions(db: Session, user_id: uuid.UUID) -> list[UserSession]:
    now = utcnow()
    rows = (
        db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.last_seen_at.desc())
        )
        .scalars()
        .all()
    )
    return [r for r in rows if r.last_seen_at + timedelta(minutes=r.idle_minutes) > now]


def revoke_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    s = db.get(UserSession, session_id)
    if s is None or s.user_id != user_id or s.revoked_at is not None:
        raise AppError(404, "NOT_FOUND", "Session not found")
    s.revoked_at, s.revoked_reason = utcnow(), "user_revoked"


def login_after_signup(
    db: Session, user: User, tenant: Tenant, role: str, *, user_agent: str, ip: str
) -> IssuedSession:
    """Session right after accepting an invite (the password was just set or confirmed)."""
    if has_mfa(db, user.id):
        state = SessionState.PENDING_MFA
    elif mfa_required(db, user, tenant, role):
        state = SessionState.PENDING_ENROLLMENT
    else:
        state = SessionState.ACTIVE
    issued = _create_session(
        db,
        user,
        state,
        tenant_id=tenant.id,
        idle_minutes=tenant.session_idle_minutes,
        user_agent=user_agent,
        ip=ip,
        is_platform=False,
        mfa_verified=False,
    )
    if state is SessionState.ACTIVE:
        _after_full_login(db, user, issued.session)
    return issued
