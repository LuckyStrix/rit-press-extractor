"""The folder pass: turn a folder's OCR'd pages into one row per release.

Pages are grouped into releases (a release can run over several pages) and, when the folder
holds a list page ("News releases sent out"), each release is matched to its subject line.
Anything not settled by clear evidence is flagged, never guessed.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field, replace

from .listpage import ListEntry, parse_list_pages, word_key, word_parts
from .pages import group_pages
from .pipeline import PageResult, Row
from .subjects import Match, Release, match_subjects

SUBJECT_MIN_CONF = 85.0  # Tesseract's floor for the words of a subject read as "verified"
TYPO_MIN_LEN, TYPO_MAX_OFF = 5, 2  # a subject word this long, this many letters off a release word


@dataclass
class PageIn:
    """One page of a folder, in scan order."""
    file: str
    page: int
    item: str
    result: PageResult


@dataclass
class FolderOutput:
    rows: list[Row]
    unmatched: list[ListEntry]  # list entries no release claimed
    summary: dict[str, int]
    consumed: set[tuple[str, int]]  # every (file, page) this output replaces in an existing CSV
    release_pages: list[list[tuple[str, int]]] = field(default_factory=list)  # (file, page) of each row's pages
    list_pages: list[tuple[str, int]] = field(default_factory=list)  # (file, page) of the list page(s)


def _add_reasons(row: Row, *reasons: str) -> None:
    reasons = tuple(r for r in reasons if r)
    if reasons:
        row.needs_review = "YES"
        row.review_reasons = " | ".join(filter(None, [row.review_reasons, *reasons]))


def _candidates(entries: list[ListEntry], idxs: list[int]) -> str:
    return "; ".join(f"'{entries[i].subject}'" for i in idxs)


def _subject_doubts(entry: ListEntry, release: Release) -> list[str]:
    """The subject's words that may be misread. A word is sure when the release's own text (its
    slug and opening words) spells it the same: it has then been read twice, independently.
    Otherwise Tesseract must have read it surely on the list, and, where other engines read the
    page too, one of them must have read the same letters. Words joined by a dash on the list
    ("reception-Ellingson") are found part by part."""
    if not entry.word_confs:
        return [] if entry.min_conf >= SUBJECT_MIN_CONF else [entry.subject]
    seen = {k for w in release.slug.split() + release.text.split() for k in word_parts(w)}
    return [w for w, conf, also in entry.word_confs
            if word_key(w) and not all(k in seen for k in word_parts(w)) and (conf < SUBJECT_MIN_CONF or also is False)]


def _subject_typos(entry: ListEntry, release: Release) -> list[tuple[str, str]]:
    """Subject words the release's own text spells a letter or two differently ("entollment" on
    the list, "enrollment" in the release). Every engine can read such a word the same, because it
    is typed that way (or struck over), so only the release can show it; either copy may be the
    misspelled or misread one. Words of different length (plurals) are left alone."""
    seen = {k for w in release.slug.split() + release.text.split() for k in word_parts(w)}
    typos = []
    for w in entry.subject.split():
        for k in word_parts(w):
            near = [s for s in sorted(seen) if k not in seen and _letters_off(k, s)]
            if near:
                typos.append((w, near[0]))
    return typos


def _letters_off(a: str, b: str) -> bool:
    return len(a) == len(b) >= TYPO_MIN_LEN and 0 < sum(x != y for x, y in zip(a, b)) <= TYPO_MAX_OFF


def _apply_match(row: Row, match: Match, entries: list[ListEntry], release: Release) -> None:
    row.subject_match = match.method
    if match.entry is None:
        row.subject_verified = "NO"
        if match.method == "none" and not match.candidates:
            return  # no list entry fits: nothing for a person to settle (subject_match says "none")
        options = f" (possible: {_candidates(entries, match.candidates)})" if match.candidates else ""
        _add_reasons(row, ("no subject found in the list page" if match.method == "none"
                           else "subject could not be settled") + options)
        return
    entry = entries[match.entry]
    if match.shared:  # one list line covers several releases, so each keeps its own title
        row.subject, row.subject_verified, row.subject_match = row.first_five_words, row.words_verified, "shared"
        return
    row.subject = entry.subject
    typos = _subject_typos(entry, release)
    doubts = [w for w in _subject_doubts(entry, release) if w not in {t for t, _ in typos}]
    if match.duplicate:
        _add_reasons(row, "another release in the folder reads the same and has the same subject; "
                          "check for a duplicate copy")
    if match.method == "date":
        _add_reasons(row, "subject matched by date only; the release text does not confirm it")
    elif match.method == "text":
        listed = entry.date.isoformat() if entry.date else ""
        _add_reasons(row, "subject matched by its text only" + (
            "" if listed == row.release_date else f"; its list entry is dated {listed}" if listed and row.release_date
            else "; no list entry carries this release's date"))
    else:
        if doubts:
            _add_reasons(row, f"subject may be misread ({', '.join(repr(w) for w in doubts)}); check its spelling")
        if typos:
            _add_reasons(row, "subject may have a typo (" + ", ".join(f"list {w!r}, release {r!r}" for w, r in typos)
                         + "); check which spelling is right")
    row.subject_verified = "YES" if match.confident and not doubts and not typos else "NO"


def _leading_lists(pages: list[PageIn]) -> list[PageIn]:
    """List pages come before the releases in a scan, never among them: a page taken for a list
    after a release of the same file is read as the release it is."""
    after_release: set[str] = set()
    kept = []
    for p in pages:
        if p.result.list_lines is not None and p.file in after_release and p.result.as_release is not None:
            p = replace(p, result=p.result.as_release)
        if p.result.list_lines is None:
            after_release.add(p.file)
        kept.append(p)
    return kept


def assemble_folder(folder: str, pages: list[PageIn]) -> FolderOutput:
    pages = _leading_lists(pages)
    list_pages = [p for p in pages if p.result.list_lines is not None]
    release_pages = [p for p in pages if p.result.list_lines is None and p.result.row is not None]
    groups = group_pages([p.result.signals for p in release_pages])

    rows: list[Row] = []
    members_of: list[list[tuple[str, int]]] = []
    texts: list[Release] = []
    for g in groups:
        members = [release_pages[i] for i in g.pages]
        first = members[0]
        row = replace(first.result.row, folder=folder, page_count=len(members),
                      pages=", ".join(f"{m.file} p{m.page}" for m in members))
        _add_reasons(row, *g.flags)
        rows.append(row)
        members_of.append([(m.file, m.page) for m in members])
        date = row.release_date
        # A later page's "RIT/<slug>" line names the release too ("RIT/ASEE Conference").
        tags = " ".join(w for m in members[1:] for w in sorted(m.result.signals.tag))
        texts.append(Release(len(rows) - 1, _as_date(date), row.date_verified == "YES",
                             " ".join(filter(None, [first.result.slug, tags])), first.result.opening))

    summary = {"list_pages": len(list_pages), "entries": 0, "releases": len(rows), "matched": 0,
               "ambiguous": 0, "no_subject": 0, "unmatched_entries": 0}
    unmatched: list[ListEntry] = []
    if list_pages:
        dates = [d for r in rows if (d := _as_date(r.release_date))]
        years, months = Counter(d.year for d in dates), Counter(d.month for d in dates)
        parsed = parse_list_pages([p.result.list_lines for p in list_pages],
                                  years.most_common(1)[0][0] if years else None,
                                  months.most_common(1)[0][0] if months else None)
        entries = parsed.entries
        result = match_subjects(texts, entries)
        for i, row in enumerate(rows):
            _apply_match(row, result.matches[i], entries, texts[i])
        unmatched = [entries[i] for i in result.unmatched_entries]
        outcomes = Counter("matched" if m.entry is not None else "ambiguous" if m.candidates else "no_subject"
                           for m in result.matches.values())
        summary.update(entries=len(entries), matched=outcomes["matched"], ambiguous=outcomes["ambiguous"],
                       no_subject=outcomes["no_subject"], unmatched_entries=len(unmatched))
    consumed = {(p.file, p.page) for p in pages}
    return FolderOutput(rows, unmatched, summary, consumed, members_of, [(p.file, p.page) for p in list_pages])


def _as_date(iso: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(iso)
    except ValueError:
        return None
