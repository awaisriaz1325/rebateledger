"""End-to-end test fixtures: a fresh tenant with MFA-enrolled users (local/test only).

Every call creates new, uniquely named users so repeated E2E runs never collide.
Credentials are random and returned to the caller (the Playwright global setup),
which keeps them in a git-ignored file. Refuses to run in staging or production.
"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.security import encrypt_secret, hash_password, new_totp_secret
from app.db.models.business import Plan, Subscription, Supplier, SupplierAlias
from app.db.models.identity import Membership, MfaFactor, Tenant, User


def seed_e2e() -> dict[str, Any]:
    settings = get_settings()
    if settings.is_production_like:
        raise SystemExit("seed-e2e refuses to run in staging or production")
    url = settings.migration_database_url
    if url is None:
        raise SystemExit("RL_MIGRATION_DATABASE_URL (owner role) is required")
    tag = secrets.token_hex(4)
    engine = create_engine(url.get_secret_value(), hide_parameters=True)
    users: dict[str, dict[str, str]] = {}
    try:
        with Session(engine) as db, db.begin():
            tenant = Tenant(name=f"E2E Distribution {tag}", timezone="America/Chicago")
            db.add(tenant)
            db.flush()
            plan = db.execute(select(Plan).where(Plan.code == "growth")).scalar_one()
            db.add(
                Subscription(
                    tenant_id=tenant.id, plan_id=plan.id, status="pilot", term_start=utcnow().date()
                )
            )
            for role in ("owner", "admin"):
                password, totp = secrets.token_urlsafe(16), new_totp_secret()
                email = f"e2e-{role}-{tag}@example.com"
                user = User(
                    email=email,
                    name=f"E2E {role.title()}",
                    password_hash=hash_password(password),
                    email_verified_at=utcnow(),
                    password_changed_at=utcnow(),
                )
                db.add(user)
                db.flush()
                db.add(
                    MfaFactor(
                        user_id=user.id,
                        secret_encrypted=encrypt_secret(totp),
                        confirmed_at=utcnow(),
                    )
                )
                db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
                users[role] = {"email": email, "password": password, "totp_secret": totp}
            supplier = Supplier(tenant_id=tenant.id, name="Acme Electrical Supply")
            db.add(supplier)
            db.flush()
            db.add(SupplierAlias(tenant_id=tenant.id, supplier_id=supplier.id, code="ACME"))
            tenant_id = str(tenant.id)
    finally:
        engine.dispose()
    return {"tag": tag, "tenant_id": tenant_id, "users": users, "supplier_code": "ACME"}
