"""Full per-page pipeline: clean up image -> two OCR engines -> fields -> reconciled row."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from PIL import Image

from . import ocr
from .extract import read_fields, reconcile_date, reconcile_words
from .preprocess import flatten_page, normalize_size
from .words import LANG_TO_TESS, detect_language

LOW_RES_WIDTH = 1500


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


def process_page(img: Image.Image, file: str, page: int, item_number: str = "", force_lang: str | None = None) -> Row:
    reasons: list[str] = []
    flat, _ = flatten_page(img)
    rotate, script = ocr.tesseract_osd(flat)
    if rotate:
        flat = flat.rotate(-rotate, expand=True)  # OSD reports clockwise degrees to fix
    if flat.width < LOW_RES_WIDTH:
        reasons.append(f"low-resolution page ({flat.width}px wide); a closer photo would be more reliable")
    page_img = normalize_size(flat)

    if script and script != "Latin" and script not in ocr.SCRIPT_TO_TESS:
        reasons.append(f"unsupported script '{script}'; read as Latin")
    tess_lang = force_lang or ocr.SCRIPT_TO_TESS.get(script or "Latin", "eng")
    lines = ocr.tesseract_lines(page_img, tess_lang)
    # Assume English (nearly every release is); switch only when another language clearly wins.
    detected, margin = detect_language(" ".join(ln.text for ln in lines))
    lang = "en"
    if force_lang or not detected or detected == "en":
        pass
    elif margin >= 2.0 and detected in LANG_TO_TESS:
        lang = detected
        if tess_lang == "eng":
            tess_lang = LANG_TO_TESS[lang]
            lines = ocr.tesseract_lines(page_img, tess_lang)  # re-read with the right language model
    else:
        reasons.append(f"text may be non-English (weak signal for '{detected}'); read as English")

    readings = [read_fields("tesseract", lines, lang)]
    easy_langs = ocr.easy_langs_for(tess_lang)
    if easy_langs is None:
        reasons.append(f"second OCR engine cannot read '{tess_lang}'; single-engine result")
    else:
        try:
            readings.append(read_fields("easyocr", ocr.easyocr_lines(page_img, easy_langs), lang, readings[0].anchor))
        except FileNotFoundError:
            reasons.append(f"EasyOCR model for {easy_langs} not installed (run: python -m extractor setup "
                           f"--langs {' '.join(easy_langs)}); single-engine result")

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


def failed_row(file: str, item_number: str, reason: str) -> Row:
    return Row(file=file, page=1, item_number=item_number, release_date="", release_date_as_printed="",
               first_five_words="", date_verified="NO", words_verified="NO", date_confidence="0",
               words_confidence="0", language="unknown", needs_review="YES", review_reasons=reason)


def row_dict(row: Row) -> dict:
    return asdict(row)
