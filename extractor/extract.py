"""Derive the two output fields from one engine's lines, then reconcile the engines."""
from __future__ import annotations

from dataclasses import dataclass, field

from .dates import DateFound, pick_release_date
from .layout import BodyWord, align_body_start, body_words, find_body_start
from .models import Line
from .words import strip_leading_articles

N_WORDS = 5
# A field is only "verified" if the engines agree character-for-character AND every word
# clears these. Agreement is the main gate: EasyOCR scores short words like "of" low
# even when read correctly, so its floor only catches reads it was itself unsure of.
MIN_CONF = {"tesseract": 90.0, "easyocr": 30.0}


@dataclass
class EngineReading:
    engine: str
    date: DateFound | None
    words: list[BodyWord]
    date_flags: list[str] = field(default_factory=list)
    word_flags: list[str] = field(default_factory=list)
    anchor: tuple[Line, int, Line | None] | None = None  # body line, word index, dateline line


def read_fields(engine: str, lines: list[Line], lang: str | None,
                anchor: tuple[Line, int, Line | None] | None = None) -> EngineReading:
    """anchor: where the primary engine found the body, so a second engine reads the same spot."""
    start = align_body_start(lines, *anchor) if anchor else find_body_start(lines)
    if start is None:
        date, dflags = pick_release_date(lines, len(lines), None)
        nobody = ["could not find the article body"]
        return EngineReading(engine, date, [], nobody + dflags, nobody)
    # Where the body starts also decides what counts as header, so layout doubts hit both fields.
    date_flags, word_flags = list(start.flags), list(start.flags)
    dateline = None
    if start.dateline is not None:
        dl = lines[start.dateline]
        # Only the part of the dateline before the body; dates in the body are about events.
        dateline = Line(dl.words[:start.word]) if start.dateline == start.line else dl
        if not dateline.words:
            dateline = None
    header_end = min(start.line, start.dateline if start.dateline is not None else start.line)
    date, dflags = pick_release_date(lines, header_end, dateline)
    date_flags.extend(dflags)

    words = body_words(lines, start)
    remaining, removed = strip_leading_articles([w.text for w in words], lang)
    kept = words[len(words) - len(remaining):]
    if kept and remaining and kept[0].text != remaining[0]:  # elided article was split off
        kept[0] = BodyWord(remaining[0], kept[0].conf, kept[0].note)
    if removed and lang is None:
        word_flags.append(f"language unknown; removed leading word(s) {removed} as articles")
    first = kept[:N_WORDS]
    if len(first) < N_WORDS:
        word_flags.append(f"only {len(first)} body word(s) found")
    word_flags.extend(w.note for w in first if w.note)
    body_anchor = (lines[start.line], start.word, lines[start.dateline] if start.dateline is not None else None)
    return EngineReading(engine, date, first, date_flags, word_flags, body_anchor)


@dataclass
class FieldResult:
    value: str
    confidence: float  # Tesseract's lowest word confidence if the engines agree; 0 if not
    reasons: list[str]  # empty means verified


def _merge_flags(flag_lists: list[tuple[str, list[str]]]) -> list[str]:
    """Flags every engine raised are listed once; engine-specific ones get an engine prefix."""
    out: list[str] = []
    for engine, flags in flag_lists:
        for f in flags:
            text = f if all(f in fl for _, fl in flag_lists) else f"{engine}: {f}"
            if text not in out:
                out.append(text)
    return out


def _low_conf_reasons(r: EngineReading, confs: list[tuple[str, float]]) -> list[str]:
    limit = MIN_CONF[r.engine]
    return [f"{r.engine} confidence {c:.0f} < {limit:.0f} on '{t}'" for t, c in confs if c < limit]


def _alnum(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())


def reconcile_date(readings: list[EngineReading]) -> FieldResult:
    reasons = _merge_flags([(r.engine, r.date_flags) for r in readings])
    primary = next((r for r in readings if r.date), None)
    if primary is None:
        return FieldResult("", 0.0, reasons + ["no release date found"])
    if primary is not readings[0]:
        reasons.append(f"date only read by {primary.engine}")
    d = primary.date
    agree = primary is readings[0]
    for r in readings:
        if r is primary:
            continue
        if r.date is None:
            reasons.append(f"{r.engine} found no date")
            agree = False
        elif r.date.iso != d.iso or _alnum(r.date.printed) != _alnum(d.printed):
            reasons.append(f"engines disagree on date: {primary.engine} '{d.printed}' vs {r.engine} '{r.date.printed}'")
            agree = False
    for r in readings:
        if r.date:
            reasons.extend(_low_conf_reasons(r, [(r.date.printed, r.date.min_conf)]))
    return FieldResult(d.iso, d.min_conf if agree else 0.0, reasons)


def reconcile_words(readings: list[EngineReading]) -> FieldResult:
    reasons = _merge_flags([(r.engine, r.word_flags) for r in readings])
    primary = next((r for r in readings if r.words), readings[0])
    value = " ".join(w.text for w in primary.words)
    if not value:
        return FieldResult("", 0.0, reasons + ["no article words found"])
    agree = primary is readings[0]
    if not agree:
        reasons.append(f"first words only read by {primary.engine}")
    for r in readings:
        if r is primary:
            continue
        other = " ".join(w.text for w in r.words)
        if other != value:
            reasons.append(f"engines disagree on first words: {primary.engine} '{value}' vs {r.engine} '{other}'")
            agree = False
    for r in readings:
        reasons.extend(_low_conf_reasons(r, [(w.text, w.conf) for w in r.words]))
    conf = min(w.conf for w in primary.words) if agree else 0.0
    return FieldResult(value, conf, reasons)
