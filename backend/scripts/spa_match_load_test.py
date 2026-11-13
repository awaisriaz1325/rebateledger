"""Time the pure SPA matcher on N synthetic sales lines (v1.1 Phase 17 load check).

Usage: uv run python scripts/spa_match_load_test.py --rows 1000000
"""

from __future__ import annotations

import argparse
import resource
import time
from datetime import date, timedelta
from decimal import Decimal

from app.engine.spa import Sale, SpaItemTerms, SpaTerms, match


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=1_000_000)
    p.add_argument("--spas", type=int, default=200)
    a = p.parse_args()
    skus = [f"SKU{i:05d}" for i in range(2_000)]
    spas = [
        SpaTerms(
            spa_id=f"SPA{n}",
            supplier_id="S1",
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
            claim_deadline_days=60,
            items={
                sku: SpaItemTerms(Decimal("10.00"), Decimal("8.00"), Decimal("5000"))
                for sku in skus[n * 10 : n * 10 + 10]
            },
            customer=f"Customer {n}",
        )
        for n in range(a.spas)
    ]
    sales = [
        Sale(
            line_id=str(i),
            supplier_id="S1",
            invoice_date=date(2025, 1, 1) + timedelta(days=i % 365),
            sku=skus[i % len(skus)],
            quantity=Decimal(1 + i % 9),
            customer=f"Customer {(i % len(skus)) // 10}",
            unit_cost=Decimal("10.00"),
        )
        for i in range(a.rows)
    ]
    t0 = time.perf_counter()
    out = match(spas, sales)
    elapsed = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(
        f"rows={a.rows} spas={a.spas} results={len(out)} match_seconds={elapsed:.1f} peak_rss_mb={rss:.0f}"
    )


if __name__ == "__main__":
    main()
