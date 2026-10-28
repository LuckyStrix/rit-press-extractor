"""Finding the article from a layout model's blocks (extractor.layout.article_rows / choose_body_start)."""
from extractor.layout import DISAGREE_FLAG, article_rows, choose_body_start
from extractor.models import Line, merge_rows
from extractor.regions import Region

from .test_units import mkline_at

BODY = [
    "Mrs. Carolyn P. Rankin has been named publications editor at Rochester",
    "Institute of Technology, it was announced today by the vice president.",
    "She will serve as editor of the alumni magazine and will be responsible",
    "for various editing and writing assignments for catalogues and brochures.",
]


def page(rows: list[tuple[int, int, str]]) -> list[Line]:
    return merge_rows([mkline_at(t, x, y) for x, y, t in rows])


def block(label: str, rows: list[tuple[int, int, str]], score: float = 0.9) -> Region:
    """A region drawn around these typed rows, as the model draws it: a little larger."""
    lines = [mkline_at(t, x, y) for x, y, t in rows]
    return Region(label, score, (min(ln.box[0] for ln in lines) - 4, min(ln.box[1] for ln in lines) - 4,
                                 max(ln.box[2] for ln in lines) + 4, max(ln.box[3] for ln in lines) + 4))


PAGE_H = 3300
LETTERHEAD = [(400, 40, "NEWS from ROCHESTER INSTITUTE OF TECHNOLOGY")]
ADDRESS = [(700, 100, "One Lomb Memorial Drive Rochester, New York 14623")]
RELEASE = [(160, 260, "FOR IMMEDIATE RELEASE"), (160, 300, "January 20, 1971")]
CONTACT = [(900, 260, "Contact: John C. Moore, Jr."), (960, 300, "(716) 464-2338")]


def release_page(*middle: list[tuple[int, int, str]]):
    """A letterhead, the release and contact blocks, then whatever is in the middle and the
    article: one paragraph, its first line indented."""
    body = [(220 if i == 0 else 160, 500 + 50 * i, t) for i, t in enumerate(BODY)]
    rows = LETTERHEAD + ADDRESS + RELEASE + CONTACT + [r for m in middle for r in m] + body
    regions = [block("header", LETTERHEAD), block("text", ADDRESS), block("text", RELEASE),
               block("text", CONTACT)] + [block("text", m) for m in middle] + [block("text", body)]
    return page(rows), regions


def test_the_article_is_the_first_block_below_the_release_and_contact_blocks():
    lines, regions = release_page()
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn P. Rankin")  # not the letterhead's address line


def test_a_headline_above_the_article_is_passed_over():
    headline = [(400, 400, "COLLEGE SKIERS HEAD FOR DEAF OLYMPICS")]
    lines, regions = release_page(headline)
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")
    start = choose_body_start(lines, regions, PAGE_H)
    assert lines[start.line].words[start.word].text == "Mrs."


def test_a_note_to_the_editors_and_an_aside_are_passed_over():
    note = [(160, 380, "Please include the following announcement in your calendar")]
    aside = [(160, 430, "(this show starts Monday, January 25)")]
    lines, regions = release_page(note, aside)
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")


def test_a_release_typed_all_in_capitals_a_line_to_a_block_keeps_its_first_line():
    caps = [(160, 400 + 60 * i, t) for i, t in enumerate([
        "A PROVOCATIVE ONE-MAN SHOW BY THE REV. THOMAS A. RATERMAN",
        "PRIEST AND A MASTER'S DEGREE CANDIDATE IN ROCHESTER INSTITUTE OF",
    ])]
    lines = page(LETTERHEAD + RELEASE + CONTACT + caps)
    regions = [block("header", LETTERHEAD), block("text", RELEASE), block("text", CONTACT),
               block("text", caps[:1]), block("text", caps[1:])]
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("A PROVOCATIVE")


def test_without_release_or_contact_blocks_the_article_is_the_first_block_of_two_lines_below_the_letterhead():
    body = [(220 if i == 0 else 160, 300 + 50 * i, t) for i, t in enumerate(BODY)]
    lines = page(LETTERHEAD + ADDRESS + body)
    regions = [block("header", LETTERHEAD), block("text", ADDRESS), block("text", body)]
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")


def test_a_note_typed_above_the_release_block_is_not_the_article():
    note = [(160, 160, "EDITORS: Please note our error in omitting the date of this event")]
    body = [(220 if i == 0 else 160, 500 + 50 * i, t) for i, t in enumerate(BODY)]
    lines = page(LETTERHEAD + note + RELEASE + CONTACT + body)
    regions = [block("header", LETTERHEAD), block("text", note), block("text", RELEASE),
               block("text", CONTACT), block("text", body)]
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")


def test_where_the_line_layout_agrees_its_start_is_kept_and_nothing_is_flagged():
    dateline = ["ROCHESTER, N.Y. -- Mrs. Carolyn P. Rankin has been named editor at"] + BODY[1:]
    body = [(160, 500 + 50 * i, t) for i, t in enumerate(dateline)]
    lines = page(LETTERHEAD + RELEASE + CONTACT + body)
    regions = [block("header", LETTERHEAD), block("text", RELEASE), block("text", CONTACT), block("text", body)]
    start = choose_body_start(lines, regions, PAGE_H)
    assert lines[start.line].words[start.word].text == "Mrs."  # after the dateline's dash
    assert start.flags == []


def test_where_the_line_layout_picks_a_later_paragraph_the_model_wins_and_it_is_flagged():
    # The first paragraph is typed flush, the second indented: the line layout takes the second.
    first = [(160, 360 + 50 * i, t) for i, t in enumerate(BODY[:2])]
    second = [(220 if i == 0 else 160, 460 + 50 * i, t) for i, t in enumerate(BODY[2:] + BODY[:2])]
    lines = page(LETTERHEAD + RELEASE + CONTACT + first + second)
    regions = [block("header", LETTERHEAD), block("text", RELEASE), block("text", CONTACT),
               block("text", first), block("text", second)]
    start = choose_body_start(lines, regions, PAGE_H)
    assert lines[start.line].words[start.word].text == "Mrs."
    assert start.flags == [DISAGREE_FLAG]


def test_without_regions_the_line_layout_decides():
    lines, _ = release_page()
    start = choose_body_start(lines, [], PAGE_H)
    assert lines[start.line].words[start.word].text == "Mrs."


def test_a_release_and_contact_block_drawn_as_one_wide_block_is_still_not_the_article():
    # The model can draw the release line, the contact and a note under them as one block.
    head = [(200, 540, "IMMEDIATE RELEASE Contact: Jack M. Tucker"), (200, 590, "October 16, 1969 464-2330"),
            (200, 640, "NOTE: D & C, T-U, Radio please use extract for calendar-of-events.")]
    body = [(220 if i == 0 else 160, 840 + 50 * i, t) for i, t in enumerate(BODY)]
    lines = page(LETTERHEAD + head + body)
    regions = [block("header", LETTERHEAD), block("text", head), block("text", body)]
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")


def test_a_block_drawn_again_in_part_does_not_stop_a_note_being_passed_over():
    note = [(500, 1240, "PLEASE INCLUDE THE FOLLOWING ANNOUNCEMENT IN YOUR CALENDAR SECTION"),
            (890, 1340, "(this show starts Monday, January 25)")]
    body = [(160, 1540 + 50 * i, t) for i, t in enumerate(BODY)]
    lines = page(LETTERHEAD + RELEASE + CONTACT + note + body)
    regions = [block("header", LETTERHEAD), block("text", RELEASE), block("text", CONTACT),
               block("text", note), block("text", note[:1]), block("text", body)]
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")


def test_on_an_all_capitals_release_the_line_layout_can_pass_over_its_heading():
    heading = [(160, 400, "PUBLIC SERVICE ANNOUNCEMENT")]
    caps = [(160, 560 + 70 * i, t) for i, t in enumerate([
        "A PROVOCATIVE ONE-MAN SHOW BY THE REV. THOMAS A. RATERMAN, A CATHOLIC",
        "PRIEST AND A MASTER'S DEGREE CANDIDATE IN ROCHESTER INSTITUTE OF",
        "TECHNOLOGY'S SCHOOL OF ART AND DESIGN, WILL RUN FROM JANUARY 8-22 AT",
        "RIT'S BEVIER GALLERY. INCLUDED IN THE SHOW ARE PAINTING, PRINTMAKING,",
    ])]
    lines = page(LETTERHEAD + RELEASE + CONTACT + heading + caps)
    regions = [block("header", LETTERHEAD), block("text", RELEASE), block("text", CONTACT), block("text", heading)]
    regions += [block("text", [row]) for row in caps]
    start = choose_body_start(lines, regions, PAGE_H)
    assert lines[start.line].words[start.word].text == "A"
    assert DISAGREE_FLAG not in start.flags


def test_a_paragraph_that_mentions_a_telephone_is_not_taken_for_the_contact_block():
    second = ["Cohen is a second year business administration student at the Institute.",
              "For his cooperative work assignment, he will serve as a telephone adjustor",
              "in the installment loan department of the bank."]
    body = [(220 if i == 0 else 160, 500 + 50 * i, t) for i, t in enumerate(BODY)]
    more = [(220 if i == 0 else 160, 750 + 50 * i, t) for i, t in enumerate(second)]
    lines = page(LETTERHEAD + RELEASE + CONTACT + body + more)
    regions = [block("header", LETTERHEAD), block("text", RELEASE), block("text", CONTACT),
               block("text", body), block("text", more)]
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")


def test_a_title_case_headline_is_passed_over():
    headline = [(400, 400, "Library Exhibit Shows Rare Books")]
    lines, regions = release_page(headline)
    assert article_rows(lines, regions, PAGE_H)[0][2].text.startswith("Mrs. Carolyn")
