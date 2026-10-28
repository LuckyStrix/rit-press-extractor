"""Locate where the article body starts (just after the dateline) and read its words."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .dates import parse_dates_in_line
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

POSITION_ONLY_FLAG = "second engine's body start located by position only"


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


RUN_LINES = 3  # consecutive full-width lines that make a block of text rather than a header


def _full_width_run(lines: list[Line], g: _Geometry) -> int | None:
    """Index of the first line of the first block of RUN_LINES aligned lines that each run
    most of the way across the page. Header lines (release cues, contacts, dates, a
    letterhead set off to one side) are shorter, misaligned or carry a cue."""
    def body_like(ln: Line) -> bool:
        words = [w for w in ln.words if is_word(w.text)]
        return (len(words) >= 6 and ln.box[2] - ln.box[0] >= 0.7 * g.width
                and not HEADER_CUE.search(ln.text) and not NON_BODY.search(ln.text)
                and not parse_dates_in_line(ln, 0))

    for i in range(len(lines) - RUN_LINES + 1):
        run = lines[i:i + RUN_LINES]
        if all(body_like(ln) for ln in run) and all(
                abs(ln.box[0] - run[0].box[0]) / g.char_w <= ALIGN_CHARS for ln in run):
            return i
    return None


def _looks_like_dateline_prefix(prefix: str) -> bool:
    if not prefix.split() or len(prefix) > 80 or HEADER_CUE.search(prefix) or NON_BODY.search(prefix):
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

    # 3b. All-capitals typescript with no dateline or indent (double-spaced 1970 releases):
    #     no lowercase to recognise prose by, so look for the first run of full-width lines.
    if g is not None:
        i = _full_width_run(lines, g)
        if i is not None:
            return BodyStart(i, 0, None, ["no dateline or paragraph indent; body start inferred from line layout"])

    # 4. Last resort: first line that reads like prose.
    for i, line in enumerate(lines):
        toks = [w.text for w in line.words]
        if len(toks) >= 6 and _lowercase_tokens(toks) >= 3 and not HEADER_CUE.search(line.text) and not NON_BODY.search(line.text):
            return BodyStart(i, 0, None, ["no dateline found; body start was guessed; check it"])
    return None


# --- The article from a layout model's blocks (extractor/regions.py) -------------------------

TEXT_LABELS = {"text", "paragraph_title", "doc_title", "abstract", "content"}
TITLE_LABELS = {"paragraph_title", "doc_title"}
CUE_MAX_LINES = 4  # a release or contact block is a few short lines
CUE_WIDTH = 0.55  # a contact or date block is this narrow: release and contact blocks sit side by side
CUE_ZONE = 0.45  # share of the page, from the top, where they are typed
HEADING_LINES = 2  # a headline or aside above the article is a line or two
NOTE = re.compile(r"^\W*(?:note|memo|editors?|attention|please)\b", re.I)  # a note to the editors
CONTAINED = 0.9  # share of a block inside another that makes it the same block drawn again
DISAGREE_FLAG = "the layout model and the line layout disagree on where the article starts; check it"


def _block_rows(lines: list[Line], box: tuple[int, int, int, int]) -> list[tuple[int, int, Line]]:
    """The block's part of each line it covers: (line index, index of its first word, its words)."""
    def inside(w: Word) -> bool:
        cx, cy = (w.box[0] + w.box[2]) / 2, (w.box[1] + w.box[3]) / 2
        return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]

    rows = []
    for i, ln in enumerate(lines):
        if ks := [k for k, w in enumerate(ln.words) if inside(w)]:
            rows.append((i, ks[0], Line([ln.words[k] for k in ks])))
    return rows


def _is_cue(rows: list[tuple[int, int, Line]], narrow: bool) -> bool:
    """A release or contact block: a release line anywhere in it (the model may draw the
    release and contact blocks as one), or a contact or a date in a narrow one (a paragraph
    that names a date or a telephone runs the width of the page)."""
    return any(HEADER_CUE.search(ln.text) or (narrow and (NON_BODY.search(ln.text) or parse_dates_in_line(ln, 0)))
               for _, _, ln in rows)


def _short_caps(rows: list[tuple[int, int, Line]]) -> bool:
    return len(rows) <= HEADING_LINES and _all_caps([w.text for _, _, ln in rows for w in ln.words])


def _title_case(rows: list[tuple[int, int, Line]]) -> bool:
    """A single line with its words capitalised ("Library Exhibit Shows Rare Books")."""
    words = [c for _, _, ln in rows for w in ln.words if (c := clean_word(w.text)) and c[0].isalpha()]
    long = [c for c in words if len(c) > 3]  # "of", "the", "for" stay small in a title
    return len(rows) == 1 and len(long) >= 2 and all(c[0].isupper() for c in long)


def _heading(label: str, rows: list[tuple[int, int, Line]]) -> bool:
    """A headline, a note to the editors or an aside set above the article: not its first words."""
    text = " ".join(ln.text for _, _, ln in rows).strip()
    aside = len(rows) <= HEADING_LINES and text.startswith("(") and text.endswith(")")
    return label in TITLE_LABELS or bool(NOTE.match(text)) or aside or _short_caps(rows) or _title_case(rows)


def _inside(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Does box a lie (nearly) all within box b?"""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy >= CONTAINED * (a[2] - a[0]) * (a[3] - a[1])


def article_blocks(lines: list[Line], regions, page_height: int) -> list[tuple[str, list[tuple[int, int, Line]]]]:
    """The text blocks from the article's first one on, top to bottom, from the layout model's
    regions: below the release and contact blocks (short blocks near the top with a release
    line, a contact or a date), or, with none, from the first block of two or more lines below
    the letterhead. A headline, note or aside above the article is passed over, unless what
    follows is as short and as capitalised (a release typed all in capitals, a line to a block)."""
    if not lines:
        return []
    blocks = [(r, rows) for r in regions if r.label in TEXT_LABELS and (rows := _block_rows(lines, r.box))]
    # The model can draw a block twice, whole and in part: keep the whole.
    blocks = [(r, rows) for r, rows in blocks
              if not any(o is not r and _inside(r.box, o.box) and not _inside(o.box, r.box) for o, _ in blocks)]
    if not blocks:
        return []
    height = _median([w.box[3] - w.box[1] for ln in lines for w in ln.words])
    widest = max(r.box[2] - r.box[0] for r, _ in blocks)
    cues = [(r, rows) for r, rows in blocks if r.box[1] < CUE_ZONE * page_height and len(rows) <= CUE_MAX_LINES
            and _is_cue(rows, r.box[2] - r.box[0] < CUE_WIDTH * widest)]
    if cues:
        floor = max(r.box[3] for r, _ in cues)
    else:
        floor = max((r.box[3] for r in regions if r.label == "header"), default=0)
    cue_ids = {id(r) for r, _ in cues}
    cands = sorted(((r, rows) for r, rows in blocks if id(r) not in cue_ids and r.box[1] >= floor - height
                    and (cues or len(rows) >= 2)), key=lambda b: (b[0].box[1], b[0].box[0]))
    i = 0
    while i + 1 < len(cands) and _heading(cands[i][0].label, cands[i][1]) and not _short_caps(cands[i + 1][1]):
        i += 1
    return [(r.label, rows) for r, rows in cands[i:]]


def article_rows(lines: list[Line], regions, page_height: int) -> list[tuple[int, int, Line]] | None:
    """The article's first block (see article_blocks): each line it covers, with the index of
    its first word in the block."""
    blocks = article_blocks(lines, regions, page_height)
    return blocks[0][1] if blocks else None


def choose_body_start(lines: list[Line], regions, page_height: int) -> BodyStart | None:
    """Where the article starts, from the layout model's blocks and the line layout together.
    Where the line layout's start falls inside the model's article block they agree, and the
    line layout's start is kept (it knows datelines). So it is where the model could only take
    a headline (a release typed all in capitals, a line to a block) and the line layout starts
    in a block below it. Otherwise the model's block wins, and the disagreement is flagged."""
    rule = find_body_start(lines)
    blocks = article_blocks(lines, regions, page_height)
    if not blocks:
        return rule
    label, rows = blocks[0]
    if rule is not None and rule.line in {i for i, _, _ in rows}:
        return rule
    if rule is not None and _heading(label, rows) and any(rule.line in {i for i, _, _ in r} for _, r in blocks[1:]):
        return rule
    i, k, _ = rows[0]
    return BodyStart(i, k, None, [DISAGREE_FLAG] if rule is not None else [])


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
    return BodyStart(i, j, dateline, [POSITION_ONLY_FLAG])


SLUG_MAX_LINES, SLUG_MAX_WORDS = 3, 12


def find_slug(lines: list[Line], start: BodyStart) -> str:
    """The short subject tag or headline set between the header block and the article
    ("TVR" under the date). Walks up from the body; release cues, dates, contacts and the
    dateline end it."""
    out: list[str] = []
    for i in range(start.line - 1, -1, -1):
        ln = lines[i]
        if (len(out) >= SLUG_MAX_LINES or i == start.dateline or len(ln.words) > SLUG_MAX_WORDS
                or HEADER_CUE.search(ln.text) or NON_BODY.search(ln.text) or parse_dates_in_line(ln, 0)):
            break
        out.append(ln.text)
    return " ".join(reversed(out))
