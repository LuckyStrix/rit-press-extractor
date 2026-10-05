"""Engine-neutral OCR data structures shared by every stage."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

Box = tuple[int, int, int, int]  # x0, y0, x1, y1

# Dashes OCR engines often glue onto neighbouring words ("N.Y.—The").
_DASH_SPLIT = re.compile(r"(—|–|―|‒|--)")


@dataclass
class Word:
    text: str
    conf: float  # 0-100, engine-reported
    box: Box


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def box(self) -> Box:
        return (
            min(w.box[0] for w in self.words),
            min(w.box[1] for w in self.words),
            max(w.box[2] for w in self.words),
            max(w.box[3] for w in self.words),
        )

    def words_in_span(self, start: int, end: int) -> list[Word]:
        """Words overlapping the character span [start, end) of self.text."""
        out, pos = [], 0
        for w in self.words:
            w_end = pos + len(w.text)
            if w_end > start and pos < end:
                out.append(w)
            pos = w_end + 1
        return out

    def word_index_at(self, char_pos: int) -> int:
        """Index of the first word starting at or after char_pos."""
        pos = 0
        for i, w in enumerate(self.words):
            if pos >= char_pos:
                return i
            pos += len(w.text) + 1
        return len(self.words)


def split_dashes(words: list[Word]) -> list[Word]:
    """Split glued em/en dashes into their own tokens, apportioning the box by characters."""
    out: list[Word] = []
    for w in words:
        parts = [p for p in _DASH_SPLIT.split(w.text) if p]
        if len(parts) == 1:
            out.append(w)
            continue
        x0, y0, x1, y1 = w.box
        per_char = (x1 - x0) / max(len(w.text), 1)
        cursor = x0
        for p in parts:
            width = per_char * len(p)
            out.append(Word(p, w.conf, (int(cursor), y0, int(cursor + width), y1)))
            cursor += width
    return out


def merge_rows(lines: list[Line]) -> list[Line]:
    """Join line pieces that sit on the same row (Tesseract sometimes splits one typed line
    into separate blocks), then order rows top to bottom."""
    rows: list[Line] = []
    for line in sorted(lines, key=lambda ln: (ln.box[1] + ln.box[3]) / 2):
        y0, y1 = line.box[1], line.box[3]
        for row in rows:
            r0, r1 = row.box[1], row.box[3]
            overlap = min(y1, r1) - max(y0, r0)
            no_collision = all(w.box[2] <= line.box[0] or w.box[0] >= line.box[2] for w in row.words)
            if overlap > 0.5 * min(y1 - y0, r1 - r0) and no_collision:
                row.words = sorted(row.words + line.words, key=lambda w: w.box[0])
                break
        else:
            rows.append(Line(list(line.words)))
    return sorted(rows, key=lambda ln: ln.box[1])
