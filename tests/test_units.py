import socket

import pytest

from extractor import netguard
from extractor.dates import parse_dates_in_line, pick_release_date
from extractor.extract import EngineReading, reconcile_words
from extractor.layout import BodyWord, body_words, find_body_start
from extractor.models import Line, Word, split_dashes
from extractor.words import clean_word, detect_language, strip_leading_articles


def mkline(text: str, y: int = 0, conf: float = 99.0) -> Line:
    words, x = [], 0
    for tok in text.split():
        words.append(Word(tok, conf, (x, y, x + 10 * len(tok), y + 30)))
        x += 10 * len(tok) + 10
    return Line(split_dashes(words))


def mkpage(*texts: str) -> list[Line]:
    return [mkline(t, i * 50) for i, t in enumerate(texts)]


# --- dates -----------------------------------------------------------------

@pytest.mark.parametrize("text,iso", [
    ("May 3, 1987", "1987-05-03"),
    ("May 3 , 1987", "1987-05-03"),
    ("Sept. 30, 1975", "1975-09-30"),
    ("For release: Oct. 12, 1979", "1979-10-12"),
    ("3 May 1987", "1987-05-03"),
    ("le 14 mars 1992", "1992-03-14"),
    ("14 de marzo de 1992", "1992-03-14"),
    ("3. Mai 1987", "1987-05-03"),
    ("December 1st, 1969", "1969-12-01"),
    ("1987-05-03", "1987-05-03"),
])
def test_parse_dates(text, iso):
    found = parse_dates_in_line(mkline(text), 0)
    assert [d.iso for d in found] == [iso]
    assert found[0].flags == []


@pytest.mark.parametrize("text,iso,flag", [
    ("5/3/87", "1987-05-03", "US month/day"),
    ("25/3/1987", "1987-03-25", "day/month"),
    ("May 3, '87", "1987-05-03", "two-digit year"),
    ("May 1987", "1987-05", "no day"),
])
def test_ambiguous_dates_are_flagged(text, iso, flag):
    (d,) = parse_dates_in_line(mkline(text), 0)
    assert d.iso == iso and any(flag in f for f in d.flags)


def test_invalid_calendar_date_ignored():
    assert parse_dates_in_line(mkline("February 30, 1987"), 0) == []


def test_release_cue_wins_over_other_header_dates():
    lines = mkpage("Revised June 1, 1988", "FOR RELEASE", "May 3, 1987", "ROCHESTER, N.Y. -- The body")
    d, flags = pick_release_date(lines, 3, lines[3])
    assert d.iso == "1987-05-03"
    assert any("other dates" in f for f in flags)


def test_body_dates_are_ignored():
    lines = mkpage("May 3, 1987", "ROCHESTER -- It began on June 1, 1984 at the old campus downtown.")
    d, flags = pick_release_date(lines, 1, Line(lines[1].words[:2]))
    assert d.iso == "1987-05-03"


# --- words -----------------------------------------------------------------

@pytest.mark.parametrize("words,lang,expected", [
    (["The", "college", "announced"], "en", ["college", "announced"]),
    (["A", "team", "of"], "en", ["team", "of"]),
    (["L'université", "a", "annoncé"], "fr", ["université", "a", "annoncé"]),
    (["Los", "estudiantes"], "es", ["estudiantes"]),
    (["Die", "Hochschule"], "de", ["Hochschule"]),
    (["'t", "Huis"], "nl", ["Huis"]),
    (["Rochester", "Institute"], "en", ["Rochester", "Institute"]),
    (["I", "am", "pleased"], "en", ["I", "am", "pleased"]),  # English "I" is not an article
])
def test_strip_leading_articles(words, lang, expected):
    assert strip_leading_articles(words, lang)[0] == expected


@pytest.mark.parametrize("raw,clean", [
    ('"The', "The"), ("Friday,", "Friday"), ("today.", "today"), ("Dr.", "Dr."),
    ("U.S.", "U.S."), ("(RIT)", "RIT"), ("aujourd'hui", "aujourd'hui"), ("“Hello”", "Hello"),
])
def test_clean_word(raw, clean):
    assert clean_word(raw) == clean


def test_detect_language():
    en = "The college will open the new building for students and faculty on Friday, and the public is invited to the event that was planned by the staff."
    fr = "La délégation de professeurs se rendra à Montréal pour une conférence sur la technologie et les arts dans le cadre du programme qui est pour les étudiants avec des collègues."
    assert detect_language(en)[0] == "en"
    assert detect_language(fr)[0] == "fr"


# --- layout ----------------------------------------------------------------

def test_dateline_with_glued_dash():
    lines = mkpage("FOR IMMEDIATE RELEASE", "RIT OPENS NEW LAB",
                   "ROCHESTER, N.Y.—The college opened a new lab on the", "east side of campus today.")
    start = find_body_start(lines)
    assert (start.line, lines[start.line].words[start.word].text) == (2, "The")
    assert start.flags == []


def test_caps_headline_with_dash_is_not_a_dateline():
    lines = mkpage("RIT WINS GRANT -- FUNDS NEW CENTER", "ROCHESTER, N.Y. -- The college won a large grant from the state.")
    start = find_body_start(lines)
    assert start.line == 1


def test_missing_dash_is_flagged():
    lines = mkpage("ROCHESTER, N.Y. The college opened a new lab on the east side.")
    start = find_body_start(lines)
    assert lines[0].words[start.word].text == "The" and start.flags


def test_no_dateline_inferred_and_flagged():
    lines = mkpage("NEWS RELEASE", "The college opened a new lab on the east side of campus today.")
    start = find_body_start(lines)
    assert start.line == 1 and "inferred" in start.flags[0]


def test_hyphenated_word_joined_and_noted():
    lines = mkpage("ROCHESTER, N.Y. -- The new uni-", "versity building opened.")
    words = body_words(lines, find_body_start(lines))
    assert [w.text for w in words][:3] == ["The", "new", "university"]
    assert words[2].note


# --- consensus -------------------------------------------------------------

def test_disagreement_zeroes_confidence():
    a = EngineReading("tesseract", None, [BodyWord("college", 95)])
    b = EngineReading("easyocr", None, [BodyWord("co1lege", 95)])
    r = reconcile_words([a, b])
    assert r.confidence == 0 and "disagree" in r.reasons[0]


def test_agreement_with_low_tesseract_conf_is_flagged():
    a = EngineReading("tesseract", None, [BodyWord("college", 70)])
    b = EngineReading("easyocr", None, [BodyWord("college", 95)])
    assert reconcile_words([a, b]).reasons


# --- network guard ---------------------------------------------------------

def test_netguard_blocks_outbound():
    netguard.enable()
    with pytest.raises(netguard.NetworkBlocked):
        socket.create_connection(("example.com", 80))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(netguard.NetworkBlocked):
        s.connect(("1.1.1.1", 80))
    s.close()
