"""Cryptographic helpers: tokens, password hashing, TOTP, CSRF, signed links (SPEC §4.1, §8)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache
from importlib import resources

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

PASSWORD_MIN = 12
PASSWORD_MAX = 128
RECOVERY_CODE_COUNT = 10

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters


def new_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    """Tokens are high-entropy, so a fast hash is appropriate (no need for argon2)."""
    return hashlib.sha256(token.encode("utf-8")).digest()


# --------------------------------------------------------------------------- passwords


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Constant work whether or not the user exists (no enumeration by timing)."""
    try:
        return _hasher.verify(stored or _dummy_hash(), password) and stored is not None
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    text = resources.files("app.core.data").joinpath("common_passwords.txt").read_text("utf-8")
    return frozenset(
        line.strip().casefold() for line in text.splitlines() if line and not line.startswith("#")
    )


def password_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """Returns a user-facing problem, or None if the password is acceptable.

    SPEC §4.1: 12–128 chars, no composition rules, reject breached/common passwords.
    """
    if len(password) < PASSWORD_MIN:
        return f"Use at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"Use at most {PASSWORD_MAX} characters."
    folded = password.casefold()
    if folded in _common_passwords():
        return "This password appears in lists of breached passwords. Choose another."
    local = email.split("@", 1)[0].casefold()
    if local and len(local) >= 4 and folded == local:
        return "Do not use your email address as your password."
    if name and folded == name.casefold():
        return "Do not use your name as your password."
    return None


# --------------------------------------------------------------------------- TOTP


def _fernet() -> Fernet:
    return Fernet(get_settings().totp_encryption_key.get_secret_value().encode())


def new_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def decrypt_secret(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken as exc:  # pragma: no cover - key rotation problem, fail loudly
        raise RuntimeError("cannot decrypt TOTP secret; check RL_TOTP_ENCRYPTION_KEY") from exc


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().product_name)


def verify_totp(
    secret: str, code: str, last_timestep: int | None, now: float | None = None
) -> int | None:
    """Returns the matched timestep, or None. Rejects codes at or before the last used
    timestep (replay protection). Accepts ±1 step of clock drift."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    t = time.time() if now is None else now
    current = int(t) // totp.interval
    for step in (current - 1, current, current + 1):
        if last_timestep is not None and step <= last_timestep:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def new_recovery_codes() -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalise_recovery_code(code: str) -> str:
    cleaned = code.strip().lower().replace(" ", "").replace("-", "")
    return f"{cleaned[:5]}-{cleaned[5:]}" if len(cleaned) == 10 else cleaned


# --------------------------------------------------------------------------- CSRF + signed links


def _key() -> bytes:
    return get_settings().signing_key.get_secret_value().encode()


def csrf_token_for(session_id: str) -> str:
    return hmac.new(_key(), f"csrf:{session_id}".encode(), hashlib.sha256).hexdigest()


def check_csrf(session_id: str, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(csrf_token_for(session_id), presented)


def sign(purpose: str, data: dict[str, str], ttl_seconds: int, now: float | None = None) -> str:
    """Compact signed token: base64(json).hmac — used for unsubscribe/download links."""
    payload = {"p": purpose, "d": data, "e": int((now or time.time()) + ttl_seconds)}
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    )
    mac = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def unsign(purpose: str, token: str, now: float | None = None) -> dict[str, str] | None:
    body, _, mac = token.partition(".")
    if not body or not mac:
        return None
    expected = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError, json.JSONDecodeError:  # pragma: no cover - mac already verified
        return None
    if payload.get("p") != purpose or int(payload.get("e", 0)) < (now or time.time()):
        return None
    data = payload.get("d")
    return data if isinstance(data, dict) else None
