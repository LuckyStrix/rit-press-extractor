"""Interactive answer-key entry: show each photo, type the correct fields, save to CSV.

The tool's own output is deliberately not shown, so it can't bias the answers.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

from .evaluate import TRUTH_COLUMNS, _norm_date
from .loader import find_inputs
from .words import ARTICLES

HELP = "Enter = leave blank (not checked)   b = back   s = skip photo   q = save and quit"


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["file"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def _save(path: Path, answers: dict[str, dict], order: list[str]) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRUTH_COLUMNS)
        w.writeheader()
        for name in order + sorted(set(answers) - set(order)):
            if name in answers:
                w.writerow({k: answers[name].get(k, "") for k in TRUTH_COLUMNS})
    os.replace(tmp, path)


def _open_viewer(photo: Path) -> None:
    # Opens the original file in place; no copies or temp files are made.
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, str(photo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print(f"  (couldn't launch a viewer; open {photo} yourself)")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def _valid_iso(text: str) -> bool:
    try:
        dt.date.fromisoformat(text + "-01" if len(text) == 7 else text)
        return len(text) in (7, 10)
    except ValueError:
        return False


def _ask_date(current: str) -> str:
    while True:
        raw = _ask(f"  release date{f' [{current}]' if current else ''}: ")
        if raw in ("b", "s", "q"):
            return raw
        if not raw:
            return current
        iso = _norm_date(raw)
        if _valid_iso(iso):
            if iso != raw:
                print(f"    -> {iso}")
            return iso
        print("    couldn't read that as a date; try e.g. 1969-01-09 or January 9, 1969")


def _ask_words(current: str) -> str:
    while True:
        raw = _ask(f"  first five words{f' [{current}]' if current else ''}: ")
        if raw in ("b", "s", "q"):
            return raw
        if not raw:
            return current
        words = raw.split()
        warnings = []
        if len(words) != 5:
            warnings.append(f"that's {len(words)} words, not 5")
        if words[0].lower() in ARTICLES["en"]:
            warnings.append(f"starts with the article '{words[0]}', which the tool skips")
        if not warnings:
            return " ".join(words)
        if _ask(f"    {'; '.join(warnings)}. Keep it anyway? [y/N] ").lower() == "y":
            return " ".join(words)


def run(folder: Path, out: Path, open_viewer: bool = True) -> int:
    photos = find_inputs([folder])
    if not photos:
        print(f"No photos found in {folder}")
        return 1
    order = [p.name for p in photos]
    answers = _load(out)
    done = {n for n, a in answers.items() if a.get("release_date") or a.get("first_five_words")}
    i = next((k for k, n in enumerate(order) if n not in done), len(order))
    print(f"{len(photos)} photos, {len(done & set(order))} already answered. Saving to {out}\n{HELP}")
    print("Type exactly what's on the paper: correct spelling and capitals, leading articles left out.\n")
    while i < len(photos):
        photo = photos[i]
        cur = answers.get(photo.name, {})
        print(f"[{i + 1}/{len(photos)}] {photo.name}")
        if open_viewer:
            _open_viewer(photo)
        date = _ask_date(cur.get("release_date", ""))
        if date in ("b", "s", "q"):
            action = date
        else:
            words = _ask_words(cur.get("first_five_words", ""))
            action = words if words in ("b", "s", "q") else None
            if action is None:
                answers[photo.name] = {"file": photo.name, "release_date": date, "first_five_words": words}
                _save(out, answers, order)
        if action == "q":
            break
        i = max(i - 1, 0) if action == "b" else i + 1
    _save(out, answers, order)
    filled = sum(1 for n in order if answers.get(n, {}).get("release_date") or answers.get(n, {}).get("first_five_words"))
    print(f"\nSaved {out}: {filled}/{len(order)} photos answered.")
    return 0
