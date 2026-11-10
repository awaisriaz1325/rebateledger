"""Cell parsing with explicit formats (SPEC §4.5.3, §9 cases 17–21)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.imports.parsing import (
    DEFAULT_FALSE,
    DEFAULT_TRUE,
    NegativeStyle,
    NumberFormat,
    ParseError,
    check_date_window,
    clean_text,
    date_format_candidates,
    looks_like_scientific,
    parse_bool,
    parse_date,
    parse_decimal,
)

US = NumberFormat()
EU = NumberFormat(decimal_separator=",", thousands_separator=".")


@pytest.mark.parametrize(
    ("raw", "fmt", "want"),
    [
        ("1,234.56", US, "1234.56"),
        ("$1,234.56", US, "1234.56"),
        ("-1234.56", US, "-1234.56"),
        ("+12", US, "12"),
        (".5", US, "0.5"),
        ("1.234,56", EU, "1234.56"),  # case 19: comma decimals
        (
            "(1,234.56)",
            NumberFormat(negative_style=NegativeStyle.PARENTHESES),
            "-1234.56",
        ),  # case 20
        (
            "1234.56-",
            NumberFormat(negative_style=NegativeStyle.TRAILING_MINUS),
            "-1234.56",
        ),  # case 20
        ("  12.3400 ", US, "12.3400"),
    ],
)
def test_parse_decimal(raw: str, fmt: NumberFormat, want: str) -> None:
    assert parse_decimal(raw, fmt) == Decimal(want)


@pytest.mark.parametrize(
    ("raw", "fmt", "code"),
    [
        ("", US, "REQUIRED"),
        ("abc", US, "NOT_A_NUMBER"),
        ("1.23456", US, "TOO_MANY_DECIMALS"),
        ("-5", NumberFormat(negative_style=NegativeStyle.PARENTHESES), "NEGATIVE_STYLE"),
        ("1e5", US, "NOT_A_NUMBER"),
        ("1,2,3.4.5", US, "NOT_A_NUMBER"),
    ],
)
def test_parse_decimal_errors(raw: str, fmt: NumberFormat, code: str) -> None:
    with pytest.raises(ParseError) as exc:
        parse_decimal(raw, fmt)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "kwargs",
    [
        {"decimal_separator": ";"},
        {"thousands_separator": "x"},
        {"decimal_separator": ",", "thousands_separator": ","},
    ],
)
def test_number_format_validation(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        NumberFormat(**kwargs)  # type: ignore[arg-type]


def test_dates_are_never_guessed() -> None:
    """Case 17: 03/04/2026 parses under two formats → caller must ask the user."""
    assert date_format_candidates(["03/04/2026", "05/06/2026"]) == ["MM/DD/YYYY", "DD/MM/YYYY"]
    assert date_format_candidates(["03/24/2026"]) == ["MM/DD/YYYY"]
    assert date_format_candidates(["", " "]) == []
    assert parse_date("03/04/2026", "MM/DD/YYYY") == date(2026, 3, 4)
    assert parse_date("03/04/2026", "DD/MM/YYYY") == date(2026, 4, 3)
    assert parse_date("29-Feb-2028", "DD-MMM-YYYY") == date(2028, 2, 29)


@pytest.mark.parametrize(
    ("raw", "fmt", "code"),
    [
        ("", "MM/DD/YYYY", "REQUIRED"),
        ("02/30/2026", "MM/DD/YYYY", "INVALID_DATE"),
        ("x", "NOPE", "DATE_FORMAT"),
    ],
)
def test_date_errors(raw: str, fmt: str, code: str) -> None:
    with pytest.raises(ParseError) as exc:
        parse_date(raw, fmt)
    assert exc.value.code == code


def test_date_window() -> None:
    today = date(2026, 6, 1)
    check_date_window(date(2026, 7, 2), today)
    with pytest.raises(ParseError, match="future"):
        check_date_window(date(2026, 7, 3), today)
    with pytest.raises(ParseError, match="2000"):
        check_date_window(date(1999, 12, 31), today)


def test_sku_and_text_helpers() -> None:
    """Case 21: leading zeros are kept; scientific notation is detected."""
    assert clean_text("  00123 ") == "00123"
    assert clean_text(None) == ""
    assert clean_text("Café") == "Café"  # NFC
    assert looks_like_scientific("1.23E+11")
    assert not looks_like_scientific("00123")


def test_parse_bool() -> None:
    assert parse_bool("y", DEFAULT_TRUE, DEFAULT_FALSE) is True
    assert parse_bool("No", DEFAULT_TRUE, DEFAULT_FALSE) is False
    assert parse_bool("", DEFAULT_TRUE, DEFAULT_FALSE) is None
    with pytest.raises(ParseError):
        parse_bool("maybe", DEFAULT_TRUE, DEFAULT_FALSE)
