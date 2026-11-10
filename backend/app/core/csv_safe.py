"""Spreadsheet formula-injection neutralisation (SPEC §4.10).

Any text cell starting with ``=``, ``+``, ``-``, ``@``, tab or carriage return is
prefixed with a single quote. In CSV every cell is text, so this applies to all
cells (including negative numbers, which then display with a leading quote in
some spreadsheet apps — the spec accepts this; XLSX writes real numbers instead).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import IO

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(DANGEROUS_PREFIXES):
        return "'" + text
    return text


def write_csv(stream: IO[str], header: Sequence[str], rows: Iterable[Sequence[object]]) -> int:
    writer = csv.writer(stream, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([neutralize(h) for h in header])
    count = 0
    for row in rows:
        writer.writerow([neutralize(v) for v in row])
        count += 1
    return count


def csv_string(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    buf = io.StringIO()
    write_csv(buf, header, rows)
    return buf.getvalue()
