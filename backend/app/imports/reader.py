"""Streaming row readers for CSV and XLSX (bounded memory)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any, BinaryIO

from app.core.errors import AppError
from app.imports.detect import MAX_COLUMNS, MAX_ROWS


def _cell(value: Any) -> str:
    """Typed XLSX cells → text. Dates become ISO (choose the YYYY-MM-DD format)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(Decimal(repr(value)), "f")
    return str(value)


def iter_csv(fh: BinaryIO, encoding: str, delimiter: str) -> Iterator[list[str]]:
    text = io.TextIOWrapper(fh, encoding=encoding, errors="strict", newline="")
    reader = csv.reader(text, delimiter=delimiter)
    try:
        yield from reader
    except UnicodeDecodeError:
        raise AppError(
            422,
            "ENCODING_MISMATCH",
            "Wrong text encoding",
            f"The file is not valid {encoding}. Choose another encoding.",
        ) from None
    except csv.Error as exc:
        raise AppError(422, "CSV_MALFORMED", "The CSV could not be read", str(exc)[:200]) from None
    finally:
        text.detach()  # leave the underlying file to its owner


def _load(fh: BinaryIO) -> Any:
    from openpyxl import load_workbook

    try:
        return load_workbook(fh, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parser refusal (incl. defusedxml entity errors) is a bad file
        raise AppError(
            422,
            "XLSX_UNREADABLE",
            "The workbook could not be read safely",
            f"The file was rejected ({type(exc).__name__}). Re-save it from Excel as .xlsx or export CSV.",
        ) from None


def xlsx_sheets(fh: BinaryIO) -> list[str]:
    wb = _load(fh)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()
        fh.seek(0)


def iter_xlsx(fh: BinaryIO, sheet: str | None) -> Iterator[list[str]]:
    # openpyxl parses with defusedxml when it is installed (it is a dependency), so
    # external entities are refused; size limits were checked by detect.check_xlsx.
    wb = _load(fh)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        if (ws.max_column or 0) > MAX_COLUMNS:
            raise AppError(
                422,
                "TOO_MANY_COLUMNS",
                "Too many columns",
                f"Sheets may have at most {MAX_COLUMNS} columns.",
            )
        try:
            for row in ws.iter_rows(values_only=True):
                yield [_cell(v) for v in row[:MAX_COLUMNS]]
        except Exception as exc:  # noqa: BLE001 - parser refusal mid-sheet (e.g. an entity in a sheet part)
            raise AppError(
                422,
                "XLSX_UNREADABLE",
                "The workbook could not be read safely",
                f"The file was rejected ({type(exc).__name__}).",
            ) from None
    finally:
        wb.close()


def iter_rows(fh: BinaryIO, config: dict[str, Any], file_format: str) -> Iterator[list[str]]:
    rows = (
        iter_xlsx(fh, config.get("sheet"))
        if file_format == "xlsx"
        else iter_csv(fh, config.get("encoding") or "utf-8", config.get("delimiter") or ",")
    )
    for count, row in enumerate(rows, start=1):
        if count > MAX_ROWS + 1000:
            raise AppError(
                422,
                "TOO_MANY_ROWS",
                "File too long",
                f"Files may have at most {MAX_ROWS:,} rows. Split the file.",
            )
        yield row


def split_header(
    rows: Iterator[list[str]], header_row: int
) -> tuple[list[str], Iterator[tuple[int, list[str]]]]:
    """Returns the header and an iterator of (1-based file row number, cells) after it."""
    header: list[str] = []
    for number, row in enumerate(rows, start=1):
        if number == header_row:
            header = [c.strip() for c in row]
            break
    else:
        raise AppError(
            422,
            "HEADER_NOT_FOUND",
            "Header row not found",
            f"The file has fewer than {header_row} rows.",
        )
    while header and not header[-1]:
        header.pop()

    def body() -> Iterator[tuple[int, list[str]]]:
        yield from enumerate(rows, start=header_row + 1)

    return header, body()
