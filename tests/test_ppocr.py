"""The PP-OCR reader's handling of Tesseract's lines (the model itself is not needed)."""
from extractor import ppocr
from extractor.models import Line, Word


def test_a_line_is_read_in_stretches_split_at_a_column_gap():
    """A dateline with a phone number far to its right: read as one, the model runs them together."""
    line = Line([Word("October", 90, (277, 684, 456, 717)), Word("9,", 90, (484, 681, 526, 720)),
                 Word("1969", 90, (561, 671, 660, 715)), Word("46-2338", 90, (1629, 637, 1833, 682))])
    assert ppocr._stretches(line) == [(277, 671, 660, 720), (1629, 637, 1833, 682)]


def test_words_spaced_normally_stay_one_stretch():
    line = Line([Word(t, 90, (x, 100, x + 80, 130)) for t, x in (("As", 100), ("college", 200), ("students", 300))])
    assert ppocr._stretches(line) == [(100, 100, 380, 130)]


def test_the_letter_height_ignores_the_tilt_of_the_whole_line():
    line = Line([Word("As", 90, (409, 933, 460, 963)), Word("college", 90, (492, 929, 667, 966)),
                 Word("Vietnam", 90, (1992, 886, 2174, 920))])
    assert ppocr._letter_height(line) == 34
