"""The folder pass: turn a folder's OCR'd pages into one row per release.

Pages are grouped into releases (a release can run over several pages) and, when the folder
holds a list page ("News releases sent out"), each release is matched to its subject line.
Anything not settled by clear evidence is flagged, never guessed.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field, replace

from .listpage import ListEntry, parse_list_pages
from .pages import group_pages
from .pipeline import PageResult, Row
from .subjects import Match, Release, match_subjects

SUBJECT_MIN_CONF = 85.0  # Tesseract's floor for the words of a subject read as "verified"


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


def _apply_match(row: Row, match: Match, entries: list[ListEntry]) -> None:
    row.subject_match = match.method
    if match.entry is None:
        options = f" (possible: {_candidates(entries, match.candidates)})" if match.candidates else ""
        _add_reasons(row, ("no subject found in the list page" if match.method == "none"
                           else "subject could not be settled") + options)
        row.subject_verified = "NO"
        return
    entry = entries[match.entry]
    if match.shared:  # one list line covers several releases, so each keeps its own title
        row.subject, row.subject_verified, row.subject_match = row.first_five_words, row.words_verified, "shared"
        return
    row.subject = entry.subject
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
    elif entry.min_conf < SUBJECT_MIN_CONF:
        _add_reasons(row, "subject text was read with low confidence; check its spelling")
    row.subject_verified = "YES" if match.confident and entry.min_conf >= SUBJECT_MIN_CONF else "NO"


def assemble_folder(folder: str, pages: list[PageIn]) -> FolderOutput:
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
            _apply_match(row, result.matches[i], entries)
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
