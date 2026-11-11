"""Demo tenant seed (PHASES §3 item 5). Fake data only; refuses to run in staging/production.

Runs with the owner role (bulk load) and writes realistic suppliers, agreements,
~100k purchase lines, credits and a subscription. Prints a one-time password.
"""

from __future__ import annotations

import hashlib
import random
import secrets
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.business import (
    Agreement,
    AgreementVersion,
    CreditLineRow,
    ImportBatch,
    Plan,
    PurchaseLineRow,
    Subscription,
    Supplier,
    SupplierAlias,
    VersionStatus,
)
from app.db.models.identity import Membership, Tenant, User
from app.services.agreement_terms import VersionTermsIn, to_snapshot, write_rows

SUPPLIERS = [
    (
        "Northwind Electric",
        "NWE",
        ["WIRE", "BREAKER", "LIGHTING", "CONDUIT"],
        (Decimal("15"), Decimal("900")),
    ),
    (
        "Summit HVAC Supply",
        "SUMMIT",
        ["COMPRESSOR", "COIL", "CONTROLS"],
        (Decimal("80"), Decimal("2400")),
    ),
    (
        "Riverbend Plumbing Products",
        "RBP",
        ["PEX", "FITTINGS", "VALVES"],
        (Decimal("1"), Decimal("70")),
    ),
    (
        "Granite Building Materials",
        "GBM",
        ["DRYWALL", "INSULATION", "LUMBER"],
        (Decimal("8"), Decimal("400")),
    ),
    ("Beacon Lighting Co.", "BEACON", ["LED", "FIXTURE"], (Decimal("12"), Decimal("600"))),
]

BASE_TERMS = {
    "effective_to": None,
    "period_type": "quarterly",
    "fiscal_aligned": True,
    "date_basis": "invoice_date",
    "measure": "spend",
    "spend_basis": "net_of_returns",
    "threshold_comparison": "gte",
    "negative_result": "floor_at_zero",
    "rounding_mode": "half_up",
    "payment_terms_days": 60,
    "stacking": "stackable",
    "prorate_thresholds_on_partial_period": False,
    "zero_baseline_policy": "needs_review",
}


def _terms(i: int, start: date) -> VersionTermsIn:
    components: list[dict[str, object]]
    if i % 3 == 0:
        components = [
            {
                "key": "volume",
                "type": "tiered_all_units",
                "tiers": [
                    {"threshold": "400000", "rate": "0.02"},
                    {"threshold": "800000", "rate": "0.03"},
                ],
            }
        ]
    elif i % 3 == 1:
        components = [
            {"key": "base", "type": "flat_percent", "rate": "0.015"},
            {"key": "bonus", "type": "fixed_bonus", "amount": "2500", "threshold": "500000"},
        ]
    else:
        components = [
            {
                "key": "incremental",
                "type": "tiered_incremental",
                "tiers": [
                    {"threshold": "0", "rate": "0.01"},
                    {"threshold": "300000", "rate": "0.025"},
                ],
            }
        ]
    eligibility = (
        [{"key": "no-spa", "action": "exclude", "field": "flag", "flag": "special_pricing"}]
        if i % 2 == 0
        else []
    )
    return VersionTermsIn.model_validate(
        {
            **BASE_TERMS,
            "effective_from": start.isoformat(),
            "components": components,
            "eligibility": eligibility,
        }
    )


def seed_demo(purchase_lines: int, owner_email: str) -> str:
    settings = get_settings()
    if settings.is_production_like:
        raise SystemExit("seed-demo refuses to run in staging or production")
    url = settings.migration_database_url
    if url is None:
        raise SystemExit("RL_MIGRATION_DATABASE_URL (owner role) is required")
    # fake demo data only; not security relevant
    rng = random.Random(2026)  # noqa: S311  # nosec B311
    engine = create_engine(url.get_secret_value(), hide_parameters=True)
    password = secrets.token_urlsafe(12)
    today = utcnow().date()
    start = date(today.year - 1, 1, 1)
    try:
        with Session(engine) as db, db.begin():
            tenant = Tenant(
                name="Demo Distribution Co. (fake data)",
                timezone="America/Chicago",
                fiscal_year_start_month=1,
                is_demo=True,
            )
            db.add(tenant)
            db.flush()
            user = db.execute(select(User).where(User.email == owner_email)).scalar_one_or_none()
            if user is None:
                user = User(
                    email=owner_email,
                    name="Demo Owner",
                    password_hash=hash_password(password),
                    email_verified_at=utcnow(),
                    password_changed_at=utcnow(),
                )
                db.add(user)
                db.flush()
                note = f"Owner {owner_email} / one-time password: {password} (MFA set-up is required at first sign-in)"
            else:
                note = f"Existing user {owner_email} added as Owner"
            db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
            plan = db.execute(select(Plan).where(Plan.code == "growth")).scalar_one()
            db.add(
                Subscription(tenant_id=tenant.id, plan_id=plan.id, status="pilot", term_start=start)
            )
            batch = ImportBatch(
                tenant_id=tenant.id,
                import_type="purchases",
                status="committed",
                filename="demo-purchases.csv",
                file_format="csv",
                size_bytes=0,
                file_hash=hashlib.sha256(str(tenant.id).encode()).hexdigest(),
                storage_key="demo/none",
                committed_at=utcnow(),
                config={},
            )
            credit_batch = ImportBatch(
                tenant_id=tenant.id,
                import_type="credits",
                status="committed",
                filename="demo-credits.csv",
                file_format="csv",
                size_bytes=0,
                file_hash=hashlib.sha256(b"c" + str(tenant.id).encode()).hexdigest(),
                storage_key="demo/none",
                committed_at=utcnow(),
                config={},
            )
            db.add_all([batch, credit_batch])
            db.flush()
            supplier_ids = []
            for i, (name, code, cats, _) in enumerate(SUPPLIERS):
                s = Supplier(tenant_id=tenant.id, name=name, category_tags=cats[:2])
                db.add(s)
                db.flush()
                db.add(SupplierAlias(tenant_id=tenant.id, supplier_id=s.id, code=code))
                supplier_ids.append(s.id)
                a = Agreement(
                    tenant_id=tenant.id,
                    supplier_id=s.id,
                    name=f"{name} rebate program",
                    external_reference=f"{code}-REB",
                )
                db.add(a)
                db.flush()
                terms = _terms(i, start)
                v = AgreementVersion(
                    tenant_id=tenant.id,
                    agreement_id=a.id,
                    version_no=1,
                    status=VersionStatus.DRAFT.value,
                    effective_from=start,
                    period_type="quarterly",
                    fiscal_year_start_month=1,
                    date_basis="invoice_date",
                    measure="spend",
                    spend_basis="net_of_returns",
                    threshold_comparison="gte",
                    negative_result="floor_at_zero",
                    rounding_mode="half_up",
                    payment_terms_days=60,
                    stacking="stackable",
                    prorate_thresholds_on_partial_period=False,
                    zero_baseline_policy="needs_review",
                )
                db.add(v)
                db.flush()
                snap = to_snapshot(
                    terms,
                    agreement_id=str(a.id),
                    version_id=str(v.id),
                    version_no=1,
                    supplier_id=str(s.id),
                    fiscal_start=1,
                )
                write_rows(db, v, terms, snap)
                v.status = VersionStatus.ACTIVE.value
                v.activated_at = utcnow()
            days = (today - start).days
            rows = []
            for n in range(purchase_lines):
                si = n % len(SUPPLIERS)
                _, _, cats, (lo, hi) = SUPPLIERS[si]
                qty = Decimal(rng.randint(1, 40))
                price = (lo + (hi - lo) * Decimal(rng.random())).quantize(Decimal("0.01"))
                amount = qty * price
                if rng.random() < 0.02:
                    qty, amount = -qty, -amount
                rows.append(
                    {
                        "tenant_id": tenant.id,
                        "batch_id": batch.id,
                        "source_row": n + 2,
                        "supplier_id": supplier_ids[si],
                        "dedupe_key": hashlib.sha256(f"demo|{n}".encode()).digest(),
                        "invoice_number": f"INV{100000 + n // 3}",
                        "line_number": str(n % 3 + 1),
                        "sku": f"{cats[n % len(cats)][:3]}-{rng.randint(100, 999)}",
                        "description": "",
                        "quantity": qty,
                        "unit_price": price,
                        "amount": amount,
                        "invoice_date": start + timedelta(days=rng.randint(0, max(days, 1))),
                        "branch": rng.choice(["DAL", "HOU", "AUS", "OKC"]),
                        "category": cats[n % len(cats)],
                        "flags": {"special_pricing": rng.random() < 0.06},
                        "is_return": amount < 0,
                        "voided": False,
                    }
                )
                if len(rows) == 5000:
                    db.execute(insert(PurchaseLineRow), rows)
                    rows = []
            if rows:
                db.execute(insert(PurchaseLineRow), rows)
            credits: list[dict[str, object]] = []
            for si, sid in enumerate(supplier_ids):
                q = date(start.year, 1, 1)
                k = 0
                while q < today - timedelta(days=90):
                    if rng.random() < 0.7:
                        credits.append(
                            {
                                "id": uuid.uuid7(),
                                "tenant_id": tenant.id,
                                "batch_id": credit_batch.id,
                                "source_row": len(credits) + 2,
                                "supplier_id": sid,
                                "credit_reference": f"CM-{SUPPLIERS[si][1]}-{k}",
                                "credit_date": q + timedelta(days=rng.randint(100, 140)),
                                "amount": Decimal(rng.randint(2000, 25000)),
                                "memo": "Rebate credit",
                                "agreement_reference": f"{SUPPLIERS[si][1]}-REB",
                                "period_label": f"{q.year}-Q{(q.month - 1) // 3 + 1}",
                                "possible_duplicate": False,
                                "voided": False,
                            }
                        )
                    k += 1
                    q = date(q.year + (q.month + 2) // 12, (q.month + 2) % 12 + 1, 1)
            if credits:
                db.execute(insert(CreditLineRow), credits)
            batch.stats = {"rows_committed": purchase_lines}
            credit_batch.stats = {"rows_committed": len(credits)}
            return f"Demo tenant {tenant.id} created with {len(SUPPLIERS)} suppliers, {purchase_lines} purchase lines, {len(credits)} credits.\n{note}"
    finally:
        engine.dispose()
