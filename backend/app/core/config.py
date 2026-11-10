"""Settings from the environment (12-factor). Startup fails if a required secret is missing."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class BreachedPasswordMode(StrEnum):
    OFFLINE = "offline"
    """Bundled common-password list only (default; no outbound HTTP from request paths)."""
    HIBP = "hibp"
    """HIBP k-anonymity range API, fail-open with a logged warning (needs an ADR to enable)."""
    OFF = "off"


class JobsMode(StrEnum):
    QUEUE = "queue"
    """Jobs go to Redis and run in the worker process."""
    INLINE = "inline"
    """Jobs run synchronously after commit (tests only)."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RL_", env_file=None, extra="ignore")

    env: Environment = Environment.LOCAL
    product_name: str = "RebateLedger"
    app_base_url: str = "http://localhost:3000"

    database_url: SecretStr
    """Application role (rl_app): no BYPASSRLS, does not own tables."""
    migration_database_url: SecretStr | None = None
    """Owner role (rl_owner): only used by Alembic."""
    redis_url: SecretStr = SecretStr("redis://localhost:6382/0")

    totp_encryption_key: SecretStr
    """Fernet key (urlsafe base64, 32 bytes) for TOTP secrets at rest."""
    signing_key: SecretStr = Field(min_length=32)
    """HMAC key for CSRF tokens, unsubscribe links and download links."""

    smtp_host: str = "localhost"
    smtp_port: int = 1026
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    email_from: str = "RebateLedger <no-reply@rebateledger.invalid>"
    ops_notification_email: str = "ops@rebateledger.invalid"

    storage_dir: Path = Path("var/storage")

    breached_password_mode: BreachedPasswordMode = BreachedPasswordMode.OFFLINE
    jobs_mode: JobsMode = JobsMode.QUEUE

    session_idle_minutes_default: int = 30
    session_absolute_hours: int = 12
    step_up_minutes: int = 10
    lockout_failures: int = 10
    lockout_minutes: int = 15
    invite_ttl_days: int = 7
    verify_ttl_hours: int = 24
    reset_ttl_minutes: int = 30
    platform_admin_ip_allowlist: list[str] = []
    trusted_origins: list[str] = []
    """Extra origins accepted by the CSRF Origin check (app_base_url is always accepted)."""

    @field_validator("app_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_production_like(self) -> bool:
        return self.env in (Environment.STAGING, Environment.PRODUCTION)

    @property
    def allowed_origins(self) -> set[str]:
        return {self.app_base_url, *(o.rstrip("/") for o in self.trusted_origins)}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
