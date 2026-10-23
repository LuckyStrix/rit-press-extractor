"""Read "News releases sent out" list pages: one dated subject per release.

A month's list can run over several pages. Only the first prints the year, the OCR garbles
many printed dates, and some rows have no date at all, so dates are rebuilt from context
(header month, the list's year, the row above) and every repair is flagged. Some lists print
only the day in a "Date" column, wrap long subjects onto further lines, and add notes in an
"Additional Info." column; the column layout is taken from the header row.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

from .dates import EARLIEST_YEAR
from .models import Box, Line, Word

TITLE_WORDS = ("news", "releases", "sent", "out")
ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
HEADER_ROW = re.compile(r"subject|additional|\bdate\b", re.I)
# month token, day (OCR may read a digit as a letter), optional year (often garbled), then the subject
_ROW = re.compile(r"^[\W_]*(?P<mon>[A-Za-z]{3,5})\W{0,6}(?P<day>[0-9A-Za-z]{1,2})(?![0-9A-Za-z])"
                  r"(?:\W{0,3}(?P<yr>[0-9:]{3,5})(?![A-Za-z0-9]))?(?P<rest>.*)$")
_STRICT_ROW = re.compile(r"^[\W_]*(?P<mon>[A-Za-z]{3})[a-z]{0,3}\.?\s*\d{1,2}\b")
_LOOKALIKE = str.maketrans("OoIlSsBb", "00115588")
_JUNK = re.compile(r"\s*[|\[\]{}]\s*")
_DAY = re.compile(r"^\d{1,2}$")
COLUMN_GAP = 2.0  # a gap this many line heights wide separates two columns, not two words
COLUMN_SLACK = 4  # notes start up to this many line heights left of their column's header word
WRAP_PITCH = 0.75  # a wrapped line sits closer to the line above than this share of an entry's spacing


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
        # Three different title words: a release letterhead's "New York ... NEWS RELEASE" is
        # news, news, releases.
        found = {close[0] for t in _norm(ln.text).split()
                 if (close := difflib.get_close_matches(t, TITLE_WORDS, 1, 0.75))}
        if len(found) >= 3:
            return True
    rows = lines[3:]  # a list is nearly all dated rows even when its title is unreadable
    dated = sum(1 for ln in rows if _STRICT_ROW.match(ln.text) and _edit1(_STRICT_ROW.match(ln.text)["mon"].lower()))
    return len(rows) >= 5 and dated >= 0.6 * len(rows) or _is_continued_list(lines)


def _is_continued_list(lines: list[Line]) -> bool:
    """A list's next page, with no title or headings: most rows start with a day, in order."""
    if not lines:
        return False
    height = _height(lines)
    left = min(ln.box[0] for ln in lines)
    rows = [ln for ln in lines if ln.box[0] < left + 10 * height]  # not the "Additional Info." column
    days = [int(ln.words[0].text) for ln in rows if len(ln.words) > 1 and _DAY.match(ln.words[0].text)
            and 1 <= int(ln.words[0].text) <= 31]
    ordered = sum(a <= b for a, b in zip(days, days[1:]))
    return len(days) >= 5 and len(days) >= 0.6 * len(rows) and ordered >= 0.8 * (len(days) - 1)


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
    """The month named on the "MONTH ......" line, if the whole word is readable. A sparse read
    can split the typed word ("Aug ust"), so two neighbouring tokens are also tried joined."""
    for ln in lines[:6]:
        toks = _norm(ln.text).split()
        if toks and _near(toks[0], ["month"], 0.7):
            for t in toks[1:] + [a + b for a, b in zip(toks[1:], toks[2:])]:
                if close := difflib.get_close_matches(t, MONTH_NAMES, 1, 0.8):
                    return close[0][:3]
    return None


def has_month_line(lines: list[Line]) -> bool:
    """Was the "MONTH ......" line read with its month or year? Tesseract can drop the whole
    line when the month is typed above a dotted rule."""
    return bool(_header_month(lines) or _header_year(lines))


def header_band(lines: list[Line]) -> Box | None:
    """The page above the column headings, where the "MONTH" line is typed."""
    head = _header_row(lines)
    return None if head is None else (0, 0, max(ln.box[2] for ln in lines), lines[head].box[1])


def with_month_line(lines: list[Line], sparse: list[Line]) -> list[Line]:
    """Add the "MONTH" line from a second read of the header band, when it names a month."""
    month = next((ln for ln in sparse if _header_month([ln]) or _header_year([ln])), None)
    if month is None:
        return lines
    head = _header_row(lines) or 0
    return lines[:head] + [month] + lines[head:]


def _header_year(lines: list[Line]) -> int | None:
    """A year typed on the "MONTH ......" line ("MONTH July 1969")."""
    for ln in lines[:6]:
        toks = _norm(ln.text).split()
        if toks and _near(toks[0], ["month"], 0.7):
            years = [int(y) for y in re.findall(r"\b\d{4}\b", ln.text)
                     if EARLIEST_YEAR <= int(y) <= dt.date.today().year]
            return years[0] if years else None
    return None


def _header_row(lines: list[Line]) -> int | None:
    return next((i for i, ln in enumerate(lines[:8]) if len(HEADER_ROW.findall(ln.text)) >= 2), None)


def _height(lines: list[Line]) -> float:
    heights = sorted(w.box[3] - w.box[1] for ln in lines for w in ln.words)
    return heights[len(heights) // 2] if heights else 1


def day_column(lines: list[Line]) -> Box | None:
    """Where the days sit on a list that prints them alone in a "Date" column, apart from the
    subjects. The OCR tends to drop such short numbers, so the column is read on its own.
    Tesseract can drop the "Date" heading too; then the column is whatever lies left of the
    subjects, which is only margin on a list that types its dates at the start of each row."""
    head = _header_row(lines)
    if head is None:
        return None
    date_word = next((w for w in lines[head].words if _norm(w.text) == "date"), None)
    rows = [ln for ln in lines[head + 1:] if ln.words]
    if not rows:
        return None
    # Where the subjects start. The page read may keep a row's day in front of it; that day is
    # in the column, not its right edge.
    left = min((ln.words[1] if _DAY.match(ln.words[0].text) and len(ln.words) > 1 else ln.words[0]).box[0]
               for ln in rows)
    if date_word is None:
        right = left - round(_height(rows))
        return (0, lines[head].box[3], right, max(ln.box[3] for ln in rows)) if right > 0 else None
    if left < date_word.box[2]:
        return None  # the dates are typed at the start of each row
    return 0, lines[head].box[3], (date_word.box[2] + left) // 2, max(ln.box[3] for ln in rows)


def with_days(lines: list[Line], days: list[Word]) -> list[Line]:
    """Put each day read from the "Date" column at the front of the row it sits beside. A punch
    hole or smudge in the margin can read as a digit; it is far taller than the typed days or
    stands away from their column, so it is left out."""
    out = [Line(list(ln.words)) for ln in lines]
    days = [w for w in days if _DAY.match(w.text)]
    if days:
        height = _height([Line(days)])
        mid = sorted((w.box[0] + w.box[2]) / 2 for w in days)[len(days) // 2]
        days = [w for w in days if w.box[3] - w.box[1] <= 1.6 * height
                and abs((w.box[0] + w.box[2]) / 2 - mid) <= 3 * height]
    for w in days:
        # A speck can be read as a short line of its own beside the row; the day goes to the
        # line it overlaps most.
        overlaps = [(min(ln.box[3], w.box[3]) - max(ln.box[1], w.box[1]), ln) for ln in out if ln.words]
        overlap, ln = max(overlaps, key=lambda o: o[0], default=(0, None))
        if ln and overlap > 0.5 * min(ln.box[3] - ln.box[1], w.box[3] - w.box[1]):
            if not _DAY.match(ln.words[0].text):
                ln.words.insert(0, w)
    return out


def missing_day_cells(lines: list[Line], column: Box) -> list[Box]:
    """The "Date" column beside each row that starts at the subjects' left edge but got no
    day from the column read, to be read again one at a time."""
    x0, y0, x1, y1 = column
    rows = [ln for ln in lines if ln.words and ln.box[0] > x1 and y0 <= ln.box[1] and ln.box[3] <= y1]
    if not rows:
        return []
    left, height = min(ln.box[0] for ln in rows), _height(rows)
    return [(x0, ln.box[1], x1, ln.box[3]) for ln in rows
            if ln.box[0] <= left + 3 * height and not _DAY.match(ln.words[0].text)]


def _additional_x(lines: list[Line], head: int | None) -> int | None:
    if head is None:
        return None
    return next((w.box[0] for w in lines[head].words if _norm(w.text).startswith("addit")), None)


def _subject_words(ln: Line, additional_x: int | None, height: float) -> list[Word]:
    """The row's words left of the "Additional Info." column: the column starts at a wide gap
    near where its header word sits."""
    if additional_x is None:
        return ln.words
    for i, w in enumerate(ln.words):
        gap = w.box[0] - ln.words[i - 1].box[2] if i else w.box[0]
        if w.box[0] >= additional_x - COLUMN_SLACK * height and gap >= COLUMN_GAP * height:
            return ln.words[:i]
    return ln.words


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


def _rows(page_no: int, lines: list[Line], month: str | None,
          default_month: str | None = None) -> tuple[list[_Row], str | None]:
    month = _header_month(lines) or month
    head = _header_row(lines)
    start = head + 1 if head is not None else 0
    if month is None:  # no readable header month: the commonest cleanly printed one on this page
        seen = Counter(m["mon"].lower()[:3] for ln in lines[start:] if (m := _STRICT_ROW.match(ln.text))
                       and m["mon"].lower()[:3] in ABBR)
        month = seen.most_common(1)[0][0] if seen else default_month
    additional_x, height = _additional_x(lines, head), _height(lines[start:])
    read: list[tuple[int, _Row]] = []  # each line's top and its reading
    for i, ln in enumerate(lines[start:], start):
        words = _subject_words(ln, additional_x, height)
        text = " ".join(w.text for w in words).strip()
        if len(re.sub(r"[\W_]", "", text)) < 3:
            continue
        read.append((ln.box[1], _row(page_no, i, Line(words), text, month, height)))
    pitch = _entry_pitch(read)
    rows: list[_Row] = []
    last_top = 0  # top of the last line of the entry above
    for top, row in read:
        # A wrapped subject is typed closer to the line above it than entries are to each other.
        if row.abbr is None and row.day is None and rows and pitch and top - last_top < WRAP_PITCH * pitch:
            prev = rows[-1]
            prev.subject = _tidy(f"{prev.subject} {row.subject}")
            prev.min_conf = min(prev.min_conf, row.min_conf)
        else:
            rows.append(row)
        last_top = top
    return rows, month


def _entry_pitch(read: list[tuple[int, _Row]]) -> float | None:
    """The page's usual spacing between entries: from each dated line back to the line above.
    Without dated entries to measure it, every undated line is taken as an entry of its own."""
    pitches = sorted(t - p for (p, _), (t, r) in zip(read, read[1:]) if r.abbr or r.day)
    return pitches[len(pitches) // 2] if pitches else None


def _row(page_no: int, i: int, ln: Line, text: str, month: str | None, height: float) -> _Row:
    words = ln.words
    # A day alone in the "Date" column, set apart from the subject: the month is the page's.
    first, rest = words[0], words[1:]
    if month and rest and _DAY.match(first.text) and rest[0].box[0] - first.box[2] >= COLUMN_GAP * height:
        day = int(first.text) if 1 <= int(first.text) <= 31 else None
        flags = [] if day else [f"day read as '{first.text}'; assumed same day as the entry above"]
        return _Row(month, day, None, first.text, _tidy(" ".join(w.text for w in rest)), min(w.conf for w in rest),
                    flags, page_no, i)
    m = _ROW.match(text)
    abbr = _month_of(m["mon"], month) if m else None
    if not m or abbr is None:
        return _Row(None, None, None, "", _tidy(text), min(w.conf for w in words),
                    ["no date printed; assumed same day as the entry above"], page_no, i)
    flags: list[str] = []
    if m["mon"] != abbr.capitalize():
        flags.append(f"month read as '{m['mon']}'; taken as {abbr.capitalize()}")
    day = _day(m["day"])
    if day is None:
        flags.append(f"day unreadable ('{m['day']}'); assumed same day as the entry above")
    elif not m["day"].isdigit():
        flags.append(f"day read as '{m['day']}'; taken as {day}")
    printed = text[: len(text) - len(m["rest"])].strip()
    # Confidence of the subject's own words; the printed date in front is often garbled.
    subject_words = words[len(printed.split()):] or words
    return _Row(abbr, day, m["yr"], printed, _tidy(m["rest"]), min(w.conf for w in subject_words), flags, page_no, i)


def parse_list_pages(pages: list[list[Line]], default_year: int | None = None,
                     default_month: int | None = None) -> ListResult:
    """Entries from a folder's list pages, in order. default_year and default_month are used
    only when no page prints a plausible one (e.g. taken from the releases' own dates)."""
    all_rows: list[_Row] = []
    month: str | None = None
    years: Counter = Counter()
    for n, lines in enumerate(pages):
        rows, month = _rows(n, lines, month, ABBR[default_month - 1] if default_month else None)
        all_rows.extend(rows)
        if header_year := _header_year(lines):
            years[header_year] += 1

    this_year = dt.date.today().year
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
