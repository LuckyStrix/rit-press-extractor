"""Match list-page subjects to releases.

The date narrows a release to the entries printed for its day (up to five or more releases
share a day), and what the release says (its slug line and opening text) picks among them.
Words that many subjects share ("Co-op", "NTID") count for little, a person's name for a lot.
A subject is only handed out when the evidence clearly favours it; otherwise the candidates
are listed for a person to choose from.
"""
from __future__ import annotations

import datetime as dt
import difflib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from .listpage import ListEntry

MIN_TEXT_SCORE = 0.5  # share of a subject's weight that must appear in the release to count as support
MIN_MARGIN = 0.2  # a match must beat every rival, for the release and for the entry, by this much
FALLBACK_MIN, FALLBACK_MARGIN = 0.6, 0.3  # stricter when the date can't narrow the choice
MAX_CANDIDATES = 4
SAME_TEXT = 0.9  # releases whose opening text agrees this closely are copies of one release
ORDER_BONUS = 0.02  # tie-break only: the list and the scan pile are in the same order
BACKING_LEN = 5  # the shortest word that backs a match made by elimination
_STOP = {"the", "and", "for", "from", "with", "new", "of"}


@dataclass
class Release:
    key: object  # whatever identifies the release to the caller
    date: dt.date | None
    date_verified: bool
    slug: str  # the short subject tag printed under the date, if any
    text: str  # opening words of the release
    body: str = ""  # every word of every page of the release; checks a subject's spelling, not its match


@dataclass
class Match:
    entry: int | None  # index into the entries; None if no subject can be given
    method: str  # "date+text", "date", "text" or "none"
    confident: bool
    score: float = 0.0
    candidates: list[int] = field(default_factory=list)  # plausible entries when not settled
    shared: bool = False  # several releases claim this entry (one list line covering many releases)
    duplicate: bool = False  # several releases claim this entry and read the same: copies of one release


@dataclass
class MatchResult:
    matches: dict[object, Match]
    unmatched_entries: list[int]  # entries no release claimed or could be mistaken for


def _tokens(text: str, parts: bool = False) -> list[str]:
    """parts: a hyphenated word also gives its parts (for a release's text, so that its
    "transportation-distribution" supports the subject "Transportation Seminar")."""
    text = re.sub(r"(?<=\w)['’](?=\w)", "", text.lower())  # "rit's" -> "rits"
    words = re.findall(r"[a-z0-9]+", re.sub(r"(?<=\w)-(?=\w)", "", text))  # "co-op" -> "coop"
    if parts:
        words += [w for w in re.findall(r"[a-z0-9]+", text) if w not in words]
    # a plural names the same thing ("Additions to staff", "the addition of seven")
    return [t[:-1] if len(t) >= 5 and t.endswith("s") and not t.endswith("ss") else t
            for t in words if len(t) >= 3 and t not in _STOP]


def _compounds(text: str) -> dict[str, list[str]]:
    """A subject's hyphenated words, joined as _tokens joins them, and their parts: the release
    may write them apart ("Operation-Tie up" against "OPERATION TIE-UP")."""
    return {_tokens(w)[0]: parts for w in re.findall(r"\w+(?:-\w+)+", text.lower())
            if _tokens(w) and len(parts := _tokens(w.replace("-", " "))) > 1}


class _Scorer:
    def __init__(self, entries: list[ListEntry]):
        self.tokens = [_tokens(e.subject) for e in entries]
        self.compounds = [_compounds(e.subject) for e in entries]
        df = Counter(t for toks in self.tokens for t in set(toks))
        n = len(entries)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self._release: dict[int, set[str]] = {}

    def release_tokens(self, r: Release) -> set[str]:
        key = id(r)
        if key not in self._release:
            self._release[key] = set(_tokens(r.slug, parts=True)) | set(_tokens(r.text, parts=True))
        return self._release[key]

    def score(self, r: Release, entry_idx: int, min_len: int = 0) -> float:
        """min_len: only words this long count as support (a short one, "time", turns up by chance)."""
        toks = self.tokens[entry_idx]
        pool = self.release_tokens(r)
        total = sum(self.idf[t] for t in toks)
        if not toks or total <= 0:
            return 0.0
        got = 0.0
        for t in toks:
            if len(t) < min_len:
                continue
            if t in pool or all(p in pool for p in self.compounds[entry_idx].get(t, [""])):
                got += self.idf[t]
            elif len(t) >= 4:  # OCR noise: one or two characters off
                best = max((difflib.SequenceMatcher(None, t, p).ratio() for p in pool if abs(len(p) - len(t)) <= 2),
                           default=0.0)
                if best >= 0.8:
                    got += self.idf[t] * best
        return got / total


def match_subjects(releases: list[Release], entries: list[ListEntry]) -> MatchResult:
    scorer = _Scorer(entries)
    by_day: dict[dt.date, list[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        if e.date is not None:
            by_day[e.date].append(i)
    matches: dict[object, Match] = {}
    settled: set[int] = set()  # entries given to a release
    touched: set[int] = set()  # entries given or named as a candidate

    groups: dict[dt.date, list[Release]] = defaultdict(list)
    loose: list[Release] = []
    for r in releases:
        (groups[r.date] if r.date in by_day else loose).append(r)

    for day, rels in groups.items():
        _match_day(rels, by_day[day], scorer, matches, settled, touched)

    # A release its own day's entries could not settle (the list's day can be misread, or a
    # day off) is tried against every entry still free, as is one whose date the list lacks.
    # Failing that, its text may point clearly at an entry already given to another release
    # (a line such as "Apprentice program AND CORRECTION" covers a release and the memo
    # correcting it).
    free = [i for i in range(len(entries)) if i not in settled]
    unsettled = [r for rels in groups.values() for r in rels if matches[r.key].entry is None]
    for r in loose + unsettled:
        scores = sorted(((scorer.score(r, i), i) for i in free), reverse=True)
        best, second = (scores[0][0], scores[1][0]) if len(scores) > 1 else ((scores[0][0], 0.0) if scores else (0.0, 0.0))
        shared = sorted(((scorer.score(r, i), i) for i in range(len(entries))), reverse=True)
        if scores and best >= FALLBACK_MIN and best - second >= FALLBACK_MARGIN:
            matches[r.key] = Match(scores[0][1], "text", False, best)
            touched.add(scores[0][1])
        elif shared and shared[0][1] not in free and shared[0][0] >= FALLBACK_MIN \
                and shared[0][0] - (shared[1][0] if len(shared) > 1 else 0.0) >= _shared_margin(r, entries[shared[0][1]]):
            matches[r.key] = Match(shared[0][1], "text", False, shared[0][0])
        else:
            near = [i for s, i in scores[:MAX_CANDIDATES] if s >= 0.4]
            if r.key not in matches:
                matches[r.key] = Match(None, "none", False, best, near)
            elif matches[r.key].candidates:
                continue  # keep the day's candidates
            else:
                matches[r.key].candidates = near
            touched.update(near)
    # Two releases can settle on one entry through the fallback; keep it for neither.
    claims = Counter(m.entry for m in matches.values() if m.entry is not None and m.method == "text")
    for m in matches.values():
        if m.entry is not None and m.method == "text" and claims[m.entry] > 1:
            m.candidates, m.entry, m.method = [m.entry], None, "none"
    _eliminate(releases, entries, scorer, matches, touched)
    return MatchResult(matches, [i for i in range(len(entries)) if i not in touched])


def _shared_margin(r: Release, e: ListEntry) -> float:
    """How far an entry already given to another release must lead the rest for this release to
    share it: by the usual margin if it is listed within a day of the release, else by more."""
    near = r.date and e.date and abs((e.date - r.date).days) <= 1
    return MIN_MARGIN if near else FALLBACK_MARGIN


def _eliminate(releases: list[Release], entries: list[ListEntry], scorer: _Scorer, matches: dict,
               touched: set) -> None:
    """A release still without a subject gets an entry no release has taken, unverified: the
    only one of those listed within a day of its date that its text supports (by a word of
    five letters or more), or, with no support, the only one listed within a day that is
    listed on its very day. Some entries have no release in the folder, so a release only
    takes an entry its text supports better than that of every other waiting release that
    could take it."""
    changed = True
    while changed:
        changed = False
        taken = {m.entry for m in matches.values() if m.entry is not None}
        free = [i for i, e in enumerate(entries) if i not in taken and e.date is not None]
        near = {r.key: [i for i in free if abs((entries[i].date - r.date).days) <= 1]
                for r in releases if matches[r.key].entry is None and r.date is not None}
        waiting = [r for r in releases if near.get(r.key)]
        for r in waiting:
            cands = near[r.key]
            backed = [i for i in cands if scorer.score(r, i, BACKING_LEN) > 0]
            pick = backed[0] if len(backed) == 1 else None
            if not backed and len(cands) == 1 and entries[cands[0]].date == r.date:
                pick = cands[0]
            if pick is None:
                continue
            rivals = [o for o in waiting if o is not r and pick in near[o.key]]
            if rivals and not all(scorer.score(r, pick) > scorer.score(o, pick) for o in rivals):
                continue
            matches[r.key] = Match(pick, "date", False, scorer.score(r, pick))
            touched.add(pick)
            changed = True
            break


def _same_text(rels: list[Release]) -> bool:
    """Do these releases open with the same words (a second copy filed with the first)?"""
    texts = [" ".join(_tokens(r.text)) for r in rels]
    return all(t and difflib.SequenceMatcher(None, texts[0], t).ratio() >= SAME_TEXT for t in texts)


def _match_day(rels: list[Release], idxs: list[int], scorer: _Scorer, matches: dict, settled: set, touched: set) -> None:
    n, m = len(rels), len(idxs)
    score = np.array([[scorer.score(r, e) for e in idxs] for r in rels])

    # A release claims the entry its text clearly points to. One list line can cover several
    # releases (hometown versions of one story), so claims on the same entry are shared.
    claimed: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        j = int(np.argmax(score[i]))
        rivals = [score[i, k] for k in range(m) if k != j]
        if score[i, j] >= MIN_TEXT_SCORE and score[i, j] - max(rivals, default=0.0) >= MIN_MARGIN:
            claimed[j].append(i)
    # A release sharing an entry with others, but the only one an unclaimed entry fits, is the
    # release that entry names ("Kenneth A. Ross Co-op" beside the "Co-op Students" that fits
    # every co-op release of the day).
    for j, owners in list(claimed.items()):
        for i in list(owners) if len(owners) > 1 else []:
            own = [k for k in range(m) if k not in claimed and score[i, k] >= MIN_TEXT_SCORE
                   and all(score[o, k] < MIN_TEXT_SCORE for o in range(n) if o != i)]
            if len(own) == 1:
                owners.remove(i)
                claimed[own[0]] = [i]
    done_rels = {i for owners in claimed.values() for i in owners}
    for j, owners in claimed.items():
        copies = len(owners) > 1 and _same_text([rels[i] for i in owners])
        for i in owners:
            matches[rels[i].key] = Match(idxs[j], "date+text", True, float(score[i, j]),
                                         shared=len(owners) > 1 and not copies, duplicate=copies)
        settled.add(idxs[j])

    # The rest are settled among the entries nobody has claimed.
    rest_r = [i for i in range(n) if i not in done_rels]
    rest_c = [j for j in range(m) if j not in claimed]
    if not rest_r:
        touched |= settled
        return
    sub = score[np.ix_(rest_r, rest_c)] if rest_c else np.zeros((len(rest_r), 0))
    order = np.array([[1 - abs(i - j) / max(n, m) for j in rest_c] for i in rest_r]).reshape(len(rest_r), len(rest_c)) * ORDER_BONUS
    chosen: dict[int, int] = {}
    if rest_c:
        rows, cols = linear_sum_assignment(sub + order, maximize=True)
        chosen = dict(zip(rows.tolist(), cols.tolist()))
    for a, i in enumerate(rest_r):
        key = rels[i].key
        if a not in chosen:
            matches[key] = Match(None, "none", False)
            continue
        b = chosen[a]
        s = float(sub[a, b])
        rivals = [sub[a, k] for k in range(len(rest_c)) if k != b] + [sub[k, b] for k in range(len(rest_r)) if k != a]
        margin = s - max(rivals, default=0.0)
        if len(rest_r) == 1 and len(rest_c) == 1 and s >= MIN_TEXT_SCORE:
            matches[key] = Match(idxs[rest_c[0]], "date+text", True, s)
            settled.add(idxs[rest_c[0]])
        elif s >= MIN_TEXT_SCORE and margin >= MIN_MARGIN:
            matches[key] = Match(idxs[rest_c[b]], "date+text", True, s)
            settled.add(idxs[rest_c[b]])
        else:
            ranked = sorted(range(len(rest_c)), key=lambda k: -sub[a, k])[:MAX_CANDIDATES]
            cands = [idxs[rest_c[k]] for k in ranked if sub[a, k] >= max(sub[a, ranked[0]] - MIN_MARGIN, 0)]
            matches[key] = Match(None, "date+text" if s > 0 else "date", False, s, cands)
            touched.update(cands)
    touched |= settled
