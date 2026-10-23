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
_MORE = re.compile(r"^[\W_]*\(?\s*more\s*\)?[\W_]*$", re.I)  # "-more-" at the foot: the list goes on
COLUMN_GAP = 2.0  # a gap this many line heights wide separates two columns, not two words
DAY_GAP = 1.0  # a typed tab after a row's day, wider than a space
DAY_VOTES = 2  # readings of the "Date" column that must find a day at a spot for it to count
DAY_ORDER_COST = 1.5  # votes a reading gives up when it puts a day before the one above it
DAY_DRIFT = 4  # line heights a day can stand off the middle of its column (typed further left)
BARE_ROWS = 4  # fewest dated rows on a list page whose days only a read of its day column finds
BARE_MARGIN = 8  # line heights from the page edge to where such a page's subjects start
WRAP_INDENT = 4  # an undated line set in this many line heights from the subjects' edge is a wrap
DAY_COLUMN_SLACK = 3  # line heights left of where most subjects start that a subject may still start
DAY_COLUMN_ROWS = 0.8  # share of rows that start right of the "Date" heading on a list with a day column
COLUMN_SLACK = 4  # notes start up to this many line heights left of their column's header word
WRAP_PITCH = 0.75  # a wrapped line sits closer to the line above than this share of an entry's spacing
SINGLE_SPACED = 1.8  # entries this many line heights apart are typed on consecutive lines


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


def bare_day_column(lines: list[Line]) -> Box | None:
    """Where the days would be on a list's next page if the page read dropped every one of them
    (there is no title or heading either): the strip left of where most lines start together,
    set in from the margin. Whether days are really there is for a read of the strip to say."""
    rows = [ln for ln in lines if ln.words]
    if len(rows) < BARE_ROWS:
        return None
    height = _height(rows)
    starts = sorted(ln.box[0] for ln in rows)
    edge = starts[len(starts) // 4]
    if edge < BARE_MARGIN * height or sum(abs(x - edge) <= 2 * height for x in starts) < 0.6 * len(rows):
        return None
    return 0, min(ln.box[1] for ln in rows) - round(height), edge - round(height), max(ln.box[3] for ln in rows)


def days_in_order(days: list[Word], rows: int) -> bool:
    """Do these days, read beside this many rows, look like a list's: one for most rows, in order?"""
    found = [int(w.text) for w in days if _DAY.match(w.text) and 1 <= int(w.text) <= 31]
    ordered = sum(a <= b for a, b in zip(found, found[1:]))
    return len(found) >= max(BARE_ROWS, 0.6 * rows) and ordered >= 0.8 * (len(found) - 1)


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
        return _continued_day_column(lines) if _is_continued_list(lines) else None
    date_word = next((w for w in lines[head].words if _norm(w.text) == "date"), None)
    rows = [ln for ln in lines[head + 1:] if ln.words]
    if not rows:
        return None
    # Where the subjects start. The page read may keep a row's day in front of it; that day is
    # in the column, not its right edge.
    starts = [(ln.words[1] if _DAY.match(ln.words[0].text) and len(ln.words) > 1 else ln.words[0]).box[0]
              for ln in rows]
    if date_word is None:
        # Without the heading to go by, the subjects start where most rows do; a row or two
        # starting further left carry a garbled day ("#514 Photographic").
        height = round(_height(rows))
        edge = sorted(starts)[len(starts) // 4]
        right = min(x for x in starts if x >= edge - DAY_COLUMN_SLACK * height) - height
        return (0, lines[head].box[3], right, max(ln.box[3] for ln in rows)) if right > 0 else None
    # A day typed over another can read as a garbled word glued to its row ("#514 Photographic").
    # Only when most rows start under the heading are the dates typed at the start of each row.
    clear = [x for x in starts if x >= date_word.box[2]]
    if len(clear) < DAY_COLUMN_ROWS * len(starts):
        return None
    return 0, lines[head].box[3], (date_word.box[2] + min(clear)) // 2, max(ln.box[3] for ln in rows)


def _continued_day_column(lines: list[Line]) -> Box | None:
    """A continued list page has no headings: the days are the numbers that start rows, and the
    column ends halfway between them and the subjects."""
    height = _height(lines)
    left = min(ln.box[0] for ln in lines)
    rows = [ln for ln in lines if ln.box[0] < left + 10 * height]
    days = [ln.words[0] for ln in rows if len(ln.words) > 1 and _DAY.match(ln.words[0].text)]
    if not days:
        return None
    subjects = min((ln.words[1] if ln.words[0] in days else ln.words[0]).box[0] for ln in rows)
    right = (max(w.box[2] for w in days) + subjects) // 2
    return 0, min(ln.box[1] for ln in rows), right, max(ln.box[3] for ln in rows)


def vote_days(reads: list[list[Word]]) -> list[Word]:
    """One day per row from several readings of the "Date" column. A single reading of a column
    of short, closely stacked numbers is fragile (three "15"s read as "5", "45", "25", or one
    left out), but the readings go wrong in different places. A day stands where at least two
    readings found a possible day (1-31); of what they read there, the most common wins, unless
    another reading keeps the days in order (a list mostly runs from the 1st on down)."""
    found = sorted(((w, i) for i, read in enumerate(reads) for w in read
                    if _DAY.match(w.text) and 1 <= int(w.text) <= 31), key=lambda wi: wi[0].box[1] + wi[0].box[3])
    if not found:
        return []
    height = _height([Line([w for w, _ in found])])
    spots: list[list[tuple[Word, int]]] = []
    for w, i in found:
        mid = (w.box[1] + w.box[3]) / 2
        spot = spots[-1] if spots else None
        if spot and abs(mid - sum((v.box[1] + v.box[3]) / 2 for v, _ in spot) / len(spot)) < height / 2 \
                and i not in {j for _, j in spot}:
            spot.append((w, i))
        else:
            spots.append([(w, i)])
    spots = [s for s in spots if len(s) >= DAY_VOTES]
    # Choose a reading for each spot: votes for it, less a penalty each time the days go back.
    options = [Counter(w.text for w, _ in s) for s in spots]
    best: dict[str, tuple[float, list[str]]] = {"": (0.0, [])}
    for votes in options:
        best = {text: max(((score + n - (DAY_ORDER_COST if prev and int(text) < int(prev) else 0), path + [text])
                           for prev, (score, path) in best.items()), key=lambda sp: sp[0])
                for text, n in votes.items()}
    chosen = max(best.values(), key=lambda sp: sp[0])[1]
    return [max((w for w, _ in s if w.text == text), key=lambda w: w.conf) for s, text in zip(spots, chosen)]


def with_days(lines: list[Line], days: list[Word], column: Box | None = None) -> list[Line]:
    """Put each day read from the "Date" column at the front of the row it sits beside. A punch
    hole or smudge in the margin can read as a digit; it is far taller than the typed days or
    stands away from their column, so it is left out. Days can sit a little above or below their
    rows (typed on a different line spacing), so each goes to the nearest row once the page's
    usual offset is allowed for, nearest pairs first and one day to a row. column: a garbled word
    at the start of a row inside it (a day typed over another, "#514") keeps only its digits, so
    the row is still an entry of its own with an unreadable day; one with no digits is dropped."""
    out = [Line(list(ln.words)) for ln in lines]
    if column:
        for ln in out:
            while len(ln.words) > 1 and ln.words[0].box[2] <= column[2] and column[1] <= ln.box[1] < column[3] \
                    and not _DAY.match(ln.words[0].text):
                if digits := re.sub(r"\D", "", ln.words[0].text):
                    ln.words[0] = Word(digits, ln.words[0].conf, ln.words[0].box)
                    break
                ln.words.pop(0)
    days = [w for w in days if _DAY.match(w.text)]
    if not days:
        return out
    height = _height([Line(days)])
    mid_x = sorted((w.box[0] + w.box[2]) / 2 for w in days)[len(days) // 2]
    days = [w for w in days if w.box[3] - w.box[1] <= 1.6 * height
            and abs((w.box[0] + w.box[2]) / 2 - mid_x) <= DAY_DRIFT * height]
    if not days:
        return out
    # Rows are the lines that start where the subjects do: not a speck read as a short line of
    # its own beside a row, nor a line of notes in the "Additional Info." column.
    right = max(w.box[2] for w in days)
    start = lambda ln: (ln.words[1] if _DAY.match(ln.words[0].text) and len(ln.words) > 1 else ln.words[0]).box[0]
    body = [ln for ln in out if ln.words and start(ln) > right and ln.box[2] > right + height]
    edge = sorted(start(ln) for ln in body)[len(body) // 4] if body else 0
    rows = [ln for ln in body if start(ln) <= edge + WRAP_INDENT * height]
    if not rows:
        return out
    mid = lambda box: (box[1] + box[3]) / 2
    offsets = sorted(min((mid(w.box) - mid(ln.box) for ln in rows), key=abs) for w in days)
    offset = offsets[len(offsets) // 2]
    pairs = sorted((abs(mid(w.box) - offset - mid(ln.box)), d, r) for d, w in enumerate(days)
                   for r, ln in enumerate(rows))
    used_days, used_rows = set(), set()
    for gap, d, r in pairs:
        if gap > height or d in used_days or r in used_rows:
            continue
        used_days.add(d)
        used_rows.add(r)
        first = rows[r].words[0]
        if column and first.text.isdigit() and not _DAY.match(first.text) and first.box[2] <= column[2]:
            rows[r].words[0] = days[d]  # a garbled day the column reads made out
        elif not _DAY.match(first.text):  # the page read may have kept the day already
            rows[r].words.insert(0, days[d])
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


def _info_cut(ln: Line, additional_x: int, height: float) -> int | None:
    """Where the "Additional Info." column starts on a row: at a wide gap near its header word."""
    for i, w in enumerate(ln.words):
        gap = w.box[0] - ln.words[i - 1].box[2] if i else w.box[0]
        if w.box[0] >= additional_x - COLUMN_SLACK * height and gap >= COLUMN_GAP * height:
            return i
    return None


def _info_left(lines: list[Line], additional_x: int | None, height: float) -> int | None:
    """The left edge of the notes column, from the rows where a wide gap sets it apart. A row
    whose subject runs up to the column has no such gap, but its notes start at this edge."""
    if additional_x is None:
        return None
    starts = sorted(ln.words[i].box[0] for ln in lines if (i := _info_cut(ln, additional_x, height)))
    return starts[len(starts) // 2] if len(starts) >= 3 else None


def _subject_words(ln: Line, additional_x: int | None, height: float, info_left: int | None = None) -> list[Word]:
    """The row's words left of the "Additional Info." column."""
    if additional_x is None:
        return ln.words
    cuts = [_info_cut(ln, additional_x, height)]
    if info_left is not None:
        cuts.append(next((i for i, w in enumerate(ln.words) if w.box[0] >= info_left - height / 2), None))
    cut = min((c for c in cuts if c is not None), default=None)
    return ln.words if cut is None else ln.words[:cut]


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


def _rows(page_no: int, lines: list[Line], month: str | None, default_month: str | None = None,
          additional_x: int | None = None) -> tuple[list[_Row], str | None, int | None]:
    """additional_x: where the list page before put its "Additional Info." column, for a
    continued page that has no headings."""
    month = _header_month(lines) or month
    head = _header_row(lines)
    start = head + 1 if head is not None else 0
    if month is None:  # no readable header month: the commonest cleanly printed one on this page
        seen = Counter(m["mon"].lower()[:3] for ln in lines[start:] if (m := _STRICT_ROW.match(ln.text))
                       and m["mon"].lower()[:3] in ABBR)
        month = seen.most_common(1)[0][0] if seen else default_month
    additional_x, height = _additional_x(lines, head) or additional_x, _height(lines[start:])
    info_left = _info_left(lines[start:], additional_x, height)
    read: list[tuple[int, _Row]] = []  # each line's top and its reading
    starts: list[int] = []  # where each line's subject starts
    for i, ln in enumerate(lines[start:], start):
        words = _subject_words(ln, additional_x, height, info_left)
        text = " ".join(w.text for w in words).strip()
        if len(re.sub(r"[\W_]", "", text)) < 3 or _MORE.match(text):
            continue
        row = _row(page_no, i, Line(words), text, month, height)
        read.append((ln.box[1], row))
        skip = len(row.printed.split())  # the subject starts after the printed date
        starts.append(words[skip].box[0] if skip < len(words) else words[0].box[0])
    limit = _wrap_limit(read, height)
    dated = sorted(x for x, (_, r) in zip(starts, read) if r.abbr or r.day)
    edge = dated[len(dated) // 4] if dated else None  # where the subjects start
    rows: list[_Row] = []
    last_top = 0  # top of the last line of the entry above
    for (top, row), x in zip(read, starts):
        # A wrapped subject is typed closer to the line above it than entries are to each other,
        # or set in well to the right of where the subjects start.
        wrapped = (limit and top - last_top < limit) or (edge is not None and x > edge + WRAP_INDENT * height)
        if row.abbr is None and row.day is None and rows and wrapped:
            prev = rows[-1]
            prev.subject = _tidy(f"{prev.subject} {row.subject}")
            prev.min_conf = min(prev.min_conf, row.min_conf)
        else:
            rows.append(row)
        last_top = top
    return rows, month, additional_x


def _wrap_limit(read: list[tuple[int, _Row]], height: float) -> float | None:
    """How close below the line above an undated line must sit to be a wrapped subject: a share
    of the page's usual spacing between entries (from each dated line back to the line above).
    Where some entries are single-spaced, spacing cannot tell a wrap from an entry, but the
    days can: then an undated line closer than the usual spacing is a wrap.
    Without dated entries to measure, every undated line is taken as an entry of its own."""
    pitches = sorted(t - p for (p, _), (t, r) in zip(read, read[1:]) if r.abbr or r.day)
    if not pitches:
        return None
    packed = pitches[len(pitches) // 4] < SINGLE_SPACED * height
    return pitches[len(pitches) // 2] * (1.0 if packed else WRAP_PITCH)


def _row(page_no: int, i: int, ln: Line, text: str, month: str | None, height: float) -> _Row:
    words = ln.words
    # A day alone in the "Date" column, set apart from the subject: the month is the page's.
    first, rest = words[0], words[1:]
    if month and rest and first.text.isdigit() and rest[0].box[0] - first.box[2] >= DAY_GAP * height:
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
    additional_x = None
    for n, lines in enumerate(pages):
        rows, month, additional_x = _rows(n, lines, month, ABBR[default_month - 1] if default_month else None,
                                          additional_x)
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
