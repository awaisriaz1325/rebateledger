"""Advisor portfolio view (v1.3 Phase 29): a summary row per organization the user belongs to.

Isolation: every organization is read in its own transaction with its own tenant context, so
row-level security applies exactly as when the user switches to it. No query spans tenants.
An organization that requires two-factor sign-in is locked (no numbers) for a user without it,
matching ``auth.switch_tenant``; an active session of a user who has it has verified it at login.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.db.models.identity import Tenant, User
from app.db.models.runs import TERMINAL_CLAIM, CalculationRun, Claim, RunStatus
from app.db.session import tenant_session
from app.engine.reconcile import ReconStatus
from app.services import auth
from app.services.reconciliation import live_items

ZERO = Decimal("0.00")


def _summary(tenant_id: uuid.UUID) -> dict[str, Any]:
    with tenant_session(tenant_id) as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant is not None
        variance, missing, short = ZERO, 0, 0
        for li in live_items(db, tenant):
            st, v = li.item.status, li.item.variance
            if st in (ReconStatus.SHORT_PAID, ReconStatus.MISSING) and v is not None:
                variance += -v
                missing += st is ReconStatus.MISSING
                short += st is ReconStatus.SHORT_PAID
        open_claims = db.execute(
            select(func.count()).where(
                Claim.tenant_id == tenant_id,
                Claim.status.not_in([s.value for s in TERMINAL_CLAIM]),
            )
        ).scalar_one()
        last_run: datetime | None = db.execute(
            select(func.max(CalculationRun.finished_at)).where(
                CalculationRun.tenant_id == tenant_id,
                CalculationRun.status == RunStatus.SUCCEEDED.value,
            )
        ).scalar_one()
    return {
        "identified_open_variance": format(variance.quantize(Decimal("0.01")), "f"),
        "missing": missing,
        "short_paid": short,
        "open_claims": int(open_claims),
        "last_run_at": last_run,
    }


def portfolio(user_id: uuid.UUID, current_tenant_id: uuid.UUID | None) -> list[dict[str, Any]]:
    with tenant_session(None) as db:
        user = db.get(User, user_id)
        assert user is not None
        enrolled = auth.has_mfa(db, user_id)
        orgs = [
            (t.id, t.name, m.role, auth.mfa_required(db, user, t, m.role) and not enrolled)
            for m, t in auth.active_memberships(db, user_id)
        ]
    empty = dict.fromkeys(
        ("identified_open_variance", "missing", "short_paid", "open_claims", "last_run_at")
    )
    return [
        {
            "tenant_id": tid,
            "name": name,
            "role": role,
            "current": tid == current_tenant_id,
            "locked": locked,
            **(empty if locked else _summary(tid)),
        }
        for tid, name, role, locked in orgs
    ]
