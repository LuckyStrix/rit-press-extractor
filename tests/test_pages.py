"""Grouping scanned pages into releases: a release can run over several pages."""
from extractor.pages import PageSignals, group_pages, has_release_header, page_signals

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
    assert not has_release_header(first)  # the letterhead marks a first page, but there is no date
    lines = pipeline._sparse_header(None, first, "eng", False)
    assert page_signals(lines).starts
    assert [ln.text for ln in lines] == [ln.text for ln in sparse]

    monkeypatch.setattr(ocr, "tesseract_lines", lambda *a, **k: first)  # nothing better found: unchanged
    assert pipeline._sparse_header(None, first, "eng", False) is first


def test_a_letterhead_marks_a_first_page_and_a_lone_number_under_it_is_a_speck():
    memo = sig(["SPORTS NEWS", "ROCHESTER INSTITUTE OF TECHNOLOGY",
                "One Lomb Memorial Drive Rochester, New York 14623", "MEMO TO SPORTS EDITORS", *BODY])
    assert memo.starts and not memo.cont  # undated, but on first-page stationery
    speck = sig(["NEWS from ROCHESTER INSTITUTE OF TECHNOLOGY", "6", "IMMEDIATE RELEASE Contact: Jack M. Tucker",
                 "September 19, 1969", *BODY])
    assert speck.starts and not speck.cont


def test_add_n_marks_a_later_page():
    assert sig(["RIT/Annual Women's Tea", "-~add 1-", *BODY]).cont
    assert sig(["RIT/Fillers", "-- add l -- FALL SPORTS FILLERS", *BODY]).cont


def test_a_later_page_whose_slug_does_not_fit_starts_a_new_release():
    memo = sig(["September 10, 1969", "Memo to editors", "Re: RIT news release dated Sept. 9 concerning the apprentice program"])
    tea = sig(["FOR IMMEDIATE RELEASE", "September 9, 1969", "The annual fall tea for new women faculty members"])
    fillers = sig(["RIT/Fillers", "-- add 1 -- FALL SPORTS FILLERS", *BODY])
    tea2 = sig(["RIT/Annual Women's Tea", "-~add 1-", *BODY])
    groups = group_pages([tea, tea2, memo, fillers])
    assert [g.pages for g in groups] == [[0, 1], [2], [3]]
    assert groups[2].flags and not groups[0].flags


def test_a_misread_slug_after_more_stays_with_its_release():
    first = sig(["FOR IMMEDIATE RELEASE", "September 15, 1969", "Two young Englishmen will lecture this fall", *BODY, "-more-"])
    second = sig(["RIT /FAG ot SL AAotions", "Both bachelors, they are sharing an apartment", *BODY, "-30-"])
    assert second.tag and not second.tag & first.words
    assert [g.pages for g in group_pages([first, second])] == [[0, 1]]
