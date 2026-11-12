"""p95 latency of list endpoints at 100k rows (SPEC §11 [PROPOSED TARGET] < 500 ms).

Seeds a demo tenant with 100,000 purchase lines plus 100,000 supplier credit lines, runs
one calculation through the API, then times every list endpoint in-process (ASGI, real
PostgreSQL and Redis; no network hop, no TLS). Results are printed as a Markdown table.

    cd backend && set -a && . ./.env.example && set +a && \\
      RL_JOBS_MODE=inline uv run python scripts/api_latency_test.py
"""

from __future__ import annotations

import os
import statistics
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("RL_JOBS_MODE", "inline")

REQUESTS = 50
CREDITS = 100_000


def main() -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, insert, select, text
    from sqlalchemy.orm import Session

    from app.core.clock import utcnow
    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.db.models.business import CreditLineRow, ImportBatch, Supplier
    from app.db.models.identity import Membership, User
    from app.main import create_app
    from app.services.seed import seed_demo

    settings = get_settings()
    assert settings.migration_database_url is not None
    tag = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()
    note = seed_demo(purchase_lines=100_000, owner_email=f"latency-owner-{tag}@example.com")
    tenant_id = uuid.UUID(note.split()[2])
    engine = create_engine(settings.migration_database_url.get_secret_value())
    password = "latency test passphrase 2026"  # noqa: S105  # nosec B105 - throwaway local load-test user
    with Session(engine) as db, db.begin():
        user = User(
            email=f"latency-analyst-{tag}@example.com",
            name="Latency Analyst",
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
        db.add(Membership(tenant_id=tenant_id, user_id=user.id, role="analyst"))
        suppliers = list(
            db.execute(select(Supplier.id).where(Supplier.tenant_id == tenant_id)).scalars()
        )
        batch = ImportBatch(
            tenant_id=tenant_id,
            import_type="credits",
            status="committed",
            filename="load-credits.csv",
            file_format="csv",
            size_bytes=0,
            file_hash=uuid.uuid4().hex,
            storage_key="none",
            config={},
        )
        db.add(batch)
        db.flush()
        rows = [
            {
                "id": uuid.uuid7(),
                "tenant_id": tenant_id,
                "batch_id": batch.id,
                "source_row": i + 2,
                "supplier_id": suppliers[i % len(suppliers)],
                "credit_reference": f"LOAD-{i}",
                "credit_date": date(2025, 1, 1) + timedelta(days=i % 365),
                "amount": Decimal("10.00"),
                "memo": "",
                "agreement_reference": None,
                "period_label": None,
                "possible_duplicate": False,
                "voided": False,
            }
            for i in range(CREDITS)
        ]
        for start in range(0, len(rows), 10_000):
            db.execute(insert(CreditLineRow), rows[start : start + 10_000])
        email = user.email
    with engine.begin() as conn:
        conn.execute(text("ANALYZE"))
    seeded = time.perf_counter() - t0

    origin = settings.app_base_url.rstrip("/")
    client = TestClient(
        create_app(), base_url=origin.replace("http://", "https://"), headers={"Origin": origin}
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    today = utcnow().date()
    run = client.post(
        "/api/v1/runs",
        json={
            "scope": {"type": "all"},
            "period_start": f"{today.year - 1}-01-01",
            "period_end": today.isoformat(),
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).json()
    run_id = run["id"]

    endpoints = [
        ("/api/v1/suppliers?limit=200", "items"),
        ("/api/v1/agreements?limit=200", "items"),
        ("/api/v1/imports?limit=200", "items"),
        ("/api/v1/runs?limit=50", "items"),
        (f"/api/v1/runs/{run_id}/results?limit=200", "items"),
        ("/api/v1/reconciliation", None),
        ("/api/v1/discrepancies", None),
        ("/api/v1/credits?limit=200", "items"),
        ("/api/v1/credits/unmatched", None),
        ("/api/v1/claims?limit=100", "items"),
        ("/api/v1/tiers", None),
        ("/api/v1/dashboard", None),
        ("/api/v1/reports/preview?report=reconciliation_summary", "rows"),
    ]
    print(
        f"Seeded 100,000 purchase lines and {CREDITS:,} credits in {seeded:.1f} s; run {run['number']} {run['status']}.\n"
    )
    print("| Endpoint | Rows returned | p50 ms | p95 ms | max ms |")
    print("|---|---|---|---|---|")
    for path, key in endpoints:
        timings: list[float] = []
        count = 0
        budget = REQUESTS + 3
        i = 0
        while i < budget:
            t_req = time.perf_counter()
            res = client.get(path)
            elapsed = (time.perf_counter() - t_req) * 1000
            if i == 0 and elapsed > 5000:
                budget = 5  # very slow endpoint: sample a few requests instead of 53
            assert res.status_code == 200, (path, res.status_code, res.text[:200])
            if i >= min(3, budget - 2):  # warm-up excluded
                timings.append(elapsed)
            body = res.json()
            count = len(body[key]) if key else (len(body) if isinstance(body, list) else 1)
            i += 1
        timings.sort()
        p95 = timings[max(int(len(timings) * 0.95) - 1, 0)]
        print(
            f"| `{path.split('?')[0].replace(run_id, '{run_id}')}` | {count} | {statistics.median(timings):.0f} | {p95:.0f} | {timings[-1]:.0f} |",
            flush=True,
        )


if __name__ == "__main__":
    main()
