"""Group scanned pages into releases (a release can run over several pages).

Each page is reduced to a few cues read from its OCR lines: does it look like a first page
(release line, header date), a continuation (page number, "continued") and does it end
with "-more-" or "-30-". Grouping then leans toward splitting: a wrong merge hides a
release, a wrong split only leaves an extra row to review, so any join made on weak
evidence is flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dates import parse_dates_in_line
from .layout import HEADER_CUE
from .models import Line

HEAD, FOOT = 8, 3  # lines inspected at the top and at the foot of a page
HEADER_DATE_WORDS = 7  # a header date sits on a short line; a long line is body text naming a date
_DASH = r"[-–—_~]"
_PAGE_NUMBER = [
    re.compile(r"^\W*(?:page\s*)?(\d{1,2})\W*$", re.I),  # "2", "Page 2", "- 2 -"
    re.compile(r"\bpage\s+(\d{1,2})\b", re.I),
    re.compile(rf"(?:^|\s){_DASH}+\s*(\d{{1,2}})\s*{_DASH}?\s*$"),  # "RIT News Release - 2", "add ~- 2"
]
_CONTINUED = re.compile(r"\(?\bcont(?:inued|'d)\b\)?", re.I)
# "RIT/Fillers --add 1--": a later page's slug and its page count, "add 1" being the second page
_ADD = re.compile(r"\badd\W{0,4}([0-9lI]{1,2})\b", re.I)
_TAG = re.compile(r"^\W*RIT\s*/\s*(.+?)(?:\W+add\b.*)?$", re.I)
# Printed stationery appears only on a release's first page.
LETTERHEAD = re.compile(r"\bone\s+lomb\s+memorial\b|\boffice\s+of\s+public\s+relations\b|\bsports\s+news\b"
                        r"|\bnews\s+from\b", re.I)
_TAG_SKIP = {"rit", "news", "release", "the", "and", "for", "add"}
_MORE = re.compile(r"^[\W_]*\(?\s*[mn]ore\s*\)?[\W_]*$", re.I)  # OCR reads "-more-" as "=nore=" too


@dataclass
class PageSignals:
    starts: bool = False  # looks like the first page of a release
    cont: bool = False  # looks like a later page of one
    more: bool = False  # ends with "-more-"
    end: bool = False  # ends with "-30-" or "###"
    tag: set[str] = field(default_factory=set)  # words of a later page's "RIT/<slug>" line
    words: set[str] = field(default_factory=set)  # every word on the page


@dataclass
class Group:
    pages: list[int]
    flags: list[str] = field(default_factory=list)


def _words(text: str) -> set[str]:
    """The page's words, and the initials of each run of capitalised words, so that a slug
    "RIT/ASEE" fits a release about the "American Society for Engineering Education"."""
    words = {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _TAG_SKIP}
    for run in re.findall(r"[A-Z][a-z]+(?:\s+(?:(?:for|of|and|the|on|in|&)\s+)?[A-Z][a-z]+)+", text):
        initials = "".join(w[0] for w in run.split() if w[0].isupper()).lower()
        if len(initials) >= 3:
            words.add(initials)
    return words


def _continuation_cue(lines: list[Line], letterhead: bool) -> bool:
    """A page number or "continued" at the top. Under a letterhead a lone number is a speck."""
    for ln in lines[:4]:
        text = ln.text
        if _CONTINUED.search(text):
            return True
        if (m := _ADD.search(text)) and int(m.group(1).replace("l", "1").replace("I", "1")) >= 1:
            return True
        for pattern in _PAGE_NUMBER[1:] if letterhead else _PAGE_NUMBER:
            m = pattern.search(text)
            if m and int(m.group(1)) >= 2:
                return True
    return False


def _end_marker(text: str) -> bool:
    """'-30-', '-end-', '###' or '# # #' on a line of its own."""
    core = re.sub(r"[\s*\-–—_~]", "", text)
    return core.lower() in ("30", "end", "ends") or bool(re.fullmatch(r"#{3,}", core))


def has_release_header(lines: list[Line]) -> bool:
    """A release line ("FOR IMMEDIATE RELEASE") or a header date near the top."""
    head = lines[:HEAD]
    return any(HEADER_CUE.search(ln.text) for ln in head) or any(
        len(ln.words) <= HEADER_DATE_WORDS and parse_dates_in_line(ln, 0) for ln in head)


def page_signals(lines: list[Line]) -> PageSignals:
    foot = lines[-FOOT:]
    letterhead = any(LETTERHEAD.search(ln.text) for ln in lines[:4])
    starts = letterhead or has_release_header(lines)
    tag = next((_words(m[1]) for ln in lines[:2] if (m := _TAG.match(ln.text))), set())
    return PageSignals(
        starts=starts,
        cont=_continuation_cue(lines, letterhead),
        more=any(_MORE.match(ln.text) for ln in foot),
        end=any(_end_marker(ln.text) for ln in foot),
        tag=tag,
        words=_words(" ".join(ln.text for ln in lines)),
    )


def group_pages(pages: list[PageSignals]) -> list[Group]:
    groups: list[Group] = []
    words: set[str] = set()  # of the release being built
    for i, s in enumerate(pages):
        if groups and s.tag and not s.tag & words and not s.starts and not pages[groups[-1].pages[-1]].more:
            # A later page's slug names something the release so far never mentions (unless the
            # page before said "-more-": then the slug is more likely misread).
            groups.append(Group([i], ["a page's slug does not fit the release before it; treated as a new release"]))
            words = set(s.words)
            continue
        if groups and (s.cont or not s.starts):
            words |= s.words
        else:
            words = set(s.words)
        if not groups:
            groups.append(Group([i], ["the first page looks like a continuation (page number or 'continued' at "
                                      "the top); the start of its release is missing"] if s.cont and not s.starts else []))
            continue
        g = groups[-1]
        prev = pages[g.pages[-1]]
        if s.cont:
            g.pages.append(i)
            if s.starts:
                g.flags.append("a page has both a date or release line and a page number; joined to the release before it")
        elif s.starts:
            flags = []
            if prev.more:
                note = "the page before ended '-more-' but the next page begins a new release; check the pages"
                g.flags.append(note)
                flags.append(note)
            groups.append(Group([i], flags))
        elif prev.more:
            g.pages.append(i)
        elif prev.end:
            groups.append(Group([i], ["no release header, date or page number found; treated as a new release"]))
        else:
            g.pages.append(i)
            g.flags.append("a page with no header, date or page number was assumed to be a continuation of "
                           "the release before it; check the pages")
    return groups
