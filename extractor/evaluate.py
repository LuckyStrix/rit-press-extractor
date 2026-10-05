"""Compare a results CSV against a hand-made answer key (truth CSV).

The key matters most for one number: fields the tool marked verified that are
actually wrong. That must be zero before trusting unflagged rows.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .dates import parse_dates_in_line
from .models import Line, Word

TRUTH_COLUMNS = ["file", "release_date", "first_five_words"]
BUCKETS = [
    ("verified_wrong", "VERIFIED BUT WRONG (must be 0)"),
    ("verified_right", "verified and right"),
    ("flagged_wrong", "flagged and wrong (caught)"),
    ("flagged_right", "flagged but right (needless review)"),
    ("no_answer", "no answer from tool"),
]


def make_template(results: Path, truth: Path) -> int:
    if truth.exists():
        raise SystemExit(f"{truth} already exists; not overwriting it")
    files = list(dict.fromkeys(r["file"] for r in csv.DictReader(open(results, encoding="utf-8"))))
    with open(truth, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TRUTH_COLUMNS)
        for name in files:
            w.writerow([name, "", ""])
    print(f"Wrote {truth} with {len(files)} rows. Fill in release_date (e.g. 1969-01-09 or January 9, 1969)\n"
          f"and first_five_words from the paper originals, not from the tool's output.")
    return 0


def _norm_date(text: str) -> str:
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", text):
        return text
    words = [Word(t, 100, (0, 0, 0, 0)) for t in text.split()]
    found = parse_dates_in_line(Line(words), 0)
    return found[0].iso if found else text


def _norm_words(text: str) -> str:
    return " ".join(text.split())


def _diff_kind(got: str, want: str) -> str:
    alnum = lambda t: "".join(c for c in t if c.isalnum())
    if got.lower() == want.lower():
        return "CASE"
    if alnum(got) == alnum(want):
        return "PUNCT"
    if alnum(got).lower() == alnum(want).lower():
        return "CASE+PUNCT"
    return "LETTERS"


def masked_diff(got: str, want: str) -> list[str]:
    """Describe how two word strings differ, with letters masked (safe to share)."""
    import difflib

    from .debug import mask

    g, w = got.split(), want.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [x.lower() for x in g], [x.lower() for x in w]).get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            out += [f"{_diff_kind(a, b)}: tool {mask(a)!r} key {mask(b)!r}" for a, b in zip(g[i1:i2], w[j1:j2]) if a != b]
        else:
            out.append(f"{op.upper()}: tool {mask(' '.join(g[i1:i2]))!r} key {mask(' '.join(w[j1:j2]))!r}")
    return out


def evaluate(results: Path, truth: Path, show: bool = False, diff: bool = False) -> int:
    rows = {r["file"]: r for r in csv.DictReader(open(results, encoding="utf-8"))}  # last row per file wins
    key = [t for t in csv.DictReader(open(truth, encoding="utf-8"))
           if t.get("release_date", "").strip() or t.get("first_five_words", "").strip()]
    fields = [("release_date", "date_verified", _norm_date), ("first_five_words", "words_verified", _norm_words)]
    tally = {f: {b: [] for b, _ in BUCKETS} for f, _, _ in fields}
    missing_rows = []
    for t in key:
        r = rows.get(t["file"])
        if r is None:
            missing_rows.append(t["file"])
            continue
        for name, verified_col, norm in fields:
            want = t.get(name, "").strip()
            if not want:
                continue
            got = r.get(name, "").strip()
            if not got:
                bucket = "no_answer"
            else:
                right = norm(got) == norm(want)
                verified = r.get(verified_col) == "YES"
                bucket = f"{'verified' if verified else 'flagged'}_{'right' if right else 'wrong'}"
            tally[name][bucket].append((t["file"], got, want))

    for name, _, _ in fields:
        total = sum(len(v) for v in tally[name].values())
        print(f"\n{name} ({total} checked)")
        for bucket, label in BUCKETS:
            items = tally[name][bucket]
            line = f"  {label:38} {len(items):4}"
            if items and bucket in ("verified_wrong", "flagged_right", "flagged_wrong"):
                line += "   " + ", ".join(f for f, _, _ in items)
            print(line)
            if show and bucket in ("verified_wrong", "flagged_wrong"):
                for f, got, want in items:
                    print(f"      {f}: tool '{got}'  vs  key '{want}'")
            if diff and bucket in ("verified_wrong", "flagged_wrong"):
                for f, got, want in items:
                    for d in masked_diff(got, want):
                        print(f"      {f}  {d}")
                    reasons = rows[f].get("review_reasons", "")
                    if reasons:
                        from .debug import mask

                        print(f"      {f}  reasons: {mask(reasons)[:300]}")
    if missing_rows:
        print(f"\nIn the key but not in the results: {', '.join(missing_rows)}")
    bad = sum(len(tally[n]["verified_wrong"]) for n, _, _ in fields)
    return 1 if bad else 0
