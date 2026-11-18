"""mfa pending secret

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-18 12:00:00.000000

Security audit 2026-11-18 #1: re-enrollment keeps the confirmed authenticator until the new
one is confirmed. Locking review: mfa_factors has one row per user (small). Adding a nullable
column without a default is a catalog-only change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mfa_factors",
        sa.Column("pending_secret_encrypted", sa.LargeBinary(), nullable=True),
        schema="rl",
    )


def downgrade() -> None:
    op.drop_column("mfa_factors", "pending_secret_encrypted", schema="rl")
