"""Append result rows to a CSV that only the current user can read."""
from __future__ import annotations

import csv
import os
import threading
from dataclasses import fields
from pathlib import Path

from .pipeline import Row, row_dict

COLUMNS = [f.name for f in fields(Row)]
_lock = threading.Lock()


def _safe_cell(value):
    # Stop spreadsheet apps from treating OCR text as a formula.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def append_rows(path: Path, rows: list[Row]) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists() or path.stat().st_size == 0
        if not new:
            with open(path, newline="", encoding="utf-8") as f:
                if next(csv.reader(f), None) != COLUMNS:
                    raise ValueError(f"{path} has different columns; choose a new output file with -o")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.chmod(path, 0o600)
        with os.fdopen(fd, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if new:
                writer.writeheader()
            for row in rows:
                writer.writerow({k: _safe_cell(v) for k, v in row_dict(row).items()})
