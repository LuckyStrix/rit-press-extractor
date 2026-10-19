"""The folder pass: pages -> releases, list-page subjects attached, problems flagged."""
from extractor.folder import PageIn, assemble_folder
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


def test_release_with_no_entry_is_flagged():
    out = assemble_folder("f1", [list_page("Nov. 3, 1970 Football schedule"), release_page("a.pdf")])
    r = out.rows[0]
    assert r.subject == "" and r.subject_match == "none" and r.needs_review == "YES"
    assert "no subject found in the list page" in r.review_reasons


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
