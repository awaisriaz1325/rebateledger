"""50-agreement / 1,000,000-line calculation run (PHASES §4 acceptance, SPEC §4.6 target < 5 min).

    cd backend && set -a && . ./.env.example && set +a && \
      RL_JOBS_MODE=inline uv run python scripts/run_load_test.py
"""

from __future__ import annotations

import hashlib
import os
import random
import resource
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("RL_JOBS_MODE", "inline")


def main() -> None:
    from sqlalchemy import create_engine, insert, text
    from sqlalchemy.orm import Session

    from app.core.config import get_settings
    from app.db.models.business import (
        Agreement,
        AgreementVersion,
        ImportBatch,
        PurchaseLineRow,
        Supplier,
        SupplierAlias,
    )
    from app.db.models.identity import Tenant
    from app.services.agreement_terms import VersionTermsIn, to_snapshot, write_rows

    settings = get_settings()
    assert settings.migration_database_url is not None
    engine = create_engine(settings.migration_database_url.get_secret_value())
    rng = random.Random(7)
    t0 = time.perf_counter()
    with Session(engine) as db, db.begin():
        tenant = Tenant(
            name="Run load test (fake)",
            timezone="America/Chicago",
            fiscal_year_start_month=1,
            is_demo=True,
        )
        db.add(tenant)
        db.flush()
        batch = ImportBatch(
            tenant_id=tenant.id,
            import_type="purchases",
            status="committed",
            filename="load",
            file_format="csv",
            size_bytes=0,
            file_hash=uuid.uuid4().hex,
            storage_key="none",
            config={},
        )
        db.add(batch)
        db.flush()
        suppliers = []
        for s in range(10):
            sup = Supplier(tenant_id=tenant.id, name=f"Supplier {s}")
            db.add(sup)
            db.flush()
            db.add(SupplierAlias(tenant_id=tenant.id, supplier_id=sup.id, code=f"S{s}"))
            suppliers.append(sup.id)
            for k in range(5):
                a = Agreement(tenant_id=tenant.id, supplier_id=sup.id, name=f"S{s} program {k}")
                db.add(a)
                db.flush()
                comps = [
                    {
                        "key": "t",
                        "type": "tiered_all_units",
                        "tiers": [
                            {"threshold": "500000", "rate": "0.02"},
                            {"threshold": "1500000", "rate": "0.03"},
                        ],
                    },
                    {"key": "f", "type": "flat_percent", "rate": "0.01"},
                    {
                        "key": "i",
                        "type": "tiered_incremental",
                        "tiers": [
                            {"threshold": "0", "rate": "0.01"},
                            {"threshold": "800000", "rate": "0.02"},
                        ],
                    },
                    {"key": "b", "type": "fixed_bonus", "amount": "1000", "threshold": "900000"},
                    {"key": "u", "type": "per_unit", "amount_per_unit": "0.05"},
                ][k]
                elig = [
                    {
                        "key": "cat",
                        "action": "include",
                        "field": "category",
                        "values": [f"C{k}", f"C{k + 1}"],
                    }
                ]
                terms = VersionTermsIn.model_validate(
                    {
                        "effective_from": "2025-01-01",
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
                        "components": [comps],
                        "eligibility": elig,
                    }
                )
                v = AgreementVersion(
                    tenant_id=tenant.id,
                    agreement_id=a.id,
                    version_no=1,
                    status="draft",
                    effective_from=date(2025, 1, 1),
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
                write_rows(
                    db,
                    v,
                    terms,
                    to_snapshot(
                        terms,
                        agreement_id=str(a.id),
                        version_id=str(v.id),
                        version_no=1,
                        supplier_id=str(sup.id),
                        fiscal_start=1,
                    ),
                )
                v.status = "active"
        rows = []
        for n in range(1_000_000):
            amount = Decimal(rng.randint(100, 900_00)) / 100
            rows.append(
                {
                    "tenant_id": tenant.id,
                    "batch_id": batch.id,
                    "source_row": n,
                    "supplier_id": suppliers[n % 10],
                    "dedupe_key": hashlib.sha256(f"{n}".encode()).digest(),
                    "invoice_number": f"I{n}",
                    "sku": f"K{n % 300}",
                    "description": "",
                    "quantity": Decimal(rng.randint(1, 20)),
                    "amount": amount,
                    "invoice_date": date(2025, 1, 1) + timedelta(days=n % 365),
                    "category": f"C{n % 6}",
                    "flags": {},
                    "is_return": False,
                    "voided": False,
                }
            )
            if len(rows) == 10_000:
                db.execute(insert(PurchaseLineRow), rows)
                rows = []
        tenant_id = tenant.id
    print(f"loaded 50 agreements + 1,000,000 lines in {time.perf_counter() - t0:.0f}s")

    from fastapi.testclient import TestClient

    from app.core.security import hash_password
    from app.main import create_app

    uid = uuid.uuid7()
    email = f"runload-{uid.hex[-8:]}@example.com"
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO rl.users (id, email, name, password_hash, email_verified_at, failed_login_count, must_reenroll_mfa, preferences) VALUES (:u, :e, 'L', :p, now(), 0, false, '{}')"
            ),
            {"u": uid, "e": email, "p": hash_password("run load passphrase 1")},
        )
        c.execute(
            text(
                "INSERT INTO rl.memberships (id, tenant_id, user_id, role, status) VALUES (:i, :t, :u, 'analyst', 'active')"
            ),
            {"i": uuid.uuid7(), "t": tenant_id, "u": uid},
        )
    client = TestClient(
        create_app(), base_url="https://testserver", headers={"Origin": settings.app_base_url}
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "run load passphrase 1"}
    ).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    t1 = time.perf_counter()
    r = client.post(
        "/api/v1/runs",
        json={"scope": {"type": "all"}, "period_start": "2025-01-01", "period_end": "2025-12-31"},
    )
    elapsed = time.perf_counter() - t1
    out = client.get(f"/api/v1/runs/{r.json()['id']}").json()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(
        f"run status={out['status']} results={out['totals'].get('results')} expected_total={out['totals'].get('expected')} in {elapsed:.1f}s (target < 300s); peak RSS {peak:.0f} MB"
    )
    with engine.begin() as c:
        c.execute(text("DELETE FROM rl.tenants WHERE id = :t"), {"t": tenant_id})
        c.execute(text("DELETE FROM rl.users WHERE id = :u"), {"u": uid})
    engine.dispose()


if __name__ == "__main__":
    main()
