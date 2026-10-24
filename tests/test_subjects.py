"""Matching list-page subjects to releases: by date first, then by what the release says."""
import datetime as dt

from extractor.listpage import ListEntry
from extractor.subjects import Release, match_subjects

D = dt.date


def entry(day: int, subject: str, flags=None) -> ListEntry:
    return ListEntry(D(1970, 11, day), subject, f"Nov. {day}, 1970", 95.0, 0, day, flags or [])


def release(key, day, slug="", text="", verified=True) -> Release:
    return Release(key, D(1970, 11, day) if day else None, verified, slug, text)


def test_slug_and_text_confirm_a_lone_same_day_match():
    entries = [entry(2, "TVR Transportation"), entry(3, "James Baker - Co-op")]
    res = match_subjects([release("a", 2, "TVR", "A DAY-LONG SYMPOSIUM ON METROPOLITAN TRANSPORTATION")], entries)
    m = res.matches["a"]
    assert (m.entry, m.method, m.confident) == (0, "date+text", True)
    assert res.unmatched_entries == [1]


def test_five_releases_on_one_day_are_sorted_by_their_names():
    names = ["John Ward", "Richard Hill", "Thomas Caiolo", "David Hoppenworth", "Karen Gates"]
    entries = [entry(2, f"{n} - Co-op") for n in names]
    # scanned in a different order than listed, and with OCR noise in two names
    scanned = [("e", "Karen Gates"), ("b", "Richard Hill"), ("d", "David Hoppenwonth"), ("a", "John Ward"),
               ("c", "Thomas Caiolo")]
    releases = [release(k, 2, "Co-op", f"{n}, a student in the college, will begin a co-op assignment") for k, n in scanned]
    res = match_subjects(releases, entries)
    assert {k: res.matches[k].entry for k, _ in scanned} == {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}
    assert all(m.confident and m.method == "date+text" for m in res.matches.values())


def test_a_release_with_no_entry_is_unmatched():
    entries = [entry(2, "John Ward - Co-op")]
    releases = [release("a", 2, "", "John Ward will begin a co-op assignment"),
                release("b", 2, "", "Susan Wolf will begin a co-op assignment")]
    res = match_subjects(releases, entries)
    assert res.matches["a"].entry == 0 and res.matches["a"].confident
    assert res.matches["b"].entry is None and res.matches["b"].method == "none"


def test_an_entry_with_no_release_is_reported():
    entries = [entry(2, "John Ward - Co-op"), entry(2, "Susan Wolf - Co-op")]
    res = match_subjects([release("a", 2, "", "John Ward will begin a co-op")], entries)
    assert res.matches["a"].entry == 0 and res.unmatched_entries == [1]


def test_identical_looking_candidates_are_ambiguous_not_guessed():
    entries = [entry(9, "Football - Siena"), entry(9, "Football - Union")]
    res = match_subjects([release("a", 9, "", "Football fans will see the season finale")], entries)
    m = res.matches["a"]
    assert m.entry is None and not m.confident and m.method == "date+text" and m.candidates == [0, 1]
    assert res.unmatched_entries == []  # both are still plausible for it


def test_date_alone_matches_but_is_not_confident():
    res = match_subjects([release("a", 2, "", "Completely different words here")], [entry(2, "John Ward - Co-op")])
    m = res.matches["a"]
    assert (m.entry, m.method, m.confident) == (0, "date", False)


def test_release_with_an_unreadable_date_matches_on_text_alone_and_is_flagged():
    entries = [entry(2, "TVR Transportation"), entry(5, "Winter Olympic - NTID")]
    res = match_subjects([release("a", None, "", "The winter Olympic training program for NTID students", False)], entries)
    m = res.matches["a"]
    assert (m.entry, m.method, m.confident) == (1, "text", False)


def test_release_whose_date_has_no_entries_falls_back_to_text():
    entries = [entry(5, "Winter Olympic - NTID")]
    res = match_subjects([release("a", 8, "", "Winter Olympic training for NTID students")], entries)  # misread day
    assert res.matches["a"].entry == 0 and res.matches["a"].method == "text" and not res.matches["a"].confident


def test_common_tags_do_not_carry_a_match():
    entries = [entry(9, f"Person{i} Name{i} - Co-op") for i in range(6)]
    res = match_subjects([release("a", 9, "Co-op", "A co-op student from the college")], entries)
    assert not res.matches["a"].confident  # only the shared tag matched


def test_one_entry_claimed_by_several_releases_is_shared():
    """One list line can cover several releases (e.g. hometown versions of one story)."""
    entries = [entry(3, "Jorjan Neri NTID Drama Club"), entry(3, "James Baker - Co-op")]
    releases = [release("a", 3, "", "Jorjan Neri, a resident of Wilson, took part in an NTID Drama Club production"),
                release("b", 3, "", "Charles Ritenour, a resident of Wilson, took part in an NTID Drama Club production"),
                release("c", 3, "", "Phil Rubin, a resident of Wilson, took part in an NTID Drama Club production")]
    res = match_subjects(releases, entries)
    for k in "abc":
        m = res.matches[k]
        assert (m.entry, m.method, m.confident, m.shared) == (0, "date+text", True, True), k
    assert res.unmatched_entries == [1]  # the other entry is still waiting for its release


def test_a_release_alone_on_its_entry_is_not_shared():
    entries = [entry(3, "Jorjan Neri NTID Drama Club"), entry(3, "James Baker - Co-op")]
    res = match_subjects([release("a", 3, "", "Jorjan Neri took part in an NTID Drama Club production")], entries)
    assert res.matches["a"].entry == 0 and not res.matches["a"].shared


def test_claims_that_are_too_close_are_still_ambiguous_not_shared():
    entries = [entry(9, "Football - Siena"), entry(9, "Football - Union")]
    res = match_subjects([release("a", 9, "", "Football fans will see the finale")], entries)
    assert res.matches["a"].entry is None and not res.matches["a"].shared


def test_a_release_its_day_cannot_settle_falls_back_to_text():
    # The list's day was misread (29 as 20): the day's only entry is someone else's.
    entries = [entry(19, "Bio-Medical Photography grant"), entry(20, "Hermann Zapf, designer")]
    releases = [release("a", 19, "", "Hermann Zapf, internationally-known type designer, will give a lecture"),
                release("b", 19, "", "A grant for bio-medical photography from the Public Health Service")]
    res = match_subjects(releases, entries)
    assert res.matches["b"].entry == 0
    m = res.matches["a"]
    assert (m.entry, m.method, m.confident) == (1, "text", False)


def test_copies_of_one_release_both_get_its_subject_and_are_flagged():
    entries = [entry(28, "Additions to the School of Printing"), entry(28, "Football schedule")]
    text = "Three additions to the School of Printing faculty have been announced by the director"
    res = match_subjects([release("a", 28, "", text), release("b", 28, "", text)], entries)
    for k in "ab":
        m = res.matches[k]
        assert (m.entry, m.confident, m.shared, m.duplicate) == (0, True, False, True), k


def test_a_release_its_day_cannot_settle_still_lists_a_near_entry_from_another_day():
    entries = [entry(19, "Bio-Medical Photography grant"), entry(20, "Leadership Development Workshop Series")]
    releases = [release("a", 19, "", "Inner-city leadership goals will be explored, part of a Leadership Development"),
                release("b", 19, "", "A grant for bio-medical photography from the Public Health Service")]
    m = match_subjects(releases, entries).matches["a"]
    assert (m.entry, m.method, m.confident) == (1, "date", False)  # the only near entry its text supports


def test_a_short_word_in_common_does_not_back_a_match_by_elimination():
    # The list line was misread; "Times" is in it only by chance and "time" in the soccer story.
    entries = [entry(10, "Aperentic= si ae Times ce Glace, goto")]
    releases = [release("soccer", 9, "", "Things are changing in RIT soccer. There was a time when"),
                release("union", 9, "", "Local 230, Lithographers and Photoengravers, is sponsoring a program")]
    res = match_subjects(releases, entries)
    assert res.matches["soccer"].entry is None and res.matches["union"].entry is None


def test_a_days_last_release_and_entry_are_not_paired_when_another_release_names_the_entry():
    # Sept 10 is left with the golf story and "Lofts Carson"; the Sept 9 release is about him.
    entries = [entry(9, "Photographic Society of America"), entry(9, "Annual Women's Tea"),
               entry(10, "Lofts Carson"), entry(10, "Apprentice program -- Lithographers & photo-"),
               entry(10, "Gulf Oil grant")]
    releases = [release("carson", 9, "", "Loftus C. Carson, Monroe County Human Relations Commission director"),
                release("tea", 9, "", "The annual fall tea for new women faculty members"),
                release("memo", 10, "", "Memo to editors: the release on the apprentice program of the Lithographers"),
                release("golf", 10, "", "For the second straight year Alan Dirk has been named captain of the golf team"),
                release("gulf", 10, "", "Gulf Oil Corporation has given a capital grant of $15,000")]
    m = match_subjects(releases, entries).matches
    assert m["carson"].entry == 2 and m["golf"].entry is None


def test_a_hyphenated_subject_word_matches_its_parts_written_apart():
    entries = [entry(9, "Jacques Van Droogenbroeck -- Belgian visitor"), entry(9, "Operation-Tie up"),
               entry(10, "Sports -- different subjects")]
    releases = [release("belgian", 9, "", "Belgian people are american-minded, Jacques Van Droogenbroeck says"),
                release("tie", 9, "", "OPERATION TIE-UP As college students across the nation gear up")]
    m = match_subjects(releases, entries).matches
    assert m["tie"].entry == 1 and m["tie"].method == "date+text"


def test_a_release_can_share_its_entry_with_the_memo_correcting_it():
    # Listed on the 10th, the day of the correction memo; the release itself went out on the 9th.
    entries = [entry(9, "Annual Women's Tea"), entry(10, "Apprentice program -- Lithographers & photo-"),
               entry(10, "Gulf Oil grant"), entry(15, "Meeting of the U.S. Assoc. of Evening Students")]  # a weaker rival
    releases = [release("tea", 9, "", "The annual fall tea for new women faculty members"),
                release("union", 9, "", "Local 230, Lithographers and Photoengravers International Union, is "
                                        "sponsoring a special apprentice program, Tuesday evening, for students"),
                release("memo", 10, "", "Memo to editors: in the release on the Lithographers apprentice program, "
                                        "please make it read"),
                release("gulf", 10, "", "Gulf Oil Corporation has given a capital grant of $15,000")]
    m = match_subjects(releases, entries).matches
    assert m["memo"].entry == 1 and (m["union"].entry, m["union"].method, m["union"].confident) == (1, "text", False)
