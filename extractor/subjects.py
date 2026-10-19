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
ORDER_BONUS = 0.02  # tie-break only: the list and the scan pile are in the same order
_STOP = {"the", "and", "for", "from", "with", "new", "of"}


@dataclass
class Release:
    key: object  # whatever identifies the release to the caller
    date: dt.date | None
    date_verified: bool
    slug: str  # the short subject tag printed under the date, if any
    text: str  # opening words of the release


@dataclass
class Match:
    entry: int | None  # index into the entries; None if no subject can be given
    method: str  # "date+text", "date", "text" or "none"
    confident: bool
    score: float = 0.0
    candidates: list[int] = field(default_factory=list)  # plausible entries when not settled


@dataclass
class MatchResult:
    matches: dict[object, Match]
    unmatched_entries: list[int]  # entries no release claimed or could be mistaken for


def _tokens(text: str) -> list[str]:
    text = re.sub(r"(?<=\w)[-'’](?=\w)", "", text.lower())  # "co-op" -> "coop"
    return [t for t in re.findall(r"[a-z0-9]+", text) if len(t) >= 3 and t not in _STOP]


class _Scorer:
    def __init__(self, entries: list[ListEntry]):
        self.tokens = [_tokens(e.subject) for e in entries]
        df = Counter(t for toks in self.tokens for t in set(toks))
        n = len(entries)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self._release: dict[int, set[str]] = {}

    def release_tokens(self, r: Release) -> set[str]:
        key = id(r)
        if key not in self._release:
            self._release[key] = set(_tokens(r.slug)) | set(_tokens(r.text))
        return self._release[key]

    def score(self, r: Release, entry_idx: int) -> float:
        toks = self.tokens[entry_idx]
        pool = self.release_tokens(r)
        total = sum(self.idf[t] for t in toks)
        if not toks or total <= 0:
            return 0.0
        got = 0.0
        for t in toks:
            if t in pool:
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

    free = [i for i in range(len(entries)) if i not in settled]
    for r in loose:
        scores = sorted(((scorer.score(r, i), i) for i in free), reverse=True)
        best, second = (scores[0][0], scores[1][0]) if len(scores) > 1 else ((scores[0][0], 0.0) if scores else (0.0, 0.0))
        if scores and best >= FALLBACK_MIN and best - second >= FALLBACK_MARGIN:
            matches[r.key] = Match(scores[0][1], "text", False, best)
            touched.add(scores[0][1])
        else:
            near = [i for s, i in scores[:MAX_CANDIDATES] if s >= 0.4]
            matches[r.key] = Match(None, "none", False, best, near)
            touched.update(near)
    # Two releases can settle on one entry through the fallback; keep it for neither.
    claims = Counter(m.entry for m in matches.values() if m.entry is not None and m.method == "text")
    for m in matches.values():
        if m.entry is not None and m.method == "text" and claims[m.entry] > 1:
            m.candidates, m.entry, m.method = [m.entry], None, "none"
    return MatchResult(matches, [i for i in range(len(entries)) if i not in touched])


def _match_day(rels: list[Release], idxs: list[int], scorer: _Scorer, matches: dict, settled: set, touched: set) -> None:
    n, m = len(rels), len(idxs)
    score = np.array([[scorer.score(r, e) for e in idxs] for r in rels])
    order = np.array([[1 - abs(i - j) / max(n, m) for j in range(m)] for i in range(n)]) * ORDER_BONUS
    rows, cols = linear_sum_assignment(score + order, maximize=True)
    chosen = dict(zip(rows.tolist(), cols.tolist()))
    for i, r in enumerate(rels):
        if i not in chosen:
            matches[r.key] = Match(None, "none", False)
            continue
        j = chosen[i]
        s = float(score[i, j])
        rivals_row = [score[i, k] for k in range(m) if k != j]
        rivals_col = [score[k, j] for k in range(n) if k != i]
        margin = s - max(rivals_row + rivals_col, default=0.0)
        if n == 1 and m == 1:
            matches[r.key] = Match(idxs[0], "date+text" if s >= MIN_TEXT_SCORE else "date",
                                   s >= MIN_TEXT_SCORE, s)
            settled.add(idxs[0])
        elif s >= MIN_TEXT_SCORE and margin >= MIN_MARGIN:
            matches[r.key] = Match(idxs[j], "date+text", True, s)
            settled.add(idxs[j])
        else:
            ranked = sorted(range(m), key=lambda k: -score[i, k])[:MAX_CANDIDATES]
            cands = [idxs[k] for k in ranked if score[i, k] >= max(score[i, ranked[0]] - MIN_MARGIN, 0)]
            matches[r.key] = Match(None, "date+text" if s > 0 else "date", False, s, cands)
            touched.update(cands)
    touched |= settled
