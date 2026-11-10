"""Subscription status checks used by write permissions (SPEC §4.14).

Phase 2 has no subscriptions yet, so nothing is read-only. Phase 3 replaces this
with the real lookup when plans and subscriptions are added.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session


def is_read_only(db: Session, tenant_id: uuid.UUID) -> bool:
    return False
