"""List pages ("News releases sent out"): dated subject lines for the releases in a folder.

The garbled dates below are the kinds of misreads seen on real typed lists; names are invented.
"""
import datetime as dt

from extractor.listpage import (bare_day_column, day_column, days_in_order, has_month_line, is_list_page,
                                missing_day_cells, parse_list_pages, vote_days, with_days, with_month_line)
from extractor.models import Line, Word

from .test_units import layout_page, mkline_at, mkpage

HEAD = ["NEWS RELEASES SENT OUT", "MONTH .. November... cee", "Date Subject Additional Info."]


def page(*rows: str, head: list[str] = HEAD):
    return layout_page([(100, 100 + 60 * i, t) for i, t in enumerate([*head, *rows])])


PAGE1 = page(
    "Nov. 2, 1970 TVR Transportation",
    "Nov. 2,. 1970 John Ward Co-op",
    "Nov. 3, 1976 James Baker - Co-op",
    "NOv.. . 3, 31970 Karen Gates - Co-op",
    "Now. 4, 2970 Jank SlutzkyNTID",
    "Nov. SS, 1970 Football schedule",
    "Nov. 6, 1970 }|Robert Panara NTID",
    "Nov 9) 1970 Rick Huff",
    "Nove\"9, 1970 Chris Roth - ROTC",
)
PAGE2 = page(
    "Nov. 10 Kenneth Nash NTID",
    "Robert Peters - Co-op",
    "Nov. 11 Joe Widay Athlete of the Week",
    "Nov. 13 Dr. Paul Bernstein - Executive Board of the]Assoc. for Gen. Studies",
    "Nov/ 22 NTID",
    head=[HEAD[0], "MONTH . November", HEAD[2]],
)
PAGE3 = page(
    "Nov. 25 Bruce Davidson - East 100th Street",
    "Mov, 25 Barry Berman - Co-op",
    "Nov. 30 Football season",
    head=[HEAD[0], "MONTH ocnawsdoerer", HEAD[2]],
)


def test_list_page_is_recognised_by_its_title():
    assert is_list_page(PAGE1) and is_list_page(PAGE3)
    release = mkpage("NEWS from ROCHESTER INSTITUTE OF TECHNOLOGY", "FOR IMMEDIATE RELEASE", "November 2, 1970")
    assert not is_list_page(release)
    letterhead = mkpage("ROCHESTER INSTITUTE OF TECHNOLOGY", "Office of Public Relations",
                        "Rochester, New York 14623 NEWS RELEASE", "IMMEDIATE RELEASE Contact: Jack M. Tucker",
                        "September 11, 1969")
    assert not is_list_page(letterhead)


def test_a_list_continued_on_a_page_without_title_or_headings_is_a_list():
    # box2folder3 p2: the rows carry on from the page before, each starting with its day
    rows = [(510, 330, "11th annual management seminar"), (1700, 330, "Code 1-1,2,3,4"),
            (510, 400, "Fall semester enrollment"), (1700, 450, "Code3-1,2,3"),
            (375, 520, "23 Alumni, faculty & staff golf tournament"), (375, 590, "25 Alumni club of Tricity area"),
            (375, 660, "25 Charles McColgan, Cadet Lieut. Col ROTC"), (1700, 710, "pictures sent."),
            (350, 780, "25 Special retirement reception"), (350, 850, "26 Architects"),
            (355, 920, "27 Certificates - Community Awareness"), (355, 990, "29 Raymond DaBoll & Warren Rhodes"),
            (370, 1060, "30 Westvaco story"), (485, 1130, "Laverne, Senator addressing NAADURH")]
    assert is_list_page(layout_page(rows))
    scores = [(300, 300 + 70 * i, f"{n} {name} scored") for i, (n, name) in
              enumerate([(12, "Smith"), (3, "Jones"), (27, "Brown"), (8, "Green"), (19, "White"), (4, "Black")])]
    assert not is_list_page(layout_page(scores))  # numbered rows out of order are not days


def test_list_page_is_recognised_without_a_readable_title():
    rows = [f"Nov. {d} Person {d} - Co-op" for d in range(2, 9)]
    assert is_list_page(page(*rows, head=["N3WS RELE SSES SINT", "M0NTH ....", "Dxte Sxbject"]))


def test_entries_across_pages_with_repairs():
    result = parse_list_pages([PAGE1, PAGE2, PAGE3])
    got = [(e.date.isoformat(), e.subject) for e in result.entries]
    assert got == [
        ("1970-11-02", "TVR Transportation"),
        ("1970-11-02", "John Ward Co-op"),
        ("1970-11-03", "James Baker - Co-op"),
        ("1970-11-03", "Karen Gates - Co-op"),
        ("1970-11-04", "Jank SlutzkyNTID"),
        ("1970-11-04", "Football schedule"),  # day unreadable: same day as the entry above
        ("1970-11-06", "Robert Panara NTID"),
        ("1970-11-09", "Rick Huff"),
        ("1970-11-09", "Chris Roth - ROTC"),
        ("1970-11-10", "Kenneth Nash NTID"),
        ("1970-11-10", "Robert Peters - Co-op"),  # no date printed: same day as the entry above
        ("1970-11-11", "Joe Widay Athlete of the Week"),
        ("1970-11-13", "Dr. Paul Bernstein - Executive Board of the Assoc. for Gen. Studies"),
        ("1970-11-22", "NTID"),
        ("1970-11-25", "Bruce Davidson - East 100th Street"),
        ("1970-11-25", "Barry Berman - Co-op"),
        ("1970-11-30", "Football season"),
    ]
    assert (result.year, result.month) == (1970, 11)


def test_clean_entries_have_no_flags_and_repairs_are_flagged():
    result = parse_list_pages([PAGE1, PAGE2, PAGE3])
    by_subject = {e.subject: e for e in result.entries}
    assert by_subject["John Ward Co-op"].flags == []
    assert by_subject["Kenneth Nash NTID"].flags == []  # the year is simply not printed after page 1
    for subject in ("James Baker - Co-op", "Karen Gates - Co-op", "Jank SlutzkyNTID", "Football schedule",
                    "Robert Peters - Co-op", "Barry Berman - Co-op"):
        assert by_subject[subject].flags, subject
    assert any("no date" in f for f in by_subject["Robert Peters - Co-op"].flags)


def test_out_of_order_date_is_flagged_not_corrected():
    result = parse_list_pages([page("Nov. 9, 1970 A Person - Co-op", "Nov. 8, 1970 B Person - Co-op")])
    assert [e.date for e in result.entries] == [dt.date(1970, 11, 9), dt.date(1970, 11, 8)]
    assert any("sequence" in f for f in result.entries[1].flags)
    assert not result.entries[0].flags


def test_year_comes_from_the_caller_when_no_page_prints_it():
    result = parse_list_pages([page("Nov. 10 A Person - Co-op")], default_year=1970)
    assert result.entries[0].date == dt.date(1970, 11, 10)
    assert parse_list_pages([page("Nov. 10 A Person - Co-op")]).entries[0].date is None


def test_header_and_blank_pages_make_no_entries():
    assert parse_list_pages([page()]).entries == []


# A list that prints only the day, in a "Date" column apart from the subject, wraps long
# subjects onto indented lines set closer together than the entries, and adds notes in an
# "Additional Info." column. Laid out like a real July 1969 list (12px characters, 30px lines).
def column_page(*entries: tuple[str, list[str], list[str]]):
    rows = [(400, 100, "NEWS RELEASES SENT OUT"), (180, 160, "MONTH July 1969"),
            (150, 240, "Date"), (420, 240, "Subject"), (800, 240, "Additional Info.")]
    days, y = [], 330
    for day, subject, info in entries:
        if day:
            days.append(Word(day, 96.0, (150, y, 150 + 12 * len(day), y + 30)))
        for k in range(max(len(subject), len(info))):
            if k < len(subject):
                rows.append((260 if k == 0 else 290, y, subject[k]))
            if k < len(info) and info[k]:
                rows.append((800, y, info[k]))
                if k == 0 and info[k].startswith("TU"):
                    rows.append((740, y, "r"))  # a speck of the column rule, read as a letter
            y += 40
        y += 50
    return layout_page(rows), days


COLUMNS = column_page(
    ("", ["Dr. Jane Doe - NTID appointment"], ["TU & D&C - special list"]),
    ("11", ["Mrs. Ann Smith named publications", "editor"], ["", "local media"]),
    ("14", ["Alan Brown RIT school of printing", "appointed to the Cary chair"], ["", "local media", "trade journals"]),
    ("22", ["Joan Black appointed to the art faculty"], ["local media"]),
    ("29", ["Two students head for Belgrade", "in August for", "the World Games for the Deaf"],
     ["", "", "local media and hometowns", "Dr. Green (of course)"]),
)


def test_days_in_their_own_column_are_read_on_their_own():
    lines, days = COLUMNS
    box = day_column(lines)
    assert box is not None and box[2] < 260  # left of the subjects
    assert all(box[0] <= w.box[0] and w.box[2] <= box[2] for w in days)
    assert day_column(PAGE1) is None  # dates typed at the start of each row


def test_day_column_rows_wrapped_subjects_and_additional_info():
    lines, days = COLUMNS
    result = parse_list_pages([with_days(lines, days)])
    got = [(e.date.isoformat() if e.date else None, e.subject) for e in result.entries]
    assert got == [
        (None, "Dr. Jane Doe - NTID appointment"),  # its day was not read
        ("1969-07-11", "Mrs. Ann Smith named publications editor"),
        ("1969-07-14", "Alan Brown RIT school of printing appointed to the Cary chair"),
        ("1969-07-22", "Joan Black appointed to the art faculty"),
        ("1969-07-29", "Two students head for Belgrade in August for the World Games for the Deaf"),
    ]
    assert (result.year, result.month) == (1969, 7)
    assert all(not e.flags for e in result.entries[1:])


def test_evenly_spaced_undated_rows_stay_entries_of_their_own():
    # On a single-spaced list an undated row is another release on the same day, not a wrap.
    result = parse_list_pages([PAGE2])
    assert "Robert Peters - Co-op" in [e.subject for e in result.entries]


# An August 1969 list where Tesseract dropped the "MONTH" line and the "Date" heading, so
# nothing on the page said where the days were or which month they belong to.
def _drop(lines, *texts):
    return [ln for ln in lines if ln.text not in texts]


def test_days_are_found_without_a_date_heading_and_the_month_comes_from_the_releases():
    lines, days = COLUMNS
    lines = [ln for ln in _drop(lines, "MONTH July 1969") if ln.text != "Date Subject Additional Info."]
    lines.insert(1, mkline_at("Subject", 420, 240))
    lines[1].words.append(mkline_at("Additional Info.", 800, 240).words[0])
    lines[1].words.append(mkline_at("Info.", 920, 240).words[0])
    assert not has_month_line(lines)
    box = day_column(lines)
    assert box is not None and box[2] < 260
    # The page read kept one row's day in front of it (Tesseract 5.5): the column still reaches the days.
    glued = [Line(list(ln.words)) for ln in lines]
    row = next(ln for ln in glued if ln.text.startswith("Joan Black"))
    row.words.insert(0, next(w for w in days if w.text == "22"))
    assert day_column(glued) == box
    result = parse_list_pages([with_days(lines, days)], default_year=1969, default_month=7)
    assert [e.date.isoformat() for e in result.entries[1:]] == ["1969-07-11", "1969-07-14", "1969-07-22", "1969-07-29"]


def test_a_month_line_read_again_in_pieces_is_put_back():
    lines, _ = COLUMNS
    lines = _drop(lines, "MONTH July 1969")
    back = with_month_line(lines, [mkline_at("NEWS RELEASES SENT OUT", 400, 100), mkline_at("MonTH Aug ust 1969", 180, 160)])
    assert has_month_line(back)
    result = parse_list_pages([back])
    assert (result.year, result.month) == (1969, 8)


def test_a_punch_hole_read_as_a_digit_is_not_taken_for_a_day():
    lines, days = COLUMNS
    hole = Word("8", 60.0, (10, 690, 110, 780))  # far taller than the typed days, at the page edge
    result = parse_list_pages([with_days(lines, [hole, *days])])
    assert result.entries[3].subject == "Joan Black appointed to the art faculty"
    assert result.entries[3].date.isoformat() == "1969-07-22"


def test_a_day_goes_to_the_row_it_overlaps_most_not_a_speck_beside_it():
    lines = [mkline_at("Subject Additional", 420, 240), mkline_at("a -", 700, 330),
             mkline_at("National Association of Lithographers", 260, 336)]
    lines[1].words = [Word("a", 50.0, (700, 330, 712, 342)), Word("-", 50.0, (720, 330, 730, 342))]
    out = with_days(lines, [Word("20", 96.0, (150, 338, 174, 366))])
    assert out[2].words[0].text == "20" and out[1].words[0].text == "a"


def test_an_entry_wrapped_before_any_spacing_is_measured_is_still_joined():
    lines, days = column_page(
        ("6", ["Alumni scholarships totaling", "$5,000 announced by", "the Alumni Association"], ["local"]),
        ("7", ["Gannett dedication"], ["local"]),
        ("8", ["Eight wrestling coaches"], ["local"]),
    )
    result = parse_list_pages([with_days(lines, days)])
    assert [e.subject for e in result.entries] == [
        "Alumni scholarships totaling $5,000 announced by the Alumni Association", "Gannett dedication",
        "Eight wrestling coaches"]


def test_rows_the_column_read_missed_are_read_again_one_by_one():
    lines, days = COLUMNS
    box = day_column(lines)
    cells = missing_day_cells(with_days(lines, days), box)
    tops = {c[1] for c in cells}
    assert 330 in tops  # Dr. Jane Doe's day was not read
    assert all(c[0] == box[0] and c[2] == box[2] for c in cells)
    dated = {w.box[1] for w in days}
    assert not tops & dated


# A September 1969 list whose second page carries on with no title or headings (box2folder3).
SEPT_HEAD = [(400, 100, "NEWS RELEASES SENT OUT"), (180, 160, "MONTH September 1969"),
             (150, 240, "Date"), (420, 240, "Subject"), (900, 240, "Additional Info.")]


def test_notes_beside_a_subject_that_runs_up_to_their_column_are_left_out():
    lines = layout_page([*SEPT_HEAD,
                         (150, 330, "9"), (260, 330, "Annual Women's Tea"), (800, 330, "Code 1-17"),
                         (150, 400, "10"), (260, 400, "Gulf Oil grant"), (800, 400, "Some picture sent"),
                         # this subject ends 48px (under two line heights) before its notes
                         (150, 470, "10"), (260, 470, "Apprentice program: Lithographers & photo"),
                         (800, 470, "Code 2, Horton"),
                         (150, 540, "11"), (260, 540, "Ilex Optical Co. donation"), (800, 540, "Code 1")])
    subjects = [e.subject for e in parse_list_pages([lines]).entries]
    assert subjects == ["Annual Women's Tea", "Gulf Oil grant", "Apprentice program: Lithographers & photo",
                        "Ilex Optical Co. donation"]


def test_a_continued_page_reads_its_days_and_notes_like_the_page_before():
    first = layout_page([*SEPT_HEAD, (150, 330, "19"), (260, 330, "Transportation Seminar"), (800, 330, "Code 2")])
    rows = [(260, 100, "11th annual management seminar"), (800, 100, "Code 1-1,2,3,4"),  # its day was dropped
            (150, 170, "23"), (260, 170, "Alumni golf tournament"), (800, 170, "Code 5"),
            (150, 240, "25"), (260, 240, "Alumni club of Tricity area"), (800, 240, "Tri-city area"),
            (150, 310, "26"), (260, 310, "Architects"), (800, 310, "Canadian publishers"),
            (150, 380, "29"), (210, 380, "Raymond DaBoll"),  # a tab, not two line heights, after the day
            (150, 450, "30"), (260, 450, "Westvaco story")]
    second = layout_page(rows)
    box = day_column(second)
    assert box is not None and 174 <= box[2] < 210  # right of the days, left of every subject
    dropped = Word("22", 96.0, (150, 100, 174, 130))
    result = parse_list_pages([first, with_days(second, [dropped])])
    got = [(e.date.isoformat(), e.subject) for e in result.entries]
    assert got == [("1969-09-19", "Transportation Seminar"), ("1969-09-22", "11th annual management seminar"),
                   ("1969-09-23", "Alumni golf tournament"), ("1969-09-25", "Alumni club of Tricity area"),
                   ("1969-09-26", "Architects"), ("1969-09-29", "Raymond DaBoll"), ("1969-09-30", "Westvaco story")]


def test_a_day_the_column_read_was_unsure_of_is_read_again_on_its_own(monkeypatch):
    from extractor import ocr, pipeline

    column = (0, 100, 300, 900)
    sure, unsure = Word("18", 96.0, (150, 200, 174, 230)), Word("9", 0.0, (160, 300, 174, 330))  # it says "19"
    asked = []
    monkeypatch.setattr(ocr, "tesseract_digits", lambda img, box, cell=False: asked.append(box) or [
        Word("19", 97.0, (150, 300, 174, 330))])
    assert pipeline._reread_day(None, column, sure) is sure and not asked
    assert pipeline._reread_day(None, column, unsure).text == "19"
    assert asked == [(0, 290, 300, 340)]  # its own cell, a little taller than the digit
    monkeypatch.setattr(ocr, "tesseract_digits", lambda img, box, cell=False: [Word("85", 69.0, box)])
    assert pipeline._reread_day(None, column, unsure) is unsure  # an unsure re-read changes nothing


def test_a_list_line_read_with_unsure_words_is_read_again_on_its_own(monkeypatch):
    from PIL import Image

    from extractor import ocr, pipeline
    page = Image.new("L", (1000, 1000), 255)
    sure = Line([Word("Gulf", 95.0, (100, 300, 160, 330)), Word("Oil", 93.0, (170, 300, 210, 330))])
    garbled = Line([Word("Aperentic=", 30.0, (100, 400, 260, 430)), Word("si", 20.0, (270, 400, 300, 430))])
    clean = Line([Word("Apprentice", 91.0, (100, 400, 260, 430)), Word("program", 90.0, (270, 400, 380, 430))])
    asked = []
    monkeypatch.setattr(ocr, "tesseract_line", lambda img, box, lang, best=False: asked.append(box) or clean)
    assert pipeline._reread_line(page, sure, "eng", False) is sure and not asked
    assert pipeline._reread_line(page, garbled, "eng", False) is clean
    assert asked == [(90, 390, 310, 440)]  # the line, with a margin
    monkeypatch.setattr(ocr, "tesseract_line", lambda img, box, lang, best=False: Line(
        [Word("Aperentlc", 30.0, box)]))
    assert pipeline._reread_line(page, garbled, "eng", False) is garbled  # not clearly surer: kept


# An October 1969 list typed unevenly: days a little above their rows, some typed over or off to
# the left, and a punch hole and a struck-out day in the "Date" column.
def _day(text, y, x=150, conf=96.0):
    return Word(text, conf, (x, y, x + 12 * len(text), y + 30))


def test_several_readings_of_the_date_column_vote():
    # Three "15"s stacked close: one reading gets them all, the others garble two of them.
    good = [_day("14", 300), _day("15", 345), _day("15", 390), _day("15", 435), _day("16", 480)]
    bad = [_day("14", 300), _day("15", 345), _day("5", 390), _day("45", 435), _day("16", 480)]
    worse = [_day("14", 300), _day("5", 345, conf=0.0), _day("5", 390), _day("25", 435), _day("16", 480),
             _day("2514", 520), _day("7", 600)]  # a struck-out day, and a speck only one reading saw
    voted = vote_days([bad, good, worse, good])
    assert [w.text for w in voted] == ["14", "15", "15", "15", "16"]


def test_days_typed_above_their_rows_go_to_the_right_rows():
    lines = layout_page([(150, 240, "Date"), (420, 240, "Subject"), (1200, 240, "Additional Info."),
                         (420, 300, "Jacques Van Droogenbroeck visitor"), (420, 360, "Paul Kazmierski appointment"),
                         (420, 420, "Hospital Management seminar"), (1200, 430, "Code 1, 2 info")])
    days = [_day("9", 288), _day("10", 340), _day("10", 408)]  # a dozen pixels above each row
    out = with_days(lines, days, (0, 270, 380, 460))
    assert [ln.text for ln in out[1:4]] == ["9 Jacques Van Droogenbroeck visitor", "10 Paul Kazmierski appointment",
                                            "10 Hospital Management seminar Code 1, 2 info"]


def test_a_garbled_day_in_the_date_column_keeps_the_row_its_own_entry():
    lines = layout_page([(180, 160, "MONTH October 1969"), (150, 240, "Date"), (420, 240, "Subject"),
                         (1200, 240, "Additional Info."), (420, 300, "Sports different subjects"),
                         (150, 340, "#514"), (420, 340, "Photographic symposium"),
                         (150, 380, "PAE"), (420, 380, "PSA Student Film award")])
    days = [_day("10", 300), _day("21", 380, x=200)]
    result = parse_list_pages([with_days(lines, days, (0, 270, 380, 420))], 1969)
    assert [(e.subject, e.date.day) for e in result.entries] == [
        ("Sports different subjects", 10), ("Photographic symposium", 10), ("PSA Student Film award", 21)]
    assert result.entries[1].flags == ["day read as '514'; assumed same day as the entry above"]


def test_a_line_set_well_in_is_a_wrapped_subject_and_more_is_not_an_entry():
    # "prospects" sits as far below its line as the next entry does; only being set in marks it.
    lines = layout_page([(180, 160, "MONTH October 1969"), (150, 240, "Date"), (420, 240, "Subject"),
                         (1200, 240, "Additional Info."), (420, 300, "Nasrin Keyhan -- American Craftsman student"),
                         (420, 360, "Dr. Martin Gainsbrugh speech on economic"), (700, 420, "prospects"),
                         (420, 480, "Renovation of Palmyra"), (600, 560, "more")])
    days = [_day("20", 300), _day("21", 360), _day("22", 480)]
    result = parse_list_pages([with_days(lines, days, (0, 270, 380, 600))], 1969)
    assert [e.subject for e in result.entries] == [
        "Nasrin Keyhan -- American Craftsman student", "Dr. Martin Gainsbrugh speech on economic prospects",
        "Renovation of Palmyra"]


def test_a_row_with_a_garbled_day_left_of_the_heading_does_not_hide_the_date_column():
    lines, days = COLUMNS
    garbled = [Line(list(ln.words)) for ln in lines]
    row = next(ln for ln in garbled if ln.text.startswith("Joan Black"))
    row.words.insert(0, Word("#514", 0.0, (100, row.box[1], 148, row.box[3])))
    assert day_column(garbled) is not None


def test_a_continued_list_whose_days_the_page_read_dropped_is_found_by_reading_beside_its_rows():
    # No title, no headings, no days in the page read: only subjects, set in from the margin.
    subjects = ["Student Chapter -- Society of Photographic Scientists", "Syracuse Club, Printing House Craftsmen",
                "Indonesian Visitors", "Engineering Dept. accreditation by ECPD", "Robert R. Sponholz address",
                "Scholarships awarded -- Rochester area"]
    lines = layout_page([(660, 270 + 100 * i, s) for i, s in enumerate(subjects)])
    box = bare_day_column(lines)
    assert box is not None and box[2] < 660 and box[1] < 270
    days = [_day(d, 270 + 100 * i, x=420) for i, d in enumerate(["24", "24", "25", "28", "29", "29"])]
    assert days_in_order(days, len(lines))
    assert not days_in_order(days[:2], len(lines))  # a stray number or two beside the rows is not a list
    # A release page's body starts near the margin, so there is no strip for days beside it.
    assert bare_day_column(layout_page([(150, 270 + 50 * i, "and the college will open a new laboratory")
                                        for i in range(8)])) is None


def test_without_the_date_heading_a_garbled_row_does_not_cut_off_the_days():
    # Tesseract 5.5 read the heading as "Subject Additional Info." and kept a struck-out day,
    # "#514", in front of one row; the days themselves stand at x 390-470.
    rows = [(1007, 657, "Subject Additional Info.")]
    rows += [(660, 740 + 60 * i, f"Release subject number {i}") for i in range(12)]
    rows += [(410, 1460, "#514 Photographic symposium"), (610, 1520, "Nancy Belfer exhibit")]
    box = day_column(layout_page(rows))
    assert box is not None and 470 < box[2] < 610


def test_only_the_unsure_words_of_a_list_line_are_read_again_cropped_to_one_line(monkeypatch):
    # Tesseract 5.5 merged a typed subject with the note written under it into one tall line of
    # nonsense; the notes on the right were read fine and must stay as they are.
    from PIL import Image

    from extractor import ocr, pipeline
    page = Image.new("L", (2600, 2000), 255)
    garbled = [Word("Aperentic=", 0.0, (649, 1364, 900, 1434)), Word("Times", 21.0, (1113, 1362, 1250, 1436))]
    notes = [Word("code", 74.0, (1771, 1390, 1880, 1423)), Word("2,", 97.0, (1905, 1390, 1950, 1429)),
             Word("Horton", 96.0, (1978, 1392, 2150, 1429))]
    clean = Line([Word("Apprentice", 70.0, (649, 1362, 900, 1400)), Word("program", 72.0, (920, 1362, 1100, 1400))])

    def read(img, box, lang, best=False):
        if box[2] > 1700:  # the whole line: no better
            return Line([Word("Aperentics", 40.0, box)])
        return clean if box[3] - box[1] <= 1.3 * 37 + 2 * (37 // 3) else Line([Word("Litho", 28.0, box)])

    monkeypatch.setattr(ocr, "tesseract_line", read)
    out = pipeline._reread_line(page, Line(garbled + notes), "eng", False)
    assert out.text == "Apprentice program code 2, Horton"


def test_a_missed_day_is_read_in_a_few_crops_and_the_surest_kept(monkeypatch):
    from PIL import Image

    from extractor import ocr, pipeline
    page = Image.new("L", (1000, 2000), 255)
    days = [_day("10", 1505, x=421), _day("15", 1689, x=426)]

    def read(img, box, cell=False):  # the exact cell cuts the top off "11"; a taller one reads it
        return [Word("11", 96.0, (420, 1560, 460, 1600))] if box[1] < 1555 else [Word("1", 0.0, (440, 1560, 460, 1600))]

    monkeypatch.setattr(ocr, "tesseract_digits", read)
    assert [w.text for w in pipeline._read_day_cell(page, (0, 1555, 548, 1612), days)] == ["11"]


def test_a_day_read_again_from_the_next_rows_cell_is_the_same_day():
    from extractor.pipeline import _same_spot
    eleven, one = Word("11", 96.0, (420, 1560, 460, 1600)), Word("1", 0.0, (440, 1575, 460, 1600))
    assert _same_spot(eleven, one) and not _same_spot(eleven, Word("15", 90.0, (420, 1690, 460, 1730)))


def test_a_missed_days_cell_does_not_take_the_day_of_the_row_above(monkeypatch):
    from PIL import Image

    from extractor import ocr, pipeline
    page = Image.new("L", (1000, 3200), 255)
    above = _day("23", 2798, x=403)
    smear = Word("2", 0.0, (81, 2853, 440, 2926))  # a punch hole and this row's day read as one
    days = [_day("22", 2567, x=408), above, smear]

    def read(img, box, cell=False):  # a crop reaching up reads the row above's "23" more surely
        return [Word("23", 97.0, above.box)] if box[1] < 2856 else [Word("24", 83.0, (394, 2850, 440, 2884))]

    monkeypatch.setattr(ocr, "tesseract_digits", read)
    assert [w.text for w in pipeline._read_day_cell(page, (0, 2856, 548, 2912), days)] == ["24"]


def test_an_undated_row_under_a_short_entry_on_a_single_spaced_list_is_its_own_entry():
    """Box 2 folder 5: "Jan. 7" was not read beside Ritsko's row, typed a little closer than usual.
    "Thms Kolb Co-op" is far too short to have wrapped, so the row below is another entry."""
    rows = ["Jan. 7 Robert Backofen NTID-Cross Country", "Jan. 7 Thms Kolb Co-op",
            "Alan J. Ritsko - Policy Committee", "Jan. 8 Sutherland resignation",
            "Jan. 8 American Society for Quality Control", "Jan. 8 Am. Assoc. of Univ. Book Show"]
    xs, ys = [100, 100, 184, 100, 100, 100], [280, 320, 358, 400, 440, 480]  # single-spaced; the subjects start at 184
    head = [(100, 100, HEAD[0]), (100, 160, "MONTH . January 1, 1971 thru January 31, 1971"),
            (100, 220, "Date"), (184, 220, "Subject"), (1000, 220, "Additional Info.")]
    lines = layout_page(head + list(zip(xs, ys, rows)))
    subjects = [e.subject for e in parse_list_pages([lines], 1971).entries]
    assert "Thms Kolb Co-op" in subjects and "Alan J. Ritsko - Policy Committee" in subjects


def test_stray_marks_at_either_end_of_a_subject_are_dropped():
    from extractor.listpage import _tidy

    assert _tidy("° Unique") == "Unique" and _tidy("Davidson NTID -") == "Davidson NTID"
    assert _tidy('"Victory over Poverty" James McCuller') == '"Victory over Poverty" James McCuller'
    assert _tidy("Prof. Smith named Jr.") == "Prof. Smith named Jr."


def test_a_line_left_unfinished_goes_on_below_though_spaced_like_an_entry():
    """Box 2 folder 7: "Manage-" ends one line, "ment Seminar." starts the next, spaced nearly as
    far apart as the entries are."""
    head = [(100, 100, HEAD[0]), (100, 160, "MONTH . January 1970"),
            (100, 220, "Date"), (184, 220, "Subject"), (1000, 220, "Additional Info.")]
    rows = [(100, 300, "Jan. 26 Pre-Retirement Planning March 10-11"),
            (100, 370, "Jan. 29 Robert McNeill, speaker (Feb. 2) Manage-"), (184, 433, "ment Seminar."),
            (100, 510, "Jan. 29 Population Explosion"), (100, 580, "Jan. 30 Production for Book Publishing")]
    subjects = [e.subject for e in parse_list_pages([layout_page(head + rows)], 1970).entries]
    assert "Robert McNeill, speaker (Feb. 2) Management Seminar." in subjects
    assert "ment Seminar." not in subjects


def test_a_subject_left_open_is_unfinished():
    from extractor.listpage import is_unfinished

    assert is_unfinished("Cooperative Education conference (Jan.") and is_unfinished("speaker Manage-")
    assert is_unfinished('"Preparing Two-Year College Teachers for')
    assert not is_unfinished("Workshops -- food preparation") and not is_unfinished('"Unique" theme')


def test_a_month_starting_one_wrapped_line_is_not_taken_for_the_page_month():
    """Box 2 folder 10: the header month was unread, and "July 27)" (the end of a wrapped subject,
    "workshop (June 22 - July 27)") was the only line starting with a month."""
    head = [(100, 100, HEAD[0]), (100, 160, "MONTH 5 ee aia ws gees"),
            (100, 220, "Date"), (184, 220, "Subject"), (1000, 220, "Additional Info.")]
    rows = [(100, 300, "16"), (184, 300, "RIT receives Texaco Inc. grant of $1,500"),
            (100, 370, "17"), (184, 370, "European travel-study workshop (June 22 -"), (184, 425, "July 27)"),
            (100, 500, "17"), (184, 500, "Tuition increase in Continuing Education"),
            (100, 570, "20"), (184, 570, "RIT plans Earth Day")]
    result = parse_list_pages([layout_page(head + rows)], 1970, 4)
    days = {e.subject: e.date for e in result.entries}
    assert days["RIT receives Texaco Inc. grant of $1,500"] == dt.date(1970, 4, 16)
    assert days["RIT plans Earth Day"] == dt.date(1970, 4, 20)
