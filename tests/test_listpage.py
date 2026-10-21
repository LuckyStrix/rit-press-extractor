"""List pages ("News releases sent out"): dated subject lines for the releases in a folder.

The garbled dates below are the kinds of misreads seen on real typed lists; names are invented.
"""
import datetime as dt

from extractor.listpage import day_column, is_list_page, parse_list_pages, with_days
from extractor.models import Word

from .test_units import layout_page, mkpage

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
