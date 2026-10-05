"""Focused second read of just the release date and the article's opening words.

The full-page pass finds *where* the fields are. Here each field's row is cropped,
scaled so the text is the height OCR engines read best, contrast-boosted, and read
again by both engines in single-line mode. Small marks (periods, apostrophes) that
get lost when a whole page is shrunk to fit an engine survive at this scale.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from . import ocr
from .dates import DateFound, parse_dates_in_line
from .extract import EngineReading, first_words
from .layout import BodyStart, BodyWord, body_words
from .models import Box, Line

TARGET_WORD_H = 48  # px; word height at which both engines read typewriter text best
MAX_ROWS = 4  # the first five words never span more lines than this

# Tesseract variants for --multipass: (thresholding method, contrast boost)
VARIANTS = [(2, True), (0, True), (2, False)]


@dataclass
class Region:
    box: Box
    text_h: float  # typical word height in this row, for scaling


@dataclass
class Regions:
    date: Region | None
    rows: list[Region]


def _median_h(boxes: list[Box]) -> float:
    hs = sorted(b[3] - b[1] for b in boxes)
    return max(hs[len(hs) // 2], 1) if hs else 1.0


def regions_from(lines: list[Line], reading: EngineReading) -> Regions:
    """Crop regions from the primary engine's full-page reading."""
    date = None
    if reading.date and reading.date.box:
        date = Region(reading.date.box, reading.date.box[3] - reading.date.box[1])
    rows: list[Region] = []
    st = reading.start
    if st is not None and reading.words and st.word < len(lines[st.line].words):
        last = min(max(w.line for w in reading.words), st.line + MAX_ROWS - 1)
        for li in range(st.line, last + 1):
            words = lines[li].words[st.word:] if li == st.line else lines[li].words
            if not words:
                continue
            boxes = [w.box for w in words]
            box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
            rows.append(Region(box, _median_h(boxes)))
    return Regions(date, rows)


def _crop(page: Image.Image, region: Region, contrast: bool = True) -> Image.Image:
    x0, y0, x1, y1 = region.box
    h = region.text_h
    box = (max(0, int(x0 - 0.3 * h)), max(0, int(y0 - 0.3 * h)),
           min(page.width, int(x1 + 0.5 * h)), min(page.height, int(y1 + 0.3 * h)))
    crop = page.crop(box).convert("L")
    scale = min(max(TARGET_WORD_H / h, 0.5), 4.0)
    crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.LANCZOS)
    arr = np.array(crop)
    if contrast:
        arr = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(2, 8)).apply(arr)
    arr = cv2.copyMakeBorder(arr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return Image.fromarray(arr)


def _one_line(lines: list[Line], crop_h: int) -> Line:
    """The text line nearest the crop's vertical centre (ignores slivers of neighbouring rows)."""
    if not lines:
        return Line([])
    centre = crop_h / 2
    return min(lines, key=lambda ln: abs((ln.box[1] + ln.box[3]) / 2 - centre))


def _read_tesseract(page, region, lang, best, multipass) -> tuple[Line, str | None]:
    variants = VARIANTS if multipass else VARIANTS[:1]
    reads = []
    for threshold, contrast in variants:
        crop = _crop(page, region, contrast)
        reads.append(_one_line(ocr.tesseract_lines(crop, lang, psm=7, threshold=threshold, best=best), crop.height))
    if len(reads) == 1:
        return reads[0], None
    texts = Counter(ln.text for ln in reads)
    text, votes = texts.most_common(1)[0]
    if votes >= 2:
        agreeing = [ln for ln in reads if ln.text == text]
        line = agreeing[0]
        for i, w in enumerate(line.words):  # a word is only as sure as its least sure agreeing pass
            w.conf = min(ln.words[i].conf for ln in agreeing)
        return line, None
    return reads[0], f"tesseract passes disagree: {' / '.join(repr(t) for t in texts)}"


def _read_easyocr(page, region, langs) -> Line:
    crop = _crop(page, region)
    return _one_line(ocr.easyocr_lines(crop, langs, beam=True), crop.height)


@dataclass
class Reread:
    date: DateFound | None
    words: list[BodyWord] | None
    word_flags: list[str]
    date_notes: list[str]  # multipass disagreements while reading the date
    word_notes: list[str]


def reread(engine: str, page: Image.Image, regions: Regions, lang: str, tess_lang: str,
           easy_langs: tuple[str, ...] | None, best: bool = False, multipass: bool = False) -> Reread:
    notes: list[str] = []

    def read(region: Region) -> Line:
        if engine == "tesseract":
            line, note = _read_tesseract(page, region, tess_lang, best, multipass)
            if note:
                notes.append(note)
            return line
        return _read_easyocr(page, region, easy_langs)

    date, date_notes = None, []
    if regions.date:
        found = parse_dates_in_line(read(regions.date), 0)
        date_notes, notes[:] = list(notes), []
        if found:
            date = found[0]
            date.box = regions.date.box

    words, wflags = None, []
    if regions.rows:
        lines = [ln for ln in (read(r) for r in regions.rows) if ln.words]
        if lines:
            got, wflags = first_words(body_words(lines, BodyStart(0, 0, None)), lang)
            words = got or None
    return Reread(date, words, wflags, date_notes, notes)
