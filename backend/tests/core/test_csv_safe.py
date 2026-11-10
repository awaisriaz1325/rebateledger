"""Formula-injection neutralisation (SPEC §4.10, §9 case 47)."""

from __future__ import annotations

import pytest

from app.core.csv_safe import csv_string, neutralize


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ('=HYPERLINK("http://x","y")', '\'=HYPERLINK("http://x","y")'),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("@SUM(1+1)", "'@SUM(1+1)"),
        ("-10.00", "'-10.00"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("plain", "plain"),
        (None, ""),
        (12, "12"),
    ],
)
def test_neutralize(value: object, want: str) -> None:
    assert neutralize(value) == want


def test_csv_string_neutralises_header_and_cells() -> None:
    out = csv_string(["=a", "b"], [["@x", "ok"]])
    assert out == "'=a,b\r\n'@x,ok\r\n"
