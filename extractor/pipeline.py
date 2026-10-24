"""Full per-page pipeline: clean up image -> two OCR engines -> fields -> reconciled row."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace

from PIL import Image

from . import ocr
from .layout import HEADER_CUE, body_words, find_slug
from .models import Line, Word
from .pages import HEAD, PageSignals, has_release_header, page_signals
from .listpage import (DAY_DRIFT, bare_day_column, day_column, days_in_order, has_month_line, header_band,
                       is_list_page, missing_day_cells, vote_days, with_days, with_month_line)
from .reread import regions_from, reread, reread_trocr
from .extract import EngineReading, _alnum, _same_words, read_fields, reconcile_date, reconcile_words
from .preprocess import clean_page, deskew, flatten_page, normalize_size
from .words import LANG_TO_TESS, detect_language

LOW_RES_WIDTH = 1500
OPENING_WORDS = 40  # article words kept to match list-page subjects against
DAY_SURE, REREAD_SURE = 70, 90  # confidence of a list day read in its column, and of its re-read
# The "Date" column is read several ways (in grey or not, and with white margins of several
# widths around it): each reading drops or garbles different days, so they vote.
DAY_READS = ((False, 0), (True, 0), (True, ocr.CELL_PAD), (False, ocr.CELL_PAD), (True, 2 * ocr.CELL_PAD))
# Margins (in line heights, above and below) a missed day's cell is read with, one read each.
CELL_MARGINS = [(above, below) for above in (0, 0.125, 0.25, 0.375, 0.5) for below in (0, 0.2)]
LINE_SURE, LINE_GAIN = 60, 10  # a list line with a word read below this is read again; kept if surer by this


@dataclass(frozen=True)
class Options:
    # Focused crop re-read of the date and opening words (experimental):
    # "off", "all" (both engines), "easyocr" (EasyOCR always), "tiebreak" (EasyOCR, only
    # where the full-page reads disagree, and only kept if it then agrees with Tesseract)
    reread: str = "tiebreak"
    best_model: bool = False  # Tesseract "best" models (setup --tess-best)
    multipass: bool = False  # 3 differently cleaned Tesseract passes per field, majority vote
    clean: bool = False  # deskew + remove uneven lighting + light denoise before OCR
    # Engines that vote. Tesseract always leads (layout + value); "easyocr" and "doctr" read
    # the whole page, "trocr" re-reads just the date and opening rows.
    engines: tuple[str, ...] = ("tesseract", "easyocr", "doctr")


@dataclass
class Row:
    file: str
    page: int
    item_number: str
    release_date: str
    release_date_as_printed: str
    first_five_words: str
    date_verified: str
    words_verified: str
    date_confidence: str
    words_confidence: str
    language: str
    needs_review: str
    review_reasons: str
    # Filled in by the folder pass (list-page subjects, multi-page releases).
    subject: str = ""
    subject_verified: str = ""
    subject_match: str = ""  # how the subject was found: date+text, date, text, none; blank without a list page
    slug: str = ""  # short subject tag printed under the date, used for matching
    opening_text: str = ""  # first words of the article, used for matching
    page_count: int = 1
    pages: str = ""  # every page of the release, "file p1, file p2"
    folder: str = ""
    # Filled in by the cataloguing step (extractor/catalog.py) when a box and folder number are known.
    box: str = ""
    folder_no: str = ""
    release_no: str = ""  # position of the release in the folder, in photo order
    file_name: str = ""  # the proposed name of the release's PDF, without ".pdf"
    digitized: str = ""  # when the release's (first) source file was made, yyyy-mm-dd


@dataclass
class PageResult:
    """One page as the folder pass needs it: the row, cues for grouping pages into releases,
    the text used to match list-page subjects, and, for a list page, its OCR lines."""
    row: Row | None  # None for a list page
    signals: PageSignals
    slug: str = ""
    opening: str = ""
    list_lines: list[Line] | None = None


def process_page(img: Image.Image, file: str, page: int, item_number: str = "",
                 force_lang: str | None = None, opts: Options = Options()) -> Row:
    return analyze_page(img, file, page, item_number, force_lang, opts, detect_list=False).row


def analyze_page(img: Image.Image, file: str, page: int, item_number: str = "",
                 force_lang: str | None = None, opts: Options = Options(), detect_list: bool = True) -> PageResult:
    result = _process_page(img, file, page, item_number, force_lang, opts, detect_list)
    row = result.row
    if row is not None and row.needs_review == "YES" and not opts.clean:
        # Lighting/tilt cleanup hurts some pages and rescues others, so it is only a second
        # chance for flagged pages. The retry replaces the first result only if it leaves fewer
        # reasons to review; verification still needs the same engine agreement either way.
        retry = _process_page(img, file, page, item_number, force_lang, replace(opts, clean=True), detect_list)
        if retry.row.review_reasons.count(" | ") < row.review_reasons.count(" | "):
            return retry
    return result


def _process_page(img: Image.Image, file: str, page: int, item_number: str = "",
                  force_lang: str | None = None, opts: Options = Options(), detect_list: bool = False) -> PageResult:
    reasons: list[str] = []
    flat, _ = flatten_page(img)
    # Captures are always shot upright; OSD's rotation guess was wrong on some pages
    # (typewriter text plus a sideways folder label), so only its script guess is used.
    _, script = ocr.tesseract_osd(flat)
    if flat.width < LOW_RES_WIDTH:
        reasons.append(f"low-resolution page ({flat.width}px wide); a closer photo would be more reliable")
    if opts.clean:
        flat, _ = deskew(flat)
    page_img = normalize_size(flat)
    if opts.clean:
        page_img = clean_page(page_img)

    if script and script != "Latin" and script not in ocr.SCRIPT_TO_TESS:
        reasons.append(f"unsupported script '{script}'; read as Latin")
    tess_lang = force_lang or ocr.SCRIPT_TO_TESS.get(script or "Latin", "eng")
    best = opts.best_model
    lines, bare = None, None
    if not force_lang and tess_lang != "eng":
        # OSD sometimes calls all-capitals English typescript Cyrillic. A non-Latin guess is only
        # trusted if an English read of the page is not clearly English.
        english = ocr.tesseract_lines(page_img, "eng", best=best and ocr.best_model_available("eng"))
        found, margin = detect_language(" ".join(ln.text for ln in english))
        if found == "en" and margin >= 2.0:
            tess_lang, lines = "eng", english
    if best and not ocr.best_model_available(tess_lang):
        reasons.append(f"best model for '{tess_lang}' not installed (setup --tess-best); used standard model")
    if lines is None:
        lines = ocr.tesseract_lines(page_img, tess_lang, best=best)
    if detect_list and (is_list_page(lines) or (bare := _bare_list(page_img, lines))):
        lines = read_list_page(page_img, lines, tess_lang, best, box=bare)
        return PageResult(None, page_signals(lines), list_lines=lines)
    lines = _sparse_header(page_img, lines, tess_lang, best)
    signals = page_signals(lines)
    # Assume English (nearly every release is); switch only when another language clearly wins.
    detected, margin = detect_language(" ".join(ln.text for ln in lines))
    lang = "en"
    if force_lang or not detected or detected == "en":
        pass
    elif margin >= 2.0 and detected in LANG_TO_TESS:
        lang = detected
        if tess_lang == "eng":
            tess_lang = LANG_TO_TESS[lang]
            lines = ocr.tesseract_lines(page_img, tess_lang, best=best)  # re-read with the right language model
    else:
        reasons.append(f"text may be non-English (weak signal for '{detected}'); read as English")

    readings = [read_fields("tesseract", lines, lang)]
    easy_langs = ocr.easy_langs_for(tess_lang)
    if "easyocr" not in opts.engines:
        pass
    elif easy_langs is None:
        reasons.append(f"second OCR engine cannot read '{tess_lang}'; single-engine result")
    else:
        try:
            readings.append(read_fields("easyocr", ocr.easyocr_lines(page_img, easy_langs), lang, readings[0].anchor))
        except FileNotFoundError:
            reasons.append(f"EasyOCR model for {easy_langs} not installed (run: python -m extractor setup "
                           f"--langs {' '.join(easy_langs)}); single-engine result")

    if "doctr" in opts.engines and ocr.doctr_available():
        readings.append(read_fields("doctr", ocr.doctr_lines(page_img), lang, readings[0].anchor))
    if "trocr" in opts.engines and readings[0].start is not None:
        rr = reread_trocr(page_img, regions_from(lines, readings[0]), lang)
        readings.append(EngineReading("trocr", rr.date, rr.words or [],
                                      list(rr.date.flags) if rr.date else [], rr.word_flags))

    # EasyOCR reads at Tesseract's chosen spot, which checks the reading but not the choice
    # of spot, so sanity-check the choice itself.
    layout_flag = _check_start(lines, readings[0].start)
    if layout_flag:
        readings[0].word_flags.append(layout_flag)

    if opts.reread != "off" and readings[0].start is not None:
        _apply_reread(readings, lines, page_img, lang, tess_lang, easy_langs, opts)

    date = reconcile_date(readings)
    words = reconcile_words(readings)
    # Page-level problems (resolution, language, single engine) apply to both fields.
    date_ok = not reasons and not date.reasons
    words_ok = not reasons and not words.reasons
    reasons += date.reasons + [r for r in words.reasons if r not in date.reasons]
    printed = next((r.date.printed for r in readings if r.date and r.date.iso == date.value), "")
    start = readings[0].start
    if start is not None:
        slug = find_slug(lines, start)
        opening = " ".join(w.text for w in body_words(lines, start, OPENING_WORDS))
    else:  # no body found: the whole page is the best text there is to match on
        everything = " ".join(w.text for ln in lines for w in ln.words)
        slug, opening = "", " ".join(everything.split()[:OPENING_WORDS])
    row = Row(
        file=file, page=page, item_number=item_number,
        release_date=date.value, release_date_as_printed=" ".join(printed.split()),
        first_five_words=words.value,
        date_verified="YES" if date_ok else "NO", words_verified="YES" if words_ok else "NO",
        date_confidence=f"{date.confidence:.0f}", words_confidence=f"{words.confidence:.0f}",
        language=lang,
        needs_review="YES" if reasons else "no",
        review_reasons=" | ".join(reasons),
        slug=slug, opening_text=opening,
    )
    return PageResult(row, signals, slug, opening)


def read_list_page(page_img: Image.Image, lines: list[Line], lang: str = "eng", best: bool = False,
                   show: Callable[[str, object], None] = lambda step, value: None,
                   box: tuple[int, int, int, int] | None = None) -> list[Line]:
    """A list page's lines with what the page read lost put back: unsure lines read again, the
    MONTH line, and the days of a "Date" column (box, if already known). show(step, value) sees
    each step (debug)."""
    lines = [_reread_line(page_img, ln, lang, best) for ln in lines]
    if not has_month_line(lines) and (band := header_band(lines)):  # sparse mode keeps it apart from its dotted rule
        lines = with_month_line(lines, ocr.tesseract_lines(page_img.crop(band), lang, psm=11, best=best))
    box = box or day_column(lines)
    show("day column", box)
    if box:
        reads = [ocr.tesseract_digits(page_img, box, pad=pad, gray=gray) for gray, pad in DAY_READS]
        for (gray, pad), read in zip(DAY_READS, reads):
            show(f"days read ({'grey' if gray else 'colour'}, margin {pad})", " ".join(f"{w.text}@y{w.box[1]}" for w in read))
        days = [_reread_day(page_img, box, w) for w in vote_days(reads)]
        show("days voted", " ".join(f"{w.text}@y{w.box[1]}" for w in days))
        cells = missing_day_cells(with_days(lines, days, box), box)
        show("cells re-read", cells)
        for cell in cells:
            days += _read_day_cell(page_img, cell, days)
        lines = with_days(lines, days, box)
    return lines


def _bare_list(page_img: Image.Image, lines: list[Line]) -> tuple[int, int, int, int] | None:
    """The day column of a list's next page whose days the page read dropped, with its title and
    headings on the page before: a page with no release header, letterhead or page number, its
    lines starting together, and a day read beside most of them, in order."""
    signals = page_signals(lines)
    if signals.starts or signals.cont or not (box := bare_day_column(lines)):
        return None
    days = vote_days([ocr.tesseract_digits(page_img, box, pad=pad, gray=gray) for gray, pad in DAY_READS])
    return box if days_in_order(days, sum(1 for ln in lines if ln.words)) else None


def _reread_day(page_img: Image.Image, column: tuple[int, int, int, int], day: Word) -> Word:
    """A day the column read was unsure of, read again on its own: two days typed close
    together can read as one wrong number ("19" as "9"). The new reading is kept only if sure."""
    if day.conf >= DAY_SURE:
        return day
    pad = (day.box[3] - day.box[1]) // 3
    again = ocr.tesseract_digits(page_img, (column[0], day.box[1] - pad, column[2], day.box[3] + pad), cell=True)
    best = max(again, key=lambda w: w.conf, default=None)
    return best if best and best.conf >= REREAD_SURE else day


def _reread_line(page_img: Image.Image, line: Line, lang: str, best: bool) -> Line:
    """A list line with a word the page read was unsure of, read again on its own; a new
    reading is kept only if Tesseract is clearly surer of it. First the whole line; failing
    that, just its unsure words, also cropped to one line of text from the top, since a
    handwritten note under a typed line can garble both into one tall line of nonsense."""
    if min(w.conf for w in line.words) >= LINE_SURE:
        return line
    mean = lambda words: sum(w.conf for w in words) / len(words)
    again = ocr.tesseract_line(page_img, _padded(page_img, line.box, (line.box[3] - line.box[1]) // 3), lang, best)
    if again.words and mean(again.words) >= mean(line.words) + LINE_GAIN:
        return again
    unsure = [i for i, w in enumerate(line.words) if w.conf < LINE_SURE]
    first, last = unsure[0], unsure[-1]
    span = line.words[first:last + 1]
    sure = [w for w in line.words if w.conf >= LINE_SURE] or line.words
    height = sorted(w.box[3] - w.box[1] for w in sure)[len(sure) // 2]
    x0, x1 = span[0].box[0], span[-1].box[2]
    y0, y1 = min(w.box[1] for w in span), max(w.box[3] for w in span)
    boxes = [(x0, y0, x1, y1)] + ([(x0, y0, x1, y0 + round(1.3 * height))] if y1 - y0 > 1.6 * height else [])
    reads = [ocr.tesseract_line(page_img, _padded(page_img, box, pad), lang, best)
             for box in boxes for pad in (0, height // 3)]
    found = max((r for r in reads if r.words), key=lambda r: mean(r.words), default=None)
    if found and mean(found.words) >= mean(span) + LINE_GAIN:
        return Line(line.words[:first] + found.words + line.words[last + 1:])
    return line


def _same_spot(a: Word, b: Word) -> bool:
    """Do two readings overlap, across and over more than half the shorter one's height?"""
    across = min(a.box[2], b.box[2]) > max(a.box[0], b.box[0])
    down = min(a.box[3], b.box[3]) - max(a.box[1], b.box[1])
    return across and down > 0.5 * min(a.box[3] - a.box[1], b.box[3] - b.box[1])


def _padded(page_img: Image.Image, box: tuple[int, int, int, int], pad: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, page_img.width), min(y1 + pad, page_img.height)


def _read_day_cell(page_img: Image.Image, cell: tuple[int, int, int, int], days: list[Word]) -> list[Word]:
    """A row's day the column reads missed, read on its own. A lone number read by itself
    comes and goes with the exact crop ("11" read as "1" or not at all a few pixels off), but
    across crops the right reading is the surest, so a few are read: from the page edge and
    from a little left of where the days stand (a punch hole at the edge can garble the first;
    the second can lose a day typed further left), each with margins above and below of up to
    half a line."""
    x0s, height = [cell[0]], cell[3] - cell[1]
    if days:
        height = sorted(w.box[3] - w.box[1] for w in days)[len(days) // 2]
        x0s.append(max(cell[0], sorted(w.box[0] for w in days)[len(days) // 2] - DAY_DRIFT * height))
    _, y0, x1, y1 = cell
    reads = []
    for x0 in dict.fromkeys(x0s):
        for above, below in CELL_MARGINS:
            box = (x0, max(y0 - round(above * height), 0), x1, min(y1 + round(below * height), page_img.height))
            reads += ocr.tesseract_digits(page_img, box, cell=True)
    # A crop reaching into the row above or below can read that row's day: it is not this one.
    # (A day read with no confidence, a punch hole and a day run together, is no such day.)
    found = [w for w in reads if w.text.isdigit() and 1 <= int(w.text) <= 31
             and not any(_same_spot(w, d) for d in days if d.conf >= DAY_SURE)]
    return [max(found, key=lambda w: w.conf)] if found else []


def _sparse_header(page_img: Image.Image, lines: list[Line], tess_lang: str, best: bool) -> list[Line]:
    """A page with neither a release header nor a page number at the top would be joined to the
    release before it. When a date is typed just above "FOR IMMEDIATE RELEASE", Tesseract can
    read the two as one garbled line and drop it, so look again in sparse-text mode (which keeps
    such lines apart) and, if that finds a release line, use its reading of the header."""
    if has_release_header(lines) or page_signals(lines).cont:  # a letterhead alone has no date
        return lines
    sparse = ocr.tesseract_lines(page_img, tess_lang, psm=11, best=best)
    cues = [ln for ln in sparse[:HEAD] if HEADER_CUE.search(ln.text)]
    if not cues:
        return lines
    cut = max(ln.box[3] for ln in cues)
    return [ln for ln in sparse if ln.box[3] <= cut] + [ln for ln in lines if ln.box[1] > cut]


def _check_start(t_lines, t_start) -> str | None:
    """Flag if text above the chosen article start reads like article prose, i.e. the
    layout may have picked a later paragraph. Letterheads, addresses, contacts and caps
    headlines don't look like this."""
    if t_start is None or t_start.dateline is not None:
        return None
    for line in t_lines[:t_start.line]:
        toks = [w.text for w in line.words if any(c.isalpha() for c in w.text)]
        lower = sum(1 for t in toks if t.lstrip("\"'(“‘")[:1].islower())
        if len(toks) >= 6 and lower >= 0.5 * len(toks):
            return "text above the chosen start reads like article text; check where the article starts"
    return None


def _dates_agree(a, b) -> bool:
    return a is not None and b is not None and a.iso == b.iso and _alnum(a.printed) == _alnum(b.printed)


def _apply_reread(readings, lines, page_img, lang, tess_lang, easy_langs, opts: Options) -> None:
    """Replace engines' full-page fields with focused re-reads (see Options.reread).
    Crop positions come from Tesseract's layout, so layout flags stay with that engine."""
    mode = opts.reread
    tess = readings[0]
    words_disagree = dates_disagree = True
    easy = next((r for r in readings if r.engine == "easyocr"), None)
    if easy is None:
        return
    if mode == "tiebreak":
        other = easy
        words_disagree = not _same_words([w.text for w in tess.words], [w.text for w in other.words])
        dates_disagree = tess.date is not None and not _dates_agree(tess.date, other.date)
        if not (words_disagree or dates_disagree):
            return
    regions = regions_from(lines, tess)
    for r in readings:
        primary = r is tess
        if (primary and mode != "all") or r.engine not in ("tesseract", "easyocr"):
            continue
        rr = reread(r.engine, page_img, regions, lang, tess_lang, easy_langs, opts.best_model, opts.multipass)
        if mode == "tiebreak":  # only accept a re-read that settles a disagreement
            if dates_disagree and _dates_agree(tess.date, rr.date):
                r.date, r.date_flags = rr.date, list(rr.date.flags)
            if words_disagree and rr.words and _same_words([w.text for w in tess.words], [w.text for w in rr.words]):
                r.words, r.word_flags = rr.words, list(rr.word_flags)
            continue
        if rr.date is not None:
            context = [f for f in r.date_flags if not (r.date and f in r.date.flags)] if primary else []
            r.date = rr.date
            r.date_flags = context + list(rr.date.flags)
        if rr.words is not None:
            r.words = rr.words
            r.word_flags = (list(r.start.flags) if primary else []) + rr.word_flags
        r.date_flags += rr.date_notes
        r.word_flags += rr.word_notes


def failed_row(file: str, item_number: str, reason: str) -> Row:
    return Row(file=file, page=1, item_number=item_number, release_date="", release_date_as_printed="",
               first_five_words="", date_verified="NO", words_verified="NO", date_confidence="0",
               words_confidence="0", language="unknown", needs_review="YES", review_reasons=reason)


def row_dict(row: Row) -> dict:
    return asdict(row)
