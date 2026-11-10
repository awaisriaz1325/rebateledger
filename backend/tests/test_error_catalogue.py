"""Every error code the backend can raise is documented in docs/error-codes.md."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERN = re.compile(
    r'(?:AppError\(\s*\d+,\s*|invalid\(\s*|conflict\(\s*)"([A-Z][A-Z0-9_]+)"', re.S
)


def test_codes_are_documented() -> None:
    raised: set[str] = set()
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        raised |= set(PATTERN.findall(path.read_text(encoding="utf-8")))
    documented = set(
        re.findall(
            r"`([A-Z][A-Z0-9_]+)`", (ROOT / "docs" / "error-codes.md").read_text(encoding="utf-8")
        )
    )
    missing = sorted(raised - documented)
    assert not missing, f"undocumented error codes: {missing}"
