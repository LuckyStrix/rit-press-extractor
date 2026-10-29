"""The folder pass: turn a folder's OCR'd pages into one row per release.

Pages are grouped into releases (a release can run over several pages) and, when the folder
holds a list page ("News releases sent out"), each release is matched to its subject line.
Anything not settled by clear evidence is flagged, never guessed.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import lru_cache

from .listpage import ListEntry, is_unfinished, parse_list_pages, word_key, word_parts
from .pages import group_pages
from .pipeline import PageResult, Row
from .subjects import Match, Release, match_subjects

SUBJECT_MIN_CONF = 85.0  # Tesseract's floor for the words of a subject read as "verified"
TYPO_MIN_LEN, TYPO_MAX_OFF = 5, 2  # a subject word this long, this many letters off a release word
WORD_MIN_LEN = 4  # shorter subject words (initials, abbreviations) are not looked up in the word list
# A lowercase word this rare (wordfreq's Zipf scale; "and" is 7.4) is a misreading even when the
# list knows it as some abbreviation ("pnd" where a ruled line crosses "and"): abbreviations are
# typed in capitals, and the common words of a subject are frequent.
RARE_LOWER, RARE_LOWER_LEN = 3.0, 3


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


def _release_words(release: Release) -> set[str]:
    return {k for w in " ".join([release.slug, release.text, release.body]).split() for k in word_parts(w)}


def _subject_doubts(entry: ListEntry, release: Release) -> list[str]:
    """The subject's words that may be misread. A word is sure when the release's own text (any
    page of it) spells it the same: it has then been read twice, independently.
    Otherwise Tesseract must have read it surely on the list, and, where other engines read the
    page too, one of them must have read the same letters. Words joined by a dash on the list
    ("reception-Ellingson") are found part by part."""
    if not entry.word_confs:
        return [] if entry.min_conf >= SUBJECT_MIN_CONF else [entry.subject]
    seen = _release_words(release)
    return [w for w, conf, also in entry.word_confs
            if word_key(w) and not all(k in seen for k in word_parts(w)) and (conf < SUBJECT_MIN_CONF or also is False)]


def _subject_typos(entry: ListEntry, release: Release) -> list[tuple[str, str]]:
    """Subject words the release's own text spells a letter or two differently ("entollment" on
    the list, "enrollment" in the release). Every engine can read such a word the same, because it
    is typed that way (or struck over), so only the release can show it; either copy may be the
    misspelled or misread one. Words of different length (plurals) are left alone."""
    seen = _release_words(release)
    typos = []
    for w in entry.subject.split():
        for k in word_parts(w):
            near = [s for s in sorted(seen) if k not in seen and _letters_off(k, s)]
            if near:
                typos.append((w, near[0]))
    return typos


def _unknown_words(entry: ListEntry, release: Release) -> list[str]:
    """Subject words that are no English word and that the release does not name. A typo on the
    list ("Visttors") or a misreading made the same way in both copies ("alumi") passes every
    comparison between readers; only a word list shows it. A name is no English word either, but
    the release writes it with a capital letter, as it does no misread common word ("alumi").
    A rare word in lowercase is in doubt too ("pnd", "ourse")."""
    names = {k for w in " ".join([release.slug, release.text, release.body]).split()
             if w[:1].isupper() for k in word_parts(w)}
    unknown = []
    for w in entry.subject.split():
        for part in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", w):
            k = part.lower().removesuffix("'s")
            if k.replace("'", "") in names:
                continue
            freq = _zipf(k)
            if (len(k) >= WORD_MIN_LEN and freq == 0) or (part.islower() and len(k) >= RARE_LOWER_LEN and freq < RARE_LOWER):
                unknown.append(w)
                break
    return unknown


@lru_cache(maxsize=None)
def _zipf(word: str) -> float:
    """How common the word is in English (0: not a word)."""
    from wordfreq import zipf_frequency

    return zipf_frequency(word, "en")


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
    unknown = [w for w in _unknown_words(entry, release) if w not in doubts and w not in {t for t, _ in typos}]
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
        if unknown:
            _add_reasons(row, f"subject has words that are not English and not named in the release "
                              f"({', '.join(repr(w) for w in unknown)}); check their spelling")
    # A subject that stops mid-way ("(Jan.", "Manage-") lost its end on the list: words that were
    # not read at all can't be doubted one by one.
    cut = is_unfinished(entry.subject)
    if cut and match.method == "date+text":
        _add_reasons(row, "subject looks cut short (it ends mid-way); check the rest on the list page")
    row.subject_verified = "YES" if match.confident and not doubts and not typos and not unknown and not cut else "NO"


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
                             " ".join(filter(None, [first.result.slug, tags])), first.result.opening,
                             " ".join(m.result.text for m in members)))

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
