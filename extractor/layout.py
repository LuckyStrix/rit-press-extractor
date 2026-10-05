"""Locate where the article body starts (just after the dateline) and read its words."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .models import Line, Word
from .words import APOSTROPHES, clean_word, is_word

DASHES = {"—", "–", "―", "‒", "--", "-", "~", "_", "−"}
NON_BODY = re.compile(r"\b(?:contact|phone|telephone|tel\.|fax|e-?mail)\b|for more information|www\.|https?://|@", re.I)
HEADER_CUE = re.compile(r"\bfor\s+(?:immediate\s+)?release\b|\bimmediate\s+release\b|\brelease\s+date\b|\bembargo", re.I)
_TITLE_CITY_COMMA = re.compile(r"^[A-Z][\w.'’\-]+(?:\s[A-Z][\w.'’\-]+){0,2},\s")
_DASHLESS_DATELINE = re.compile(r"^([A-Z][A-Z.'’\-]{2,}(?:\s[A-Z][A-Z.'’\-]+){0,2},\s*(?:[A-Z][A-Za-z]{0,4}\.){1,3})\s+(?=[A-Z\"“])")

# Typewritten paragraphs indent their first line ~5 characters. Measured relative to the
# next line (not a fixed margin), so tilted phone photos with a drifting margin still work.
INDENT_MIN_CHARS, INDENT_MAX_CHARS = 2.5, 15
ALIGN_CHARS = 1.5  # continuation lines start within this many characters of each other

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


def _all_caps(tokens: list[str]) -> bool:
    letters = [c for c in (clean_word(t) for t in tokens) if any(ch.isalpha() for ch in c)]
    return bool(letters) and all(c.upper() == c for c in letters)


@dataclass
class _Geometry:
    char_w: float  # typical character width
    width: float  # typical width of a full line
    gap: float  # typical gap between lines, in line heights


def _median(values: list[float]) -> float:
    values = sorted(values)
    return values[len(values) // 2]


def _geometry(lines: list[Line]) -> _Geometry | None:
    long = [ln for ln in lines if len(ln.words) >= 5]
    words = [w for ln in long for w in ln.words if len(w.text) >= 3]
    if len(long) < 3 or not words:
        return None
    gaps = [(b.box[1] - a.box[3]) / max(a.box[3] - a.box[1], 1) for a, b in zip(lines, lines[1:])]
    return _Geometry(
        char_w=_median([(w.box[2] - w.box[0]) / len(w.text) for w in words]),
        width=_median([ln.box[2] - ln.box[0] for ln in long]),
        gap=_median(gaps) if gaps else 1.0,
    )


def _x_offset_chars(lines: list[Line], a: int, b: int, g: _Geometry) -> float:
    return (lines[a].box[0] - lines[b].box[0]) / g.char_w


def _paragraph_start(lines: list[Line], i: int, g: _Geometry) -> str | None:
    """'indent' if line i is indented relative to the line below it, 'gap' if a flush
    paragraph follows a large blank space. None otherwise."""
    if i + 1 >= len(lines):
        return None
    offset = _x_offset_chars(lines, i, i + 1, g)
    if INDENT_MIN_CHARS <= offset <= INDENT_MAX_CHARS:
        return "indent"
    if abs(offset) <= ALIGN_CHARS and i > 0:
        a, b = lines[i - 1].box, lines[i].box
        gap = (b[1] - a[3]) / max(a[3] - a[1], 1)
        if gap > max(1.5 * g.gap, g.gap + 0.8):
            return "gap"
    return None


def _paragraph(lines: list[Line], i: int, g: _Geometry) -> list[Line]:
    """Line i plus the continuation lines that follow it (aligned, no new paragraph)."""
    para = [lines[i]]
    for j in range(i + 1, len(lines)):
        if j > i + 1 and (abs(_x_offset_chars(lines, j, j - 1, g)) > ALIGN_CHARS or _paragraph_start(lines, j, g)):
            break
        para.append(lines[j])
    return para


def _is_prose_paragraph(para: list[Line], g: _Geometry) -> bool:
    toks = [w.text for ln in para for w in ln.words if is_word(w.text)]
    first = [w.text for w in para[0].words]
    if len(para) < 2 or len(toks) < 12 or _lowercase_tokens(toks) < 0.3 * len(toks):
        return False
    if len(first) >= 2 and _all_caps(first):
        return False  # a caps headline sitting above unindented body text
    if HEADER_CUE.search(para[0].text) or NON_BODY.search(para[0].text):
        return False
    # A paragraph's first line runs to (nearly) the right margin, unlike a centred title.
    right = _median([ln.box[2] for ln in para[1:]])
    return para[0].box[2] >= right - 0.2 * g.width


def _looks_like_dateline_prefix(prefix: str) -> bool:
    if not prefix or len(prefix) > 80 or HEADER_CUE.search(prefix) or NON_BODY.search(prefix):
        return False
    first = re.sub(r"[^\w]", "", prefix.split()[0])
    caps_city = len(first) >= 3 and first.isalpha() and first.isupper()
    # "ROCHESTER, N.Y." / "ROCHESTER" / "NEW YORK". A longer caps run-in such as
    # "ACME GIVES COLLEGE GRANT --" is a headline that is part of the text, not a dateline.
    shaped = "," in prefix or len(prefix.split()) <= 2
    return (caps_city and shaped) or bool(_TITLE_CITY_COMMA.match(prefix + " "))


def find_body_start(lines: list[Line]) -> BodyStart | None:
    g = _geometry(lines)
    starts = [i == 0 or (g is not None and _paragraph_start(lines, i, g) is not None) for i in range(len(lines))]

    # 1. A dateline or caps run-in: "ROCHESTER, N.Y. — The college ..."
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

    # 3. No dateline: the first prose paragraph, found by its indented first line
    #    (typewritten releases) or, failing that, by the blank space above it.
    if g is not None:
        for i in range(len(lines)):
            kind = _paragraph_start(lines, i, g)
            if kind and _is_prose_paragraph(_paragraph(lines, i, g), g):
                flags = [] if kind == "indent" else ["no dateline or paragraph indent; body start inferred from spacing"]
                return BodyStart(i, 0, None, flags)

    # 4. Last resort: first line that reads like prose.
    for i, line in enumerate(lines):
        toks = [w.text for w in line.words]
        if len(toks) >= 6 and _lowercase_tokens(toks) >= 3 and not HEADER_CUE.search(line.text) and not NON_BODY.search(line.text):
            return BodyStart(i, 0, None, ["no dateline found; body start was guessed; check it"])
    return None


@dataclass
class BodyWord:
    text: str
    conf: float
    note: str | None = None  # set when the word needed interpretation
    line: int = 0  # index of the (last) line the word sits on
    box: tuple[int, int, int, int] | None = None


def _rejoin_glued(words: list[Word]) -> list[Word]:
    """Re-merge pieces printed with no space between them (dashes split off for layout
    analysis, e.g. 'GRANT' '---' 'J.' back into 'GRANT---J.')."""
    out: list[Word] = []
    for w in words:
        if out:
            p = out[-1]
            char_w = (p.box[2] - p.box[0]) / max(len(p.text), 1)
            if w.box[0] - p.box[2] < 0.25 * char_w:
                out[-1] = Word(p.text + w.text, min(p.conf, w.conf),
                               (p.box[0], min(p.box[1], w.box[1]), w.box[2], max(p.box[3], w.box[3])))
                continue
        out.append(w)
    return out


def body_words(lines: list[Line], start: BodyStart, limit: int = 40) -> list[BodyWord]:
    """Words from the body start onward, exactly as printed (punctuation kept), joining
    words hyphenated across lines. Free-standing punctuation (a lone dash) isn't a word."""
    out: list[BodyWord] = []
    rows = [_rejoin_glued(ln.words[start.word:] if i == start.line else ln.words) for i, ln in enumerate(lines)]
    li, wi = start.line, 0
    while li < len(rows) and len(out) < limit:
        words = rows[li]
        while wi < len(words) and len(out) < limit:
            w = words[wi]
            last_on_line = wi == len(words) - 1
            if last_on_line and w.text.endswith("-") and len(w.text) > 1 and li + 1 < len(rows) and rows[li + 1]:
                nxt = rows[li + 1][0]
                joined = w.text[:-1] + nxt.text
                note = f"'{w.text} {nxt.text}' was hyphenated across a line break; joined as '{joined}'"
                out.append(BodyWord(joined, min(w.conf, nxt.conf), note, li + 1, nxt.box))
                li, wi = li + 1, 1
                words = rows[li]
                continue
            if w.text[-1:] in APOSTROPHES and len(w.text) > 1 and not last_on_line:
                # Elided forms never stand alone: OCR spacing "qu' une" means "qu'une".
                nxt = words[wi + 1]
                out.append(BodyWord(w.text + nxt.text, min(w.conf, nxt.conf), None, li,
                                    (w.box[0], min(w.box[1], nxt.box[1]), nxt.box[2], max(w.box[3], nxt.box[3]))))
                wi += 2
                continue
            if is_word(w.text):
                out.append(BodyWord(w.text, w.conf, None, li, w.box))
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
