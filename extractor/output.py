"""Result rows in a CSV that only the current user can read."""
from __future__ import annotations

import csv
import os
import threading
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

from .listpage import ListEntry
from .pipeline import Row, row_dict

COLUMNS = [f.name for f in fields(Row)]
UNMATCHED_COLUMNS = ["folder", "list_date", "subject", "printed_date", "review_reasons"]
_lock = threading.Lock()


FORMULA_STARTS = ("=", "+", "-", "@")


def _safe_cell(value):
    # Stop spreadsheet apps from treating OCR text as a formula. Text that already starts with an
    # apostrophe gets one too, so plain_cell can always undo this exactly.
    if isinstance(value, str) and value[:1] in (*FORMULA_STARTS, "'"):
        return "'" + value
    return value


def plain_cell(value: str) -> str:
    """The text _safe_cell was given, for a file (the xlsx) that stores text as text."""
    return value[1:] if value[:1] == "'" and value[1:2] in (*FORMULA_STARTS, "'") else value


def _load(path: Path, columns: list[str]) -> list[dict] | None:
    """Existing rows, or None if the file is new. A CSV from an older version (the columns are
    the start of today's) is read as-is, its new columns blank; anything else is refused."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:  # -sig: Excel's "CSV UTF-8" adds a marker
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if header != columns[:len(header)] or not header:
                raise ValueError(f"{path} has different columns; choose a new output file with -o")
            return [{c: r.get(c) or "" for c in columns} for r in reader]  # cells past the header are dropped
    except UnicodeDecodeError:
        raise ValueError(f"{path} is not UTF-8 text; if you edited it in Excel, save it as \"CSV UTF-8\"")


def load_results(path: Path) -> list[dict]:
    """The rows of a results CSV (one this program wrote, maybe corrected by hand since)."""
    with _lock:
        return _load(path, COLUMNS) or []


def replace_private(path: Path, write: Callable, binary: bool = False) -> None:
    """Write a file only the current user can read, in one step: write(f) fills a temporary file
    that then replaces path, so an interruption (or a copy open elsewhere) never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        with (os.fdopen(fd, "wb") if binary else os.fdopen(fd, "w", newline="", encoding="utf-8")) as f:
            write(f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    def write(f):
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    replace_private(path, write)


def _cells(row: Row) -> dict:
    return {k: _safe_cell(v) for k, v in row_dict(row).items()}


def append_rows(path: Path, rows: list[Row]) -> None:
    with _lock:
        old = _load(path, COLUMNS)
        _write(path, COLUMNS, (old or []) + [_cells(r) for r in rows])


def merge_rows(path: Path, rows: list[Row], consumed: set[tuple[str, int]], folder: str) -> None:
    """Add a folder's finished rows, replacing the earlier rows for the pages it covered (the
    per-page rows written while it ran, or a previous run). Rows without a folder, from older
    versions, are replaced when they are the same file and page."""
    with _lock:
        pages = {(f, str(p)) for f, p in consumed}
        keep = [r for r in (_load(path, COLUMNS) or [])
                if not ((r["file"], r["page"]) in pages and r["folder"] in (folder, ""))]
        _write(path, COLUMNS, keep + [_cells(r) for r in rows])


def write_unmatched(path: Path, folder: str, entries: list[ListEntry]) -> None:
    """List entries no release claimed, one report for all folders; this folder's earlier
    rows are replaced."""
    with _lock:
        old = _load(path, UNMATCHED_COLUMNS)
        if old is None and not entries:
            return
        keep = [r for r in (old or []) if r["folder"] != folder]
        new = [{"folder": folder, "list_date": e.date.isoformat() if e.date else "", "subject": _safe_cell(e.subject),
                "printed_date": _safe_cell(e.printed), "review_reasons": " | ".join(e.flags)} for e in entries]
        _write(path, UNMATCHED_COLUMNS, keep + new)
