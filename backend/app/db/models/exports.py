"""Generated files: report exports, claim evidence packs and full data exports (SPEC §4.10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base, IdMixin, TenantMixin


class ExportKind(StrEnum):
    REPORT = "report"
    EVIDENCE_PACK = "evidence_pack"
    FULL_EXPORT = "full_export"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


def _in(column: str, values: list[str]) -> CheckConstraint:
    joined = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=f"{column}_valid")


class Export(IdMixin, TenantMixin, Base):
    """One requested file. The file lives in object storage under a tenant-prefixed key and
    is only downloadable through an authorised, short-lived signed link."""

    __tablename__ = "exports"
    __table_args__ = (
        _in("kind", [k.value for k in ExportKind]),
        _in("status", [s.value for s in ExportStatus]),
        _in("format", ["csv", "xlsx", "pdf", "zip"]),
        Index("ix_exports_tenant_created", "tenant_id", "created_at"),
    )

    kind: Mapped[str] = mapped_column(String(20))
    report: Mapped[str] = mapped_column(String(40), default="")
    format: Mapped[str] = mapped_column(String(10))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default=ExportStatus.QUEUED.value)
    filename: Mapped[str] = mapped_column(String(200), default="")
    storage_key: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(Integer)
    job_id: Mapped[uuid.UUID | None]
    requested_by: Mapped[uuid.UUID]
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
