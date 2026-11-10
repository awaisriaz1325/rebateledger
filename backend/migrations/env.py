"""Alembic environment. Runs as the owner role (RL_MIGRATION_DATABASE_URL)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text

import app.db.models  # noqa: F401  (registers every table)
from app.core.config import get_settings
from app.db.base import SCHEMA, Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    settings = get_settings()
    url = settings.migration_database_url
    if url is None:
        raise RuntimeError("RL_MIGRATION_DATABASE_URL is required to run migrations")
    engine = create_engine(url.get_secret_value())
    with engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.execute(text(f"SET search_path TO {SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_object=lambda obj, name, type_, reflected, compare_to: (
                name != "alembic_version"
            ),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
