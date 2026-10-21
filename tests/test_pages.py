"""Grouping scanned pages into releases: a release can run over several pages."""
from extractor.pages import PageSignals, group_pages, page_signals

from .test_units import layout_page


def sig(lines):
    return page_signals(layout_page([(100, 100 + 60 * i, t) for i, t in enumerate(lines)]))


BODY = ["The college will open a new laboratory next fall with funding from the state and",
        "several private donors, officials said on Tuesday at a press conference held on campus."]


def test_header_cue_or_short_date_line_marks_a_first_page():
    assert sig(["FOR IMMEDIATE RELEASE", "November 2, 1970", *BODY]).starts
    assert sig(["NEWS RELEASE", "November 2, 1970", *BODY]).starts
    assert not sig([*BODY, *BODY]).starts
    # a long line of body text that happens to name a date is not a header date
    assert not sig(["Officials said on November 5, 1970 that the new laboratory would open in the fall", *BODY]).starts


def test_page_number_marks_a_continuation():
    for top in ("2", "Page 2", "- 2 -", "RIT News Release - 2", "add ~- 2", "(continued)"):
        assert sig([top, *BODY]).cont, top
    assert not sig(["Page 1", *BODY]).cont
    assert not sig(["FOR IMMEDIATE RELEASE", "November 2, 1970", *BODY]).cont


def test_more_and_end_markers_at_the_foot_of_a_page():
    assert sig([*BODY, "-more-"]).more
    assert sig([*BODY, "(MORE)"]).more
    assert sig([*BODY, "=nore="]).more  # a common misread
    assert not sig([*BODY, "more people attended the ceremony than expected"]).more
    assert sig([*BODY, "-30-"]).end
    assert sig([*BODY, "###"]).end
    assert sig([*BODY, "# # #"]).end
    assert not sig([*BODY]).end


S = lambda **k: PageSignals(**{"starts": False, "cont": False, "more": False, "end": False, **k})  # noqa: E731


def test_each_first_page_starts_its_own_release():
    groups = group_pages([S(starts=True), S(starts=True), S(starts=True)])
    assert [g.pages for g in groups] == [[0], [1], [2]] and not any(g.flags for g in groups)


def test_page_number_joins_a_page_to_the_release_before_it():
    groups = group_pages([S(starts=True, more=True), S(cont=True), S(starts=True)])
    assert [g.pages for g in groups] == [[0, 1], [2]]
    assert not any(g.flags for g in groups)


def test_more_marker_joins_a_headerless_page():
    groups = group_pages([S(starts=True, more=True), S(), S(starts=True)])
    assert [g.pages for g in groups] == [[0, 1], [2]] and not groups[0].flags


def test_headerless_page_with_no_marker_is_joined_but_flagged_both_ways():
    groups = group_pages([S(starts=True), S(), S(starts=True)])
    assert [g.pages for g in groups] == [[0, 1], [2]]
    assert groups[0].flags and "continuation" in groups[0].flags[0]


def test_headerless_page_after_an_end_marker_is_a_new_flagged_release():
    groups = group_pages([S(starts=True, end=True), S(), S(starts=True)])
    assert [g.pages for g in groups] == [[0], [1], [2]]
    assert groups[1].flags and not groups[0].flags


def test_a_dated_page_is_never_swallowed_without_a_page_number():
    groups = group_pages([S(starts=True, more=True), S(starts=True)])
    assert [g.pages for g in groups] == [[0], [1]]
    assert groups[0].flags and groups[1].flags  # '-more-' promised a continuation that isn't there


def test_a_folder_that_opens_on_a_continuation_page_is_flagged():
    groups = group_pages([S(cont=True), S(starts=True)])
    assert [g.pages for g in groups] == [[0], [1]] and groups[0].flags


def test_a_page_with_both_a_date_and_a_page_number_joins_but_is_flagged():
    groups = group_pages([S(starts=True), S(starts=True, cont=True)])
    assert [g.pages for g in groups] == [[0, 1]] and groups[0].flags


def test_a_header_lost_by_the_first_read_is_found_by_a_sparse_read(monkeypatch):
    """A date typed right above FOR IMMEDIATE RELEASE: the first read garbles the two into one
    line and drops it, so the page looks headerless and would join the release before it."""
    from extractor import ocr, pipeline

    letterhead = [(300, 100, "NEWS from NATIONAL TECHNICAL INSTITUTE FOR THE DEAF"),
                  (600, 160, "One Lomb Memorial Drive Rochester, New York 14623")]
    body = [(150, 400 + 60 * i, t) for i, t in enumerate(BODY)]
    first = layout_page([*letterhead, (700, 250, "Contact: John Doe"), *body])
    sparse = layout_page([*letterhead, (150, 215, "July 29, 1969"),
                          (150, 250, "FOR IMMEDIATE RELEASE"), (700, 250, "Contact: John Doe"), *body])
    monkeypatch.setattr(ocr, "tesseract_lines", lambda *a, **k: sparse)
    assert not page_signals(first).starts
    lines = pipeline._sparse_header(None, first, "eng", False)
    assert page_signals(lines).starts
    assert [ln.text for ln in lines] == [ln.text for ln in sparse]

    monkeypatch.setattr(ocr, "tesseract_lines", lambda *a, **k: first)  # nothing better found: unchanged
    assert pipeline._sparse_header(None, first, "eng", False) is first
