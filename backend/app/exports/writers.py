"""Tabular writers (CSV, XLSX) and the PDF renderer.

Formula-injection protection (SPEC §4.10): every text cell starting with ``=``, ``+``,
``-``, ``@``, tab or carriage return is prefixed with a single quote. In XLSX genuine
numbers and dates are written as typed cells (never text), and text cells are forced to
the string type so a value can never become a formula.

PDF (ADR 0005): WeasyPrint with a URL fetcher that refuses everything except inline
``data:`` URIs, so a rendered document can never reach the network or the filesystem.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from weasyprint import HTML
from weasyprint.urls import URLFetcher, URLFetcherResponse

from app.core.csv_safe import csv_string, neutralize

Kind = Literal["text", "money", "number", "int", "date", "datetime"]


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: Kind = "text"


@dataclass
class Table:
    """A report: ordered columns, rows of plain values, and exact Decimal totals."""

    title: str
    columns: Sequence[Column]
    rows: list[dict[str, Any]]
    subtitle: str = ""
    filters: list[tuple[str, str]] = field(default_factory=list)
    totals: dict[str, Decimal] = field(default_factory=dict)


# --------------------------------------------------------------------------- text values


def text_value(value: Any, kind: Kind) -> str:
    """Plain, exact text for CSV and JSON (money keeps every stored decimal place)."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def display_value(value: Any, kind: Kind) -> str:
    """Human formatting for PDF: thousands separators, two decimals for money."""
    if value is None or value == "":
        return "—" if kind in ("money", "number") else ""
    if kind == "money" and isinstance(value, Decimal):
        sign = "−" if value < 0 else ""
        return f"{sign}${abs(value):,.2f}"
    if kind == "number" and isinstance(value, Decimal):
        return f"{value:,f}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return text_value(value, kind)


# --------------------------------------------------------------------------- CSV / XLSX


def to_csv(table: Table) -> bytes:
    header = [c.label for c in table.columns]
    rows = [[text_value(r.get(c.key), c.kind) for c in table.columns] for r in table.rows]
    if table.totals:
        rows.append(
            [
                "Total" if i == 0 else text_value(table.totals.get(c.key), c.kind)
                for i, c in enumerate(table.columns)
            ]
        )
    # UTF-8 with BOM so Excel opens accented supplier names correctly.
    return ("﻿" + csv_string(header, rows)).encode("utf-8")


def _xlsx_cell(ws: Any, value: Any, kind: Kind) -> WriteOnlyCell:
    if value is None:
        return WriteOnlyCell(ws, value=None)
    if kind == "money" and isinstance(value, Decimal):
        cell = WriteOnlyCell(ws, value=value)
        cell.number_format = "#,##0.00;-#,##0.00"
        return cell
    if (
        kind in ("number", "int")
        and isinstance(value, Decimal | int)
        and not isinstance(value, bool)
    ):
        cell = WriteOnlyCell(ws, value=value)
        cell.number_format = "#,##0" if kind == "int" else "#,##0.####"
        return cell
    if kind == "date" and isinstance(value, date) and not isinstance(value, datetime):
        cell = WriteOnlyCell(ws, value=value)
        cell.number_format = "yyyy-mm-dd"
        return cell
    cell = WriteOnlyCell(ws, value=neutralize(text_value(value, kind)))
    cell.data_type = "s"  # never a formula, whatever the text
    return cell


def to_xlsx(table: Table) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title="Report")
    bold = Font(bold=True)
    header = []
    for c in table.columns:
        cell = _xlsx_cell(ws, c.label, "text")
        cell.font = bold
        header.append(cell)
    ws.append(header)
    for r in table.rows:
        ws.append([_xlsx_cell(ws, r.get(c.key), c.kind) for c in table.columns])
    if table.totals:
        total_row = []
        for i, c in enumerate(table.columns):
            cell = _xlsx_cell(
                ws, "Total" if i == 0 else table.totals.get(c.key), "text" if i == 0 else c.kind
            )
            cell.font = bold
            total_row.append(cell)
        ws.append(total_row)
    about = wb.create_sheet(title="About")
    for label, value in [("Report", table.title), ("Details", table.subtitle), *table.filters]:
        about.append([_xlsx_cell(about, label, "text"), _xlsx_cell(about, value, "text")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- PDF


class NoNetworkFetcher(URLFetcher):  # type: ignore[misc]  # weasyprint ships no type hints
    """Refuses every URL except inline ``data:`` URIs (no http(s), file, ftp, ...)."""

    def __init__(self) -> None:
        super().__init__(allowed_protocols={"data"}, allow_redirects=False, fail_on_errors=False)
        self.blocked: list[str] = []

    def fetch(self, url: str, headers: Any = None) -> URLFetcherResponse:
        if not url.lower().startswith("data:"):
            self.blocked.append(url[:200])
            raise ValueError("network and file access are disabled for PDF rendering")
        response: URLFetcherResponse = super().fetch(url, headers)
        return response


_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["show"] = display_value
# WeasyPrint logs blocked resources at WARNING; they are expected and never contain data.
logging.getLogger("weasyprint").setLevel(logging.ERROR)


def render_html(template: str, **context: Any) -> str:
    return _env.get_template(template).render(**context)


def html_to_pdf(html: str, fetcher: NoNetworkFetcher | None = None) -> bytes:
    pdf: bytes = HTML(
        string=html, base_url=None, url_fetcher=fetcher or NoNetworkFetcher()
    ).write_pdf()
    return pdf


def to_pdf(table: Table, *, organization: str, generated_at: datetime) -> bytes:
    return html_to_pdf(
        render_html("report.html", t=table, organization=organization, generated_at=generated_at)
    )
