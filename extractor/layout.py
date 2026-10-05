"""Locate where the article body starts (just after the dateline) and read its words."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .dates import RELEASE_CUES
from .models import Line
from .words import APOSTROPHES, clean_word, is_word

DASHES = {"—", "–", "―", "‒", "--", "-", "~", "_", "−"}
NON_BODY = re.compile(r"contact|for more information|phone|tel\.|telephone|fax|e-?mail|www\.|http|@", re.I)
_TITLE_CITY_COMMA = re.compile(r"^[A-Z][\w.'’\-]+(?:\s[A-Z][\w.'’\-]+){0,2},\s")
_DASHLESS_DATELINE = re.compile(r"^([A-Z][A-Z.'’\-]{2,}(?:\s[A-Z][A-Z.'’\-]+){0,2},\s*(?:[A-Z][A-Za-z]{0,4}\.){1,3})\s+(?=[A-Z\"“])")


@dataclass
class BodyStart:
    line: int
    word: int
    dateline: int | None  # index of the dateline line, if one was found
    flags: list[str] = field(default_factory=list)


def _lowercase_tokens(tokens: list[str]) -> int:
    return sum(1 for t in tokens if (c := clean_word(t)) and c[0].islower())


def _following_tokens(lines: list[Line], i: int, k: int, n: int = 12) -> list[str]:
    out = [w.text for w in lines[i].words[k:]]
    for line in lines[i + 1:]:
        if len(out) >= n:
            break
        out.extend(w.text for w in line.words)
    return out[:n]


def _looks_like_dateline_prefix(prefix: str) -> bool:
    if not prefix or len(prefix) > 80 or RELEASE_CUES.search(prefix) or NON_BODY.search(prefix):
        return False
    first = re.sub(r"[^\w]", "", prefix.split()[0])
    caps_city = len(first) >= 3 and first.isalpha() and first.isupper()
    # "ROCHESTER, N.Y." / "ROCHESTER" / "NEW YORK", but not a multi-word caps headline.
    shaped = "," in prefix or len(prefix.split()) <= 2
    return (caps_city and shaped) or bool(_TITLE_CITY_COMMA.match(prefix + " "))


def find_body_start(lines: list[Line]) -> BodyStart | None:
    # 1. A dateline: "ROCHESTER, N.Y. — The college ..."
    for i, line in enumerate(lines):
        toks = [w.text for w in line.words]
        for k, tok in enumerate(toks[:14]):
            if tok not in DASHES or k == 0:
                continue
            prefix = " ".join(toks[:k])
            if not _looks_like_dateline_prefix(prefix):
                break
            same_line = [t for t in toks[k + 1:] if is_word(t)]
            if len(same_line) >= 3 and _lowercase_tokens(same_line) == 0:
                break  # "RIT WINS GRANT -- FUNDS NEW CENTER" is a headline
            if _lowercase_tokens(_following_tokens(lines, i, k + 1)) < 3:
                break  # what follows isn't prose (e.g. an all-caps headline)
            if k + 1 < len(toks):
                return BodyStart(i, k + 1, i)
            if i + 1 < len(lines):
                return BodyStart(i + 1, 0, i)
            break

    # 2. A dateline whose dash the OCR missed: "ROCHESTER, N.Y. The college ..."
    for i, line in enumerate(lines):
        m = _DASHLESS_DATELINE.match(line.text)
        if m and _lowercase_tokens(_following_tokens(lines, i, line.word_index_at(m.end()))) >= 3:
            return BodyStart(i, line.word_index_at(m.end()), i,
                             ["dateline found but its dash was not read; check where the body starts"])

    # 3. No dateline: first prose paragraph.
    for i, line in enumerate(lines):
        toks = [w.text for w in line.words]
        if len(toks) < 6 or _lowercase_tokens(toks) < 3 or RELEASE_CUES.search(line.text) or NON_BODY.search(line.text):
            continue
        start = i
        while start > 0 and _is_same_paragraph(lines[start - 1], lines[start]):
            start -= 1
        return BodyStart(start, 0, None, ["no dateline found; body start was inferred from layout"])
    return None


def _is_same_paragraph(above: Line, below: Line) -> bool:
    a, b = above.box, below.box
    line_h = max(a[3] - a[1], 1)
    gap = b[1] - a[3]
    toks = [w.text for w in above.words]
    return gap < 0.8 * line_h and len(toks) >= 6 and _lowercase_tokens(toks) >= 3 and abs(a[0] - b[0]) < 3 * line_h


@dataclass
class BodyWord:
    text: str
    conf: float
    note: str | None = None  # set when the word needed interpretation


def body_words(lines: list[Line], start: BodyStart, limit: int = 40) -> list[BodyWord]:
    """Cleaned words from the body start onward, joining words hyphenated across lines."""
    out: list[BodyWord] = []
    li, wi = start.line, start.word
    while li < len(lines) and len(out) < limit:
        words = lines[li].words
        while wi < len(words) and len(out) < limit:
            w = words[wi]
            last_on_line = wi == len(words) - 1
            if last_on_line and w.text.endswith("-") and len(w.text) > 1 and li + 1 < len(lines) and lines[li + 1].words:
                nxt = lines[li + 1].words[0]
                joined = w.text[:-1] + nxt.text
                note = f"'{w.text} {nxt.text}' was hyphenated across a line break; joined as '{clean_word(joined)}'"
                out.append(BodyWord(clean_word(joined), min(w.conf, nxt.conf), note))
                li, wi = li + 1, 1
                words = lines[li].words
                continue
            if w.text[-1:] in APOSTROPHES and len(w.text) > 1 and not last_on_line:
                # Elided forms never stand alone: OCR spacing "qu' une" means "qu'une".
                nxt = words[wi + 1]
                out.append(BodyWord(clean_word(w.text + nxt.text), min(w.conf, nxt.conf)))
                wi += 2
                continue
            if is_word(w.text) and clean_word(w.text):
                out.append(BodyWord(clean_word(w.text), w.conf))
            wi += 1
        li, wi = li + 1, 0
    return out


def _matching_line(lines: list[Line], ref: Line) -> int | None:
    """Index of the line that vertically overlaps ref the most (at least half a line height)."""
    r0, r1 = ref.box[1], ref.box[3]
    best, best_overlap = None, 0.0
    for i, line in enumerate(lines):
        y0, y1 = line.box[1], line.box[3]
        overlap = min(r1, y1) - max(r0, y0)
        if overlap > 0.5 * min(r1 - r0, y1 - y0) and overlap > best_overlap:
            best, best_overlap = i, overlap
    return best


def align_body_start(lines: list[Line], ref_line: Line, ref_word: int, ref_dateline: Line | None) -> BodyStart | None:
    """Find the same body start in another engine's lines, by text alignment then position."""
    i = _matching_line(lines, ref_line)
    if i is None:
        return None
    dateline = _matching_line(lines, ref_dateline) if ref_dateline is not None else None
    ref_tokens = [clean_word(w.text).lower() for w in ref_line.words]
    tokens = [clean_word(w.text).lower() for w in lines[i].words]
    sm = difflib.SequenceMatcher(None, ref_tokens, tokens, autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        if a <= ref_word < a + size:
            return BodyStart(i, b + ref_word - a, dateline)
    target_x = ref_line.words[ref_word].box[0]
    j = min(range(len(lines[i].words)), key=lambda j: abs(lines[i].words[j].box[0] - target_x))
    return BodyStart(i, j, dateline, ["second engine's body start located by position only"])
