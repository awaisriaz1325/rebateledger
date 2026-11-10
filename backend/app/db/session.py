"""Engine/session factory and per-transaction tenant context for Row-Level Security.

The app connects as ``rl_app`` (no BYPASSRLS). Every transaction that touches
tenant data calls :func:`set_tenant_context`, which uses ``set_config(..., true)``
so the value is transaction-local and can never leak to the next request on a
pooled connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,  # never put row values or emails into logs/errors
        pool_size=10,
        max_overflow=10,
        connect_args={"options": "-c search_path=rl -c statement_timeout=60000"},
    )


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def set_tenant_context(db: Session, tenant_id: UUID | None) -> None:
    db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": "" if tenant_id is None else str(tenant_id)},
    )


def set_platform_context(db: Session, enabled: bool) -> None:
    """Lets platform admins read tenant *metadata* tables (never business data)."""
    db.execute(
        text("SELECT set_config('app.platform_admin', :v, true)"), {"v": "on" if enabled else ""}
    )


def set_user_context(db: Session, user_id: UUID | None) -> None:
    """Lets a user list their own memberships across tenants (org switcher)."""
    db.execute(
        text("SELECT set_config('app.user_id', :u, true)"),
        {"u": "" if user_id is None else str(user_id)},
    )


@contextmanager
def tenant_session(tenant_id: UUID | None) -> Iterator[Session]:
    """A transaction with tenant context set — for workers and scripts."""
    with session_factory()() as db, db.begin():
        set_tenant_context(db, tenant_id)
        yield db
