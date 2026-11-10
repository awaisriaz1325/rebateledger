"""Regenerate docs/pilot-samples/ deterministically (fake data, seeded RNG).

Usage: uv run python scripts/make_pilot_samples.py ../docs/pilot-samples
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SUPPLIERS = {
    "ACME-ELEC": (
        ["WIRE-12-2", "BRKR-20A", "LED-PNL-24", "CONDUIT-075", "BOX-4SQ"],
        ["WIRE", "BREAKER", "LIGHTING", "CONDUIT", "BOXES"],
    ),
    "COOLAIR": (
        ["CMP-3T", "COIL-36", "TSTAT-PRO", "LINESET-50"],
        ["COMPRESSOR", "COIL", "CONTROLS", "LINESET"],
    ),
    "PIPEWORKS": (
        ["PEX-050-100", "PEX-075-100", "FIT-BRS-050", "VALVE-BALL-075"],
        ["PEX", "PEX", "FITTINGS", "VALVES"],
    ),
}
BRANCHES = ["DAL", "FTW", "AUS", "HOU"]
PRICE = {
    "ACME-ELEC": (Decimal("18.00"), Decimal("950.00")),
    "COOLAIR": (Decimal("85.00"), Decimal("2400.00")),
    "PIPEWORKS": (Decimal("0.90"), Decimal("65.00")),
}


def money(rng: random.Random, lo: Decimal, hi: Decimal) -> Decimal:
    cents = rng.randint(int(lo * 100), int(hi * 100))
    return Decimal(cents) / 100


def main(out: Path) -> None:
    rng = random.Random(20260101)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    invoice = 100000
    day = date(2026, 1, 2)
    while day <= date(2026, 6, 30):
        for supplier, (skus, cats) in SUPPLIERS.items():
            for _ in range(rng.randint(1, 3)):
                invoice += 1
                for line in range(1, rng.randint(2, 5)):
                    i = rng.randrange(len(skus))
                    qty = Decimal(
                        rng.randint(
                            *{"ACME-ELEC": (1, 12), "COOLAIR": (1, 4), "PIPEWORKS": (10, 150)}[
                                supplier
                            ]
                        )
                    )
                    price = money(rng, *PRICE[supplier])
                    amount = qty * price
                    returned = rng.random() < 0.03
                    if returned:
                        qty, amount = -qty, -amount
                    rows.append(
                        {
                            "Vendor No": supplier,
                            "Invoice No": f"INV{invoice}",
                            "Line": str(line),
                            "Item No": skus[i],
                            "Description": f"{cats[i].title()} item",
                            "Qty": str(qty),
                            "Unit Cost": str(price),
                            "Ext Cost": f"{amount:.2f}",
                            "Invoice Date": f"{day:%m/%d/%Y}",
                            "Ship Date": f"{day - timedelta(days=rng.randint(0, 3)):%m/%d/%Y}",
                            "Branch": rng.choice(BRANCHES),
                            "Product Class": cats[i],
                            "SPA": "Y" if rng.random() < 0.08 else "N",
                        }
                    )
        day += timedelta(days=rng.choice([1, 1, 2, 3]))
    with (out / "purchases.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} purchase rows")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
