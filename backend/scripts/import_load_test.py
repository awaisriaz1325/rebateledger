"""1,000,000-row import load test (PHASES §3 acceptance, SPEC §9 case 27).

Runs upload → validate → commit through the real API in-process (jobs inline) against
the local database, and reports elapsed time, progress updates and peak RSS.
Usage (local stack running, migrations applied):

    cd backend && set -a && . ./.env.example && set +a && \
      RL_JOBS_MODE=inline uv run python scripts/import_load_test.py --rows 1000000
"""

from __future__ import annotations

import argparse
import os
import resource
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("RL_JOBS_MODE", "inline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.main import create_app

    settings = get_settings()
    assert settings.migration_database_url is not None
    owner = create_engine(settings.migration_database_url.get_secret_value())
    tid, uid, sid = uuid.uuid7(), uuid.uuid7(), uuid.uuid7()
    email = f"load-{uid.hex[-8:]}@example.com"
    with owner.begin() as c:
        c.execute(
            text(
                "INSERT INTO rl.tenants (id, name, timezone, fiscal_year_start_month, currency, require_mfa_all, session_idle_minutes, allowed_invite_domains, abs_tolerance, pct_tolerance, default_payment_terms_days, data_freshness_days, tier_alert_pct, tier_alert_days, four_eyes_activation, four_eyes_writeoff, onboarding, is_demo, row_version) "
                "VALUES (:t, 'Load test (fake)', 'America/Chicago', 1, 'USD', false, 30, '{}', 1, 0.005, 60, 45, 0.1, 21, false, false, '{}', true, 1)"
            ),
            {"t": tid},
        )
        c.execute(
            text(
                "INSERT INTO rl.users (id, email, name, password_hash, email_verified_at, failed_login_count, must_reenroll_mfa, preferences) VALUES (:u, :e, 'Load', :p, now(), 0, false, '{}')"
            ),
            {"u": uid, "e": email, "p": hash_password("load test passphrase 1")},
        )
        c.execute(
            text(
                "INSERT INTO rl.memberships (id, tenant_id, user_id, role, status) VALUES (:i, :t, :u, 'analyst', 'active')"
            ),
            {"i": uuid.uuid7(), "t": tid, "u": uid},
        )
        c.execute(
            text(
                "INSERT INTO rl.suppliers (id, tenant_id, name, status, category_tags, payment_notes, notes, row_version) VALUES (:s, :t, 'Load Supplier', 'active', '{}', '', '', 1)"
            ),
            {"s": sid, "t": tid},
        )
        c.execute(
            text(
                "INSERT INTO rl.supplier_aliases (id, tenant_id, supplier_id, code) VALUES (:i, :t, :s, 'LOAD')"
            ),
            {"i": uuid.uuid7(), "t": tid, "s": sid},
        )

    path = Path(tempfile.gettempdir()) / f"rl-load-{args.rows}.csv"
    with path.open("w") as fh:
        # Compact rows so 1,000,000 rows fit the 50 MB upload cap (SPEC §4.5.2 defaults).
        fh.write("Vendor,Invoice,Line,Item,Qty,Ext,Inv Date,Category\n")
        for i in range(args.rows):
            fh.write(
                f"LOAD,{i // 4},{i % 4 + 1},S{i % 5000},{i % 50 + 1},{(i % 997) + 0.25:.2f},{(i % 12) + 1}/{(i % 28) + 1}/2025,C{i % 9}\n"
            )
    print(f"generated {path} ({path.stat().st_size / 1e6:.1f} MB)")

    origin = settings.app_base_url
    client = TestClient(create_app(), base_url="https://testserver", headers={"Origin": origin})
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "load test passphrase 1"}
    ).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    t0 = time.perf_counter()
    with path.open("rb") as fh:
        r = client.post(
            "/api/v1/imports",
            files={"file": ("load.csv", fh, "text/csv")},
            data={"import_type": "purchases"},
        )
    if r.status_code != 201:
        raise SystemExit(
            f"upload failed: {r.status_code} {r.json().get('code')}: {r.json().get('detail')}"
        )
    bid = r.json()["id"]
    cols = {
        "supplier_code": "Vendor",
        "invoice_number": "Invoice",
        "line_number": "Line",
        "sku": "Item",
        "quantity": "Qty",
        "amount": "Ext",
        "invoice_date": "Inv Date",
        "category": "Category",
    }
    client.put(
        f"/api/v1/imports/{bid}/config", json={"columns": cols, "date_format": "MM/DD/YYYY"}
    ).raise_for_status()
    t1 = time.perf_counter()
    client.post(f"/api/v1/imports/{bid}/validate").raise_for_status()
    t2 = time.perf_counter()
    job = client.post(f"/api/v1/imports/{bid}/commit", json={"mode": "all_or_nothing"}).json()[
        "job_id"
    ]
    t3 = time.perf_counter()
    batch = client.get(f"/api/v1/imports/{bid}").json()
    status = client.get(f"/api/v1/jobs/{job}").json()
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(
        f"upload {t1 - t0:.1f}s, validate {t2 - t1:.1f}s, commit {t3 - t2:.1f}s, total {t3 - t0:.1f}s"
    )
    print(
        f"status={batch['status']} committed={batch['stats'].get('rows_committed')} job={status['status']} progress={status['progress']}/{status['total']}"
    )
    print(f"peak RSS {peak_mb:.0f} MB")
    path.unlink()
    with owner.begin() as c:  # remove the load-test tenant
        c.execute(text("DELETE FROM rl.purchase_lines WHERE tenant_id = :t"), {"t": tid})
        c.execute(text("DELETE FROM rl.tenants WHERE id = :t"), {"t": tid})
        c.execute(text("DELETE FROM rl.users WHERE id = :u"), {"u": uid})
    owner.dispose()


if __name__ == "__main__":
    main()
