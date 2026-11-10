"""Canonical serialisation used for ``input_hash``.

Equal values must serialise identically regardless of construction order or
Decimal exponent (``Decimal("2.0")`` and ``Decimal("2.00")`` hash the same).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import Enum


def to_canonical(value: object) -> object:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        normal = value.normalize()
        return format(normal if normal != 0 else Decimal(0), "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: to_canonical(getattr(value, f.name))
            for f in dataclasses.fields(value)
            if f.compare
        }
    if isinstance(value, frozenset | set):
        items = [to_canonical(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, list | tuple):
        return [to_canonical(v) for v in value]
    if isinstance(value, dict):
        return {
            str(k): to_canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    raise TypeError(f"cannot canonicalise {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(to_canonical(value), sort_keys=True, separators=(",", ":"))


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
