"""Find and parse release dates in OCR'd text (multilingual month names)."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

from .models import Line

EARLIEST_YEAR = 1829  # RIT's founding

_MONTHS_BY_LANG = {
    "en": ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"],
    "de": ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
           "september", "oktober", "november", "dezember"],
    "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
           "september", "oktober", "november", "december"],
}
_ABBREVIATIONS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12, "févr": 2, "fév": 2, "avr": 4, "juil": 7,
    "déc": 12, "ene": 1, "dic": 12, "ago": 8, "gen": 1, "mag": 5, "giu": 6, "lug": 7,
    "set": 9, "ott": 10, "fev": 2, "dez": 12, "okt": 10, "mär": 3, "mrt": 3, "mei": 5,
    "janv": 1, "abr": 4, "out": 10, "sett": 9,
}
MONTHS: dict[str, int] = dict(_ABBREVIATIONS)
for _names in _MONTHS_BY_LANG.values():
    for _i, _n in enumerate(_names, start=1):
        MONTHS[_n] = _i
        MONTHS[unicodedata.normalize("NFD", _n).encode("ascii", "ignore").decode()] = _i

_MONTH_ALT = "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True))
_M = rf"(?P<m>{_MONTH_ALT})(?:\s?\.)?"
_D = r"(?P<d>[0-3]?\d)(?:st|nd|rd|th|er|e|º|°|\.)?"
_Y = r"(?P<y>1[89]\d\d|20\d\d|['’]\d\d)"
_B = r"(?<![\w])"  # left word boundary that also works before digits
_E = r"(?![\w])"
_S = r"(?:\s*,\s*|\s+)"  # separator; OCR sometimes puts a space before the comma

PATTERNS = [
    ("mdy", re.compile(rf"{_B}{_M}\s*{_D}{_S}{_Y}{_E}", re.I)),
    ("dmy", re.compile(rf"{_B}{_D}\s+(?:de\s+)?{_M}{_S}(?:de\s+)?{_Y}{_E}", re.I)),
    ("iso", re.compile(rf"{_B}(?P<y>1[89]\d\d|20\d\d)-(?P<a>\d\d)-(?P<b>\d\d){_E}")),
    ("num", re.compile(rf"{_B}(?P<a>\d{{1,2}})[/.\-](?P<b>\d{{1,2}})[/.\-](?P<y>\d{{4}}|\d{{2}}){_E}")),
    ("my", re.compile(rf"{_B}{_M}{_S}{_Y}{_E}", re.I)),
]

RELEASE_CUES = re.compile(
    r"release|embargo|immediate|diffusion|publication|publicaci|divulga|veröffentlich|"
    r"sperrfrist|uitgifte|publicatie|pubblicazione|\bdated?\b",
    re.I,
)


@dataclass
class DateFound:
    iso: str  # YYYY-MM-DD, or YYYY-MM for month-only dates
    printed: str
    line_index: int
    min_conf: float
    flags: list[str] = field(default_factory=list)
    box: tuple[int, int, int, int] | None = None  # where the date sits on the page


def _year(raw: str, flags: list[str]) -> int:
    if raw[0] in "'’" or len(raw) == 2:
        yy = int(raw[-2:])
        flags.append(f"two-digit year '{raw}' assumed to be 19{yy:02d}")
        return 1900 + yy
    return int(raw)


def parse_dates_in_line(line: Line, index: int) -> list[DateFound]:
    text = line.text
    found: list[DateFound] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue  # a more specific pattern already claimed this span
            flags: list[str] = []
            g = m.groupdict()
            year = _year(g["y"], flags)
            if kind in ("mdy", "dmy", "my"):
                month = MONTHS[g["m"].lower()]
                day = int(g["d"]) if g.get("d") else None
            elif kind == "iso":
                month, day = int(g["a"]), int(g["b"])
            else:
                a, b = int(g["a"]), int(g["b"])
                if a > 12 >= b:
                    month, day = b, a
                    flags.append(f"numeric date '{m.group(0)}' read as day/month")
                else:
                    month, day = a, b
                    flags.append(f"numeric date '{m.group(0)}' read as US month/day")
            try:
                if day is None:
                    dt.date(year, month, 1)
                    iso = f"{year:04d}-{month:02d}"
                    flags.append(f"'{m.group(0)}' has no day")
                else:
                    iso = dt.date(year, month, day).isoformat()
            except ValueError:
                continue  # not a real calendar date
            if not EARLIEST_YEAR <= year <= dt.date.today().year:
                flags.append(f"year {year} is outside the plausible range")
            words = line.words_in_span(m.start(), m.end())
            box = (min(w.box[0] for w in words), min(w.box[1] for w in words),
                   max(w.box[2] for w in words), max(w.box[3] for w in words))
            found.append(DateFound(iso, m.group(0), index, min(w.conf for w in words), flags, box))
            taken.append((m.start(), m.end()))
    return sorted(found, key=lambda d: text.find(d.printed))


def pick_release_date(lines: list[Line], header_end: int, dateline: Line | None):
    """Choose the release date from lines[:header_end] plus the dateline (body text excluded).

    Returns (DateFound or None, flags).
    """
    scope = list(lines[:header_end]) + ([dateline] if dateline is not None else [])
    dateline_index = header_end if dateline is not None else None
    candidates = [d for i, line in enumerate(scope) for d in parse_dates_in_line(line, i)]
    if not candidates:
        return None, ["no date found above the article body"]

    cue_lines = {i for i, line in enumerate(scope) if RELEASE_CUES.search(line.text)}
    near_cue = cue_lines | {i + 1 for i in cue_lines}
    primary = [d for d in candidates if d.line_index in near_cue]
    if not primary and dateline_index is not None:
        primary = [d for d in candidates if d.line_index == dateline_index]
    if not primary:
        primary = candidates

    chosen = primary[0]
    flags = list(chosen.flags)
    others = sorted({d.iso for d in candidates} - {chosen.iso})
    if others:
        flags.append(f"other dates also found above the body: {', '.join(others)}")
    return chosen, flags
