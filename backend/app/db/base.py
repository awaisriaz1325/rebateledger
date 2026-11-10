"""Declarative base, naming conventions and shared column mixins (SPEC §5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, MetaData, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

SCHEMA = "rl"

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Annotated[Decimal, mapped_column(Numeric(18, 4))]
Rate = Annotated[Decimal, mapped_column(Numeric(9, 6))]
Quantity = Annotated[Decimal, mapped_column(Numeric(18, 4))]
Str200 = Annotated[str, mapped_column(String(200))]
Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]


def new_id() -> uuid.UUID:
    return uuid.uuid7()


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSON().with_variant(JSONB(), "postgresql")
    }


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """Every table with customer data. RLS policy is added in the migration."""

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE"), index=True, nullable=False
        )


class AuthorMixin:
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class VersionedMixin:
    """Optimistic locking: ETag = row_version; SQLAlchemy also checks it on UPDATE."""

    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)

    @declared_attr.directive
    @classmethod
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.row_version}  # type: ignore[attr-defined]
