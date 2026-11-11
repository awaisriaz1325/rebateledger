"""Upload safety and format detection (SPEC §4.5.2 step 2, §4.5.6)."""

from __future__ import annotations

import codecs
import csv
import io
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from app.core.errors import AppError

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ROWS = 1_000_000
MAX_COLUMNS = 200
MAX_XLSX_UNCOMPRESSED = 300 * 1024 * 1024
MAX_XLSX_RATIO = 150
MAX_XLSX_MEMBERS = 5_000
DELIMITERS = (",", ";", "\t", "|")
ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "cp1252")


def reject(code: str, detail: str) -> AppError:
    return AppError(422, code, "File rejected", detail)


def file_format(filename: str, head: bytes) -> str:
    """'csv' or 'xlsx'. Extension AND magic bytes must agree; macro formats are refused."""
    name = filename.lower().strip()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("xlsm", "xlsb", "xls", "xltm"):
        raise reject(
            "FILE_TYPE_NOT_ALLOWED",
            "Macro-enabled and legacy Excel files are not accepted. Save as .xlsx or .csv.",
        )
    if ext == "xlsx":
        if not head.startswith(b"PK\x03\x04"):
            raise reject(
                "FILE_SIGNATURE_MISMATCH", "This .xlsx file is not a valid Excel workbook."
            )
        return "xlsx"
    if ext in ("csv", "txt"):
        if head.startswith(b"PK\x03\x04") or head.startswith(b"\xd0\xcf\x11\xe0"):
            raise reject(
                "FILE_SIGNATURE_MISMATCH",
                "This file is a spreadsheet, not CSV text. Upload it as .xlsx.",
            )
        if b"\x00" in head and not (
            head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE)
        ):
            raise reject(
                "FILE_SIGNATURE_MISMATCH", "This file contains binary data and is not a CSV."
            )
        return "csv"
    raise reject("FILE_TYPE_NOT_ALLOWED", "Upload a .csv or .xlsx file.")


def check_xlsx(fh: BinaryIO) -> None:
    """Zip-bomb protection before any XML is parsed (SPEC §9 case 28)."""
    try:
        with zipfile.ZipFile(fh) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_XLSX_MEMBERS:
                raise reject("XLSX_TOO_COMPLEX", "The workbook has too many parts.")
            names = {i.filename for i in infos}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise reject(
                    "FILE_SIGNATURE_MISMATCH", "This .xlsx file is not a valid Excel workbook."
                )
            if any(n.startswith("xl/vbaProject") for n in names):
                raise reject("FILE_TYPE_NOT_ALLOWED", "Workbooks with macros are not accepted.")
            total = 0
            for i in infos:
                total += i.file_size
                if (
                    i.compress_size
                    and i.file_size / max(i.compress_size, 1) > MAX_XLSX_RATIO
                    and i.file_size > 1024 * 1024
                ):
                    raise reject(
                        "XLSX_TOO_LARGE",
                        "The workbook expands to an unsafe size (possible zip bomb).",
                    )
            if total > MAX_XLSX_UNCOMPRESSED:
                raise reject(
                    "XLSX_TOO_LARGE",
                    "The workbook is too large when uncompressed. Export it as CSV instead.",
                )
    except zipfile.BadZipFile:
        raise reject(
            "FILE_SIGNATURE_MISMATCH", "This .xlsx file is damaged or not a workbook."
        ) from None
    finally:
        fh.seek(0)


def detect_encoding(sample: bytes) -> str:
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if sample.startswith(codecs.BOM_UTF16_LE) or sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    try:
        # A sample can cut a multi-byte character: drop up to 3 trailing bytes.
        for cut in range(4):
            try:
                sample[: len(sample) - cut or None].decode("utf-8")
                return "utf-8"
            except UnicodeDecodeError as exc:
                if exc.start < len(sample) - 4:
                    raise
        raise UnicodeDecodeError("utf-8", sample, 0, 1, "invalid")
    except UnicodeDecodeError:
        return "cp1252"


def detect_delimiter(text: str) -> str:
    lines = [ln for ln in text.splitlines()[:50] if ln.strip()]
    if not lines:
        return ","
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines), delimiters="".join(DELIMITERS))
        return dialect.delimiter
    except csv.Error:
        counts = {d: sum(ln.count(d) for ln in lines) for d in DELIMITERS}
        return max(counts, key=lambda d: counts[d])


@dataclass(frozen=True)
class Detection:
    file_format: str
    encoding: str | None
    delimiter: str | None
    sheets: list[str]


def decode_sample(raw: bytes, encoding: str) -> str:
    return io.TextIOWrapper(io.BytesIO(raw), encoding=encoding, errors="replace", newline="").read()
