"""Full per-page pipeline: clean up image -> two OCR engines -> fields -> reconciled row."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from PIL import Image

from . import ocr
from .reread import regions_from, reread, reread_trocr
from .extract import EngineReading, _alnum, _same_words, read_fields, reconcile_date, reconcile_words
from .preprocess import clean_page, deskew, flatten_page, normalize_size
from .words import LANG_TO_TESS, detect_language

LOW_RES_WIDTH = 1500


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


def process_page(img: Image.Image, file: str, page: int, item_number: str = "",
                 force_lang: str | None = None, opts: Options = Options()) -> Row:
    reasons: list[str] = []
    flat, _ = flatten_page(img)
    rotate, script = ocr.tesseract_osd(flat)
    if rotate:
        flat = flat.rotate(-rotate, expand=True)  # OSD reports clockwise degrees to fix
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
    if best and not ocr.best_model_available(tess_lang):
        reasons.append(f"best model for '{tess_lang}' not installed (setup --tess-best); used standard model")
    lines = ocr.tesseract_lines(page_img, tess_lang, best=best)
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
    return Row(
        file=file, page=page, item_number=item_number,
        release_date=date.value, release_date_as_printed=" ".join(printed.split()),
        first_five_words=words.value,
        date_verified="YES" if date_ok else "NO", words_verified="YES" if words_ok else "NO",
        date_confidence=f"{date.confidence:.0f}", words_confidence=f"{words.confidence:.0f}",
        language=lang,
        needs_review="YES" if reasons else "no",
        review_reasons=" | ".join(reasons),
    )


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
