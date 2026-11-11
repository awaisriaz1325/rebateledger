"""Claims (Phase 4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models.business import Approval


def apply_write_off_decision(db: Session, ctx: Any, approval: Approval, approve: bool) -> None:
    raise NotImplementedError("claim write-offs arrive with claims in Phase 4")
