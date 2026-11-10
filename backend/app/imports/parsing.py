"""Cell-level parsing with explicit, user-chosen formats (SPEC §4.5.2 step 4, §4.5.3).

Nothing here guesses between ambiguous formats. Detection helpers return
*candidates*; the caller must make the user confirm one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class NegativeStyle(StrEnum):
    MINUS = "minus"  # -123.45
    PARENTHESES = "parentheses"  # (123.45)
    TRAILING_MINUS = "trailing_minus"  # 123.45-


class ParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class NumberFormat:
    decimal_separator: str = "."
    thousands_separator: str = ","
    negative_style: NegativeStyle = NegativeStyle.MINUS
    currency_symbols: tuple[str, ...] = ("$",)
    max_places: int = 4

    def __post_init__(self) -> None:
        if self.decimal_separator not in {".", ","}:
            raise ValueError("decimal separator must be '.' or ','")
        if self.thousands_separator not in {"", ",", ".", " ", "'"}:
            raise ValueError("unsupported thousands separator")
        if self.thousands_separator == self.decimal_separator:
            raise ValueError("thousands and decimal separators must differ")


SUPPORTED_DATE_FORMATS: dict[str, str] = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "M/D/YY": "%m/%d/%y",
    "D/M/YY": "%d/%m/%y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "YYYYMMDD": "%Y%m%d",
    "DD-MMM-YYYY": "%d-%b-%Y",
    "MM-DD-YYYY": "%m-%d-%Y",
}


def clean_text(value: str | None) -> str:
    """Trim and NFC-normalise. ``None`` becomes ''."""
    if value is None:
        return ""
    return unicodedata.normalize("NFC", value).strip()


def parse_decimal(raw: str, fmt: NumberFormat) -> Decimal:
    text = clean_text(raw)
    if not text:
        raise ParseError("REQUIRED", "value is empty")
    negative = False
    if (
        fmt.negative_style is NegativeStyle.PARENTHESES
        and text.startswith("(")
        and text.endswith(")")
    ):
        negative, text = True, text[1:-1].strip()
    elif fmt.negative_style is NegativeStyle.TRAILING_MINUS and text.endswith("-"):
        negative, text = True, text[:-1].strip()
    if text.startswith("-") or text.startswith("+"):
        if fmt.negative_style is not NegativeStyle.MINUS:
            raise ParseError(
                "NEGATIVE_STYLE",
                f"'{raw}' uses a sign but the chosen style is {fmt.negative_style.value}",
            )
        negative, text = text.startswith("-"), text[1:].strip()
    for symbol in fmt.currency_symbols:
        text = text.replace(symbol, "")
    text = text.strip()
    if fmt.thousands_separator:
        text = text.replace(fmt.thousands_separator, "")
    if fmt.decimal_separator == ",":
        text = text.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", text):
        raise ParseError("NOT_A_NUMBER", f"'{raw}' is not a number in the chosen format")
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - regex already guarantees validity
        raise ParseError("NOT_A_NUMBER", f"'{raw}' is not a number") from None
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    if -exponent > fmt.max_places:
        raise ParseError(
            "TOO_MANY_DECIMALS", f"'{raw}' has more than {fmt.max_places} decimal places"
        )
    return -value if negative else value


def parse_date(raw: str, format_name: str) -> date:
    text = clean_text(raw)
    if not text:
        raise ParseError("REQUIRED", "date is empty")
    pattern = SUPPORTED_DATE_FORMATS.get(format_name)
    if pattern is None:
        raise ParseError("DATE_FORMAT", f"unsupported date format {format_name}")
    try:
        return datetime.strptime(text, pattern).date()  # noqa: DTZ007 - a calendar date, no time
    except ValueError:
        raise ParseError(
            "INVALID_DATE", f"'{raw}' is not a real date in {format_name} form"
        ) from None


def check_date_window(d: date, today: date, future_days: int = 31) -> None:
    """SPEC §4.5.3: not before 2000-01-01 and not more than 31 days in the future."""
    if d < date(2000, 1, 1):
        raise ParseError("DATE_TOO_OLD", f"{d} is before 2000-01-01")
    if (d - today).days > future_days:
        raise ParseError("DATE_IN_FUTURE", f"{d} is more than {future_days} days in the future")


def date_format_candidates(samples: list[str]) -> list[str]:
    """Formats under which every non-empty sample parses. More than one = ambiguous;
    the user must choose (SPEC §9 case 17)."""
    values = [clean_text(s) for s in samples if clean_text(s)]
    if not values:
        return []
    out = []
    for name in SUPPORTED_DATE_FORMATS:
        try:
            for v in values:
                parse_date(v, name)
        except ParseError:
            continue
        out.append(name)
    return out


_SCIENTIFIC = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")


def looks_like_scientific(sku: str) -> bool:
    """`1.23E+11` in a SKU column means Excel already corrupted the file (SPEC §9 case 21)."""
    return bool(_SCIENTIFIC.match(clean_text(sku)))


def parse_bool(raw: str, true_values: frozenset[str], false_values: frozenset[str]) -> bool | None:
    text = clean_text(raw).upper()
    if not text:
        return None
    if text in true_values:
        return True
    if text in false_values:
        return False
    raise ParseError("NOT_A_BOOLEAN", f"'{raw}' is not one of {sorted(true_values | false_values)}")


DEFAULT_TRUE = frozenset({"Y", "YES", "TRUE", "1", "X"})
DEFAULT_FALSE = frozenset({"N", "NO", "FALSE", "0"})
