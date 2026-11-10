"""Shared API model bases and types (SPEC §6 conventions)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, WithJsonSchema


class In(BaseModel):
    """Request bodies: unknown fields are rejected, strings trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _decimal_from_string(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise ValueError('send decimal values as strings, e.g. "1234.50"')
    try:
        d = Decimal(value.strip())
    except InvalidOperation:
        raise ValueError("not a decimal number") from None
    if not d.is_finite():
        raise ValueError("must be finite")
    return d


def _scale_check(places: int) -> Any:
    def check(value: Decimal) -> Decimal:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > places:
            raise ValueError(f"at most {places} decimal places")
        if abs(value) >= Decimal(10) ** (18 - places):
            raise ValueError("value is too large")
        return value

    return check


_decimal_schema = WithJsonSchema(
    {"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "examples": ["1234.50"]}
)
_as_string = PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json")

DecimalStr = Annotated[Decimal, BeforeValidator(_decimal_from_string), _as_string, _decimal_schema]
"""Generic decimal (output); money/rate inputs use the scale-checked variants."""
MoneyIn = Annotated[
    Decimal,
    BeforeValidator(lambda v: _scale_check(4)(_decimal_from_string(v))),
    _as_string,
    _decimal_schema,
]
RateIn = Annotated[
    Decimal,
    BeforeValidator(lambda v: _scale_check(6)(_decimal_from_string(v))),
    _as_string,
    _decimal_schema,
]

Name = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(max_length=500)]
LongText = Annotated[str, Field(max_length=10_000)]
Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Password = Annotated[str, Field(min_length=1, max_length=128)]
Code = Annotated[str, Field(min_length=1, max_length=20)]
Token = Annotated[str, Field(min_length=10, max_length=200)]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class Ok(Out):
    ok: bool = True
