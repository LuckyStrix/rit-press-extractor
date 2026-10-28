"""The folder pass: pages -> releases, list-page subjects attached, problems flagged."""
from extractor.folder import PageIn, assemble_folder
from extractor.models import Word
from extractor.pages import PageSignals
from extractor.pipeline import PageResult, Row

from .test_units import layout_page


def row(file, page=1, date="1970-11-02", verified="YES", reasons="") -> Row:
    return Row(file, page, "", date, "", "Day-long public symposium", verified, verified, "95", "95", "en",
               "YES" if reasons else "no", reasons)


def release_page(file, page=1, date="1970-11-02", slug="", opening="", **signals) -> PageIn:
    sig = PageSignals(**{"starts": True, **signals})
    return PageIn(file, page, "", PageResult(row(file, page, date), sig, slug, opening))


def cont_page(file, page=2) -> PageIn:
    return PageIn(file, page, "", PageResult(row(file, page, ""), PageSignals(cont=True)))


def list_page(*rows: str) -> PageIn:
    lines = layout_page([(100, 100 + 60 * i, t) for i, t in enumerate(
        ["NEWS RELEASES SENT OUT", "MONTH . November", "Date Subject Additional Info.", *rows])])
    return PageIn("list1.pdf", 1, "", PageResult(None, PageSignals(), list_lines=lines))


def test_folder_without_a_list_page_leaves_subject_columns_blank():
    out = assemble_folder("f1", [release_page("a.pdf"), release_page("b.pdf", date="1970-11-03")])
    assert [r.file for r in out.rows] == ["a.pdf", "b.pdf"]
    assert all(r.subject == "" and r.subject_match == "" and r.folder == "f1" for r in out.rows)
    assert all(r.needs_review == "no" for r in out.rows)


def test_continuation_pages_fold_into_their_release():
    out = assemble_folder("f1", [release_page("a.pdf", more=True), cont_page("a.pdf", 2), release_page("b.pdf")])
    assert [(r.file, r.page, r.page_count, r.pages) for r in out.rows] == [
        ("a.pdf", 1, 2, "a.pdf p1, a.pdf p2"), ("b.pdf", 1, 1, "b.pdf p1")]
    assert out.consumed == {("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 1)}


def test_weak_join_is_flagged_on_the_release_row():
    headerless = PageIn("a.pdf", 2, "", PageResult(row("a.pdf", 2, ""), PageSignals()))
    out = assemble_folder("f1", [release_page("a.pdf"), headerless])
    assert len(out.rows) == 1 and out.rows[0].needs_review == "YES"
    assert "continuation" in out.rows[0].review_reasons


def test_subjects_attach_by_date_and_text_and_verify():
    pages = [
        list_page("Nov. 2, 1970 TVR Transportation", "Nov. 2, 1970 Susan Wolf - Co-op",
                  "Nov. 3, 1970 Football schedule"),
        release_page("a.pdf", slug="TVR", opening="METROPOLITAN TRANSPORTATION symposium"),
        release_page("b.pdf", opening="Susan Wolf will begin a co-op assignment"),
    ]
    out = assemble_folder("f1", pages)
    a, b = out.rows
    assert (a.subject, a.subject_match, a.subject_verified) == ("TVR Transportation", "date+text", "YES")
    assert (b.subject, b.subject_verified) == ("Susan Wolf - Co-op", "YES")
    assert a.needs_review == "no"
    assert [e.subject for e in out.unmatched] == ["Football schedule"]


def test_release_with_no_entry_is_not_flagged_for_it():  # the one entry is a day off and its text unrelated
    out = assemble_folder("f1", [list_page("Nov. 3, 1970 Football schedule"), release_page("a.pdf")])
    r = out.rows[0]
    # No list entry fits, and none is in doubt: nothing for a person to settle. The entry no
    # release took is still listed among the unmatched ones.
    assert r.subject == "" and r.subject_match == "none" and r.subject_verified == "NO"
    assert "no subject found" not in r.review_reasons
    assert [e.subject for e in out.unmatched] == ["Football schedule"]


def test_the_one_entry_left_on_a_release_s_day_is_given_but_flagged():
    out = assemble_folder("f1", [list_page("Nov. 2, 1970 Football schedule"), release_page("a.pdf")])
    r = out.rows[0]
    assert (r.subject, r.subject_match, r.subject_verified) == ("Football schedule", "date", "NO")
    assert "subject matched by date only" in r.review_reasons


def test_ambiguous_group_lists_candidates_instead_of_guessing():
    pages = [list_page("Nov. 2, 1970 Football - Siena", "Nov. 2, 1970 Football - Union"),
             release_page("a.pdf", opening="Football fans will see the finale")]
    r = assemble_folder("f1", pages).rows[0]
    assert r.subject == "" and r.needs_review == "YES"
    assert "Football - Siena" in r.review_reasons and "Football - Union" in r.review_reasons


def test_date_only_match_gives_the_subject_but_is_not_verified():
    pages = [list_page("Nov. 2, 1970 John Ward - Co-op"), release_page("a.pdf", opening="unrelated words only here")]
    r = assemble_folder("f1", pages).rows[0]
    assert r.subject == "John Ward - Co-op" and r.subject_verified == "NO" and r.needs_review == "YES"
    assert "date only" in r.review_reasons


def test_list_pages_make_no_rows_and_are_counted():
    out = assemble_folder("f1", [list_page("Nov. 3, 1970 Football schedule")])
    assert out.rows == [] and out.summary["list_pages"] == 1 and out.summary["entries"] == 1


def test_real_list_page_year_is_filled_from_the_releases():
    # a list whose pages print no year still matches, using the year the releases carry
    pages = [list_page("Nov. 2 TVR Transportation"), release_page("a.pdf", slug="TVR", opening="transportation")]
    assert assemble_folder("f1", pages).rows[0].subject == "TVR Transportation"


def test_failed_pages_stand_alone():
    failed = PageIn("bad.pdf", 1, "", PageResult(row("bad.pdf", 1, "", "NO", "processing failed"), PageSignals(starts=True)))
    out = assemble_folder("f1", [release_page("a.pdf", more=True), failed])
    assert [r.file for r in out.rows] == ["a.pdf", "bad.pdf"]


def test_shared_subject_uses_each_releases_own_first_words():
    pages = [list_page("Nov. 2, 1970 NTID Drama Club - Jorjan Neri", "Nov. 2, 1970 Susan Wolf - Co-op"),
             release_page("a.pdf", opening="Jorjan Neri took part in an NTID Drama Club production"),
             release_page("b.pdf", opening="Charles Ritenour took part in an NTID Drama Club production")]
    out = assemble_folder("f1", pages)
    for r in out.rows:
        assert (r.subject, r.subject_match, r.subject_verified) == ("Day-long public symposium", "shared", "YES")
        assert r.needs_review == "no"
    assert [e.subject for e in out.unmatched] == ["Susan Wolf - Co-op"]


def test_a_later_pages_slug_line_helps_find_the_subject():
    # The first page never says "ASEE"; its second page is headed "RIT/ASEE Conference".
    later = PageIn("a.pdf", 2, "", PageResult(row("a.pdf", 2, ""), PageSignals(cont=True, tag={"asee", "conference"})))
    pages = [list_page("Nov. 2, 1970 ASEE conference", "Nov. 2, 1970 Women's Club Fall luncheon"),
             release_page("a.pdf", opening="Some of the top engineering muscle in the country will meet", more=True),
             later,
             release_page("b.pdf", opening="Annual fall luncheon of the Women's Club will be held")]
    a, b = assemble_folder("f1", pages).rows
    assert (a.subject, a.subject_match) == ("ASEE conference", "date+text")
    assert b.subject == "Women's Club Fall luncheon"


def _weak(page: PageIn, word: str, conf: float = 60.0) -> PageIn:
    """The list page with one word read unsurely."""
    for ln in page.result.list_lines:
        ln.words = [Word(w.text, conf, w.box) if w.text == word else w for w in ln.words]
    return page


def test_a_subject_word_read_unsurely_but_spelled_the_same_in_the_release_is_verified():
    out = assemble_folder("f1", [_weak(list_page("Nov. 2, 1970 Rankin named editor"), "Rankin"),
                                 release_page("a.pdf", opening="Mrs. Carolyn Rankin has been named editor")])
    r = out.rows[0]
    assert (r.subject, r.subject_verified) == ("Rankin named editor", "YES")
    assert "low confidence" not in r.review_reasons


def test_a_subject_word_read_unsurely_and_not_in_the_release_is_flagged():
    out = assemble_folder("f1", [_weak(list_page("Nov. 2, 1970 Rankin named editor"), "editor"),
                                 release_page("a.pdf", opening="Mrs. Carolyn Rankin has been named to the post")])
    r = out.rows[0]
    assert r.subject_verified == "NO"
    assert "subject may be misread ('editor')" in r.review_reasons


def test_a_weak_subject_word_joined_by_a_dash_is_found_part_by_part():
    out = assemble_folder("f1", [_weak(list_page("Nov. 2, 1970 Special retirement reception-Ellingson"),
                                       "reception-Ellingson"),
                                 release_page("a.pdf", opening="A special retirement reception honoring Mark Ellingson")])
    assert out.rows[0].subject_verified == "YES"


def _second_read(page: PageIn, misread: dict[str, str]) -> PageIn:
    """The list page as a second engine read it: the same, but for the words in misread."""
    from extractor.listpage import confirm_words
    from extractor.models import Line

    lines = page.result.list_lines
    other = [Line([Word(misread.get(w.text, w.text), 90, w.box) for w in ln.words]) for ln in lines]
    confirm_words(lines, [other])
    return page


def test_a_subject_word_another_engine_reads_differently_is_flagged_though_tesseract_was_sure():
    page = _second_read(list_page("Nov. 2, 1970 Professor promoted to Dean, College of Businless"),
                        {"Businless": "Business"})
    out = assemble_folder("f1", [page, release_page("a.pdf", opening="Professor promoted to Dean of the college")])
    r = out.rows[0]
    assert r.subject_verified == "NO" and "subject may be misread ('Businless')" in r.review_reasons


def test_a_subject_another_engine_reads_the_same_is_verified():
    page = _second_read(list_page("Nov. 2, 1970 Professor promoted to Dean, College of Business"), {})
    out = assemble_folder("f1", [page, release_page("a.pdf", opening="Professor promoted to Dean of the college")])
    assert out.rows[0].subject_verified == "YES"


def test_a_word_the_release_spells_the_same_needs_no_second_engine():
    page = _second_read(list_page("Nov. 2, 1970 Harold Kentner retires"), {"Kentner": "Kantner"})
    out = assemble_folder("f1", [page, release_page("a.pdf", opening="Harold M. Kentner of 68 Beach Avenue retires")])
    assert out.rows[0].subject_verified == "YES"
