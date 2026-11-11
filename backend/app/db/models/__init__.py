"""Import every model module so Base.metadata is complete (Alembic, tests)."""

from app.db.models import business, identity, runs  # noqa: F401
