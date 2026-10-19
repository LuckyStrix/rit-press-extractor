"""Read "News releases sent out" list pages: one dated subject line per release.

A month's list can run over several pages. Only the first prints the year, the OCR garbles
many printed dates, and some rows have no date at all, so dates are rebuilt from context
(header month, the list's year, the row above) and every repair is flagged.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

from .dates import EARLIEST_YEAR
from .models import Line

TITLE_WORDS = ("news", "releases", "sent", "out")
ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
HEADER_ROW = re.compile(r"subject|additional|\bdate\b", re.I)
# month token, day (OCR may read a digit as a letter), optional year (often garbled), then the subject
_ROW = re.compile(r"^[\W_]*(?P<mon>[A-Za-z]{3,5})\W{0,6}(?P<day>[0-9A-Za-z]{1,2})(?![0-9A-Za-z])"
                  r"(?:\W{0,3}(?P<yr>[0-9:]{3,5})(?![A-Za-z0-9]))?(?P<rest>.*)$")
_STRICT_ROW = re.compile(r"^[\W_]*(?P<mon>[A-Za-z]{3})[a-z]{0,3}\.?\s*\d{1,2}\b")
_LOOKALIKE = str.maketrans("OoIlSsBb", "00115588")
_JUNK = re.compile(r"\s*[|\[\]{}]\s*")


@dataclass
class ListEntry:
    date: dt.date | None
    subject: str
    printed: str  # the date as the OCR read it
    min_conf: float
    page: int  # index of the list page within the folder's list pages
    line: int
    flags: list[str] = field(default_factory=list)


@dataclass
class ListResult:
    entries: list[ListEntry]
    year: int | None
    month: int | None
    flags: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower())


def _near(token: str, targets: tuple[str, ...] | list[str], cutoff: float = 0.75) -> bool:
    return bool(difflib.get_close_matches(token, targets, 1, cutoff))


def is_list_page(lines: list[Line]) -> bool:
    for ln in lines[:6]:
        tokens = _norm(ln.text).split()
        if sum(_near(t, TITLE_WORDS) for t in tokens) >= 3:
            return True
    rows = lines[3:]  # a list is nearly all dated rows even when its title is unreadable
    dated = sum(1 for ln in rows if _STRICT_ROW.match(ln.text) and _edit1(_STRICT_ROW.match(ln.text)["mon"].lower()))
    return len(rows) >= 5 and dated >= 0.6 * len(rows)


def _edit1(token: str) -> str | None:
    """The month abbreviation a 3-letter token is (within one misread letter), if any."""
    if token in ABBR:
        return token
    for abbr in ABBR:
        if sum(a != b for a, b in zip(token, abbr)) == 1:
            return abbr
    return None


MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]


def _header_month(lines: list[Line]) -> str | None:
    """The month named on the "MONTH ......" line, if the whole word is readable."""
    for ln in lines[:6]:
        toks = _norm(ln.text).split()
        if toks and _near(toks[0], ["month"], 0.7):
            for t in toks[1:]:
                if close := difflib.get_close_matches(t, MONTH_NAMES, 1, 0.8):
                    return close[0][:3]
    return None


def _day(raw: str) -> int | None:
    if not any(c.isdigit() for c in raw):
        return None
    day = int(raw.translate(_LOOKALIKE)) if raw.translate(_LOOKALIKE).isdigit() else None
    return day if day and 1 <= day <= 31 else None


def _tidy(subject: str) -> str:
    subject = _JUNK.sub(" ", subject).strip(" _~‘'`")
    return re.sub(r"\s+", " ", subject).strip()


@dataclass
class _Row:
    abbr: str | None
    day: int | None
    year_raw: str | None
    printed: str
    subject: str
    min_conf: float
    flags: list[str]
    page: int
    line: int


def _month_of(token: str, month: str | None) -> str | None:
    """Which month a row's leading token names. Once the page's month is known, a token one
    misread letter away from it is that month; otherwise only a cleanly printed month counts."""
    tok = token.lower()[:3]
    if month and tok != month and sum(a != b for a, b in zip(tok, month)) == 1 and len(tok) == 3:
        return month
    return tok if tok in ABBR else None


def _rows(page_no: int, lines: list[Line], month: str | None) -> tuple[list[_Row], str | None]:
    month = _header_month(lines) or month
    start = next((i + 1 for i, ln in enumerate(lines[:8]) if len(HEADER_ROW.findall(ln.text)) >= 2), 0)
    if month is None:  # no readable header month: the commonest cleanly printed one on this page
        seen = Counter(m["mon"].lower()[:3] for ln in lines[start:] if (m := _STRICT_ROW.match(ln.text))
                       and m["mon"].lower()[:3] in ABBR)
        month = seen.most_common(1)[0][0] if seen else None
    rows: list[_Row] = []
    for i, ln in enumerate(lines[start:], start):
        text = ln.text.strip()
        if len(re.sub(r"[\W_]", "", text)) < 3:
            continue
        conf = min(w.conf for w in ln.words)
        m = _ROW.match(text)
        abbr = _month_of(m["mon"], month) if m else None
        if not m or abbr is None:
            rows.append(_Row(None, None, None, "", _tidy(text), conf,
                             ["no date printed; assumed same day as the entry above"], page_no, i))
            continue
        flags: list[str] = []
        if m["mon"] != abbr.capitalize():
            flags.append(f"month read as '{m['mon']}'; taken as {abbr.capitalize()}")
        day = _day(m["day"])
        if day is None:
            flags.append(f"day unreadable ('{m['day']}'); assumed same day as the entry above")
        elif not m["day"].isdigit():
            flags.append(f"day read as '{m['day']}'; taken as {day}")
        printed = text[: len(text) - len(m["rest"])].strip()
        rows.append(_Row(abbr, day, m["yr"], printed, _tidy(m["rest"]), conf, flags, page_no, i))
    return rows, month


def parse_list_pages(pages: list[list[Line]], default_year: int | None = None) -> ListResult:
    """Entries from a folder's list pages, in order. default_year is used only when no
    page prints a plausible year (e.g. taken from the releases' own dates)."""
    all_rows: list[_Row] = []
    month: str | None = None
    for n, lines in enumerate(pages):
        rows, month = _rows(n, lines, month)
        all_rows.extend(rows)

    this_year = dt.date.today().year
    years: Counter = Counter()
    for r in all_rows:
        digits = re.sub(r"\D", "", r.year_raw or "")
        if len(digits) == 4 and EARLIEST_YEAR <= int(digits) <= this_year:
            years[int(digits)] += 1
    year = years.most_common(1)[0][0] if years else default_year

    entries: list[ListEntry] = []
    prev: dt.date | None = None
    for r in all_rows:
        flags = list(r.flags)
        date: dt.date | None = None
        if r.abbr and r.day and year:
            try:
                date = dt.date(year, ABBR.index(r.abbr) + 1, r.day)
            except ValueError:
                flags.append(f"{r.abbr.capitalize()} {r.day} is not a calendar date; assumed same day as the entry above")
            if r.year_raw and re.sub(r"\D", "", r.year_raw) != str(year):
                flags.append(f"printed year read as '{r.year_raw}'; using the list's year {year}")
        if date is None:
            date = prev  # a row with no usable date sits on the same day as the one above it
        elif prev and date < prev:
            flags.append(f"date is out of sequence (after {prev.isoformat()})")
        else:
            prev = date
        entries.append(ListEntry(date, r.subject, r.printed, r.min_conf, r.page, r.line, flags))
    return ListResult(entries, year, ABBR.index(month) + 1 if month else None)
