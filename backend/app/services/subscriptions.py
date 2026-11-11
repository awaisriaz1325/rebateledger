"""Subscription status and plan limits (SPEC §4.14).

Exceeding a limit blocks only the new action with a clear message; existing data
stays accessible. Suspended tenants are read-only (view + export allowed).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    ImportBatch,
    Plan,
    Subscription,
    SubscriptionStatus,
    VersionStatus,
)
from app.db.models.identity import Membership, MembershipStatus

LIMIT_FIELDS = ("max_active_agreements", "max_users", "max_import_rows_per_month", "max_storage_mb")


@dataclass(frozen=True)
class Limits:
    plan_code: str
    plan_name: str
    status: str
    max_active_agreements: int | None
    max_users: int | None
    max_import_rows_per_month: int | None
    max_storage_mb: int | None


def subscription(db: Session, tenant_id: uuid.UUID) -> Subscription | None:
    return db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    ).scalar_one_or_none()


def limits(db: Session, tenant_id: uuid.UUID) -> Limits | None:
    sub = subscription(db, tenant_id)
    if sub is None:
        return None
    plan = db.get(Plan, sub.plan_id)
    assert plan is not None
    values: dict[str, Any] = {f: getattr(plan, f) for f in LIMIT_FIELDS}
    values.update({k: v for k, v in sub.limit_overrides.items() if k in LIMIT_FIELDS})
    return Limits(plan.code, plan.name, sub.status, **values)


def is_read_only(db: Session, tenant_id: uuid.UUID) -> bool:
    sub = subscription(db, tenant_id)
    return sub is not None and sub.status in (
        SubscriptionStatus.SUSPENDED.value,
        SubscriptionStatus.CANCELLED.value,
    )


def usage(db: Session, tenant_id: uuid.UUID) -> dict[str, int]:
    active_agreements = db.execute(
        select(func.count(func.distinct(Agreement.id)))
        .join(AgreementVersion, AgreementVersion.agreement_id == Agreement.id)
        .where(
            Agreement.tenant_id == tenant_id,
            Agreement.status == "active",
            AgreementVersion.status == VersionStatus.ACTIVE.value,
        )
    ).scalar_one()
    users = db.execute(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == tenant_id, Membership.status == MembershipStatus.ACTIVE.value
        )
    ).scalar_one()
    month_start = utcnow().date().replace(day=1)
    rows = db.execute(
        select(func.coalesce(func.sum(ImportBatch.stats["rows_committed"].as_integer()), 0)).where(
            ImportBatch.tenant_id == tenant_id, ImportBatch.committed_at >= month_start
        )
    ).scalar_one()
    storage = db.execute(
        select(func.coalesce(func.sum(ImportBatch.size_bytes), 0)).where(
            ImportBatch.tenant_id == tenant_id
        )
    ).scalar_one()
    return {
        "active_agreements": int(active_agreements),
        "users": int(users),
        "import_rows_this_month": int(rows),
        "storage_mb": int(storage) // (1024 * 1024),
    }


def _limit_error(what: str, limit: int, plan: str) -> AppError:
    return AppError(
        403,
        "PLAN_LIMIT_REACHED",
        "Plan limit reached",
        f"Your {plan} plan allows {limit:,} {what}. Existing data is unaffected. Contact us to upgrade.",
        extra={"limit": limit},
    )


def check(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    agreements: int = 0,
    users: int = 0,
    import_rows: int = 0,
    storage_bytes: int = 0,
) -> None:
    """Raise if adding the given amounts would exceed the plan. No subscription = no limits (pre-provisioning)."""
    lim = limits(db, tenant_id)
    if lim is None:
        return
    use = usage(db, tenant_id)
    if (
        agreements
        and lim.max_active_agreements is not None
        and use["active_agreements"] + agreements > lim.max_active_agreements
    ):
        raise _limit_error("active agreements", lim.max_active_agreements, lim.plan_name)
    if users and lim.max_users is not None and use["users"] + users > lim.max_users:
        raise _limit_error("users", lim.max_users, lim.plan_name)
    if (
        import_rows
        and lim.max_import_rows_per_month is not None
        and use["import_rows_this_month"] + import_rows > lim.max_import_rows_per_month
    ):
        raise _limit_error("imported rows per month", lim.max_import_rows_per_month, lim.plan_name)
    if (
        storage_bytes
        and lim.max_storage_mb is not None
        and (use["storage_mb"] * 1024 * 1024 + storage_bytes) > lim.max_storage_mb * 1024 * 1024
    ):
        raise _limit_error("MB of stored files", lim.max_storage_mb, lim.plan_name)
