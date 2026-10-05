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
    date_confidence: str
    words_confidence: str
    language: str
    needs_review: str
    review_reasons: str


def _merge_engine_flags(readings) -> list[str]:
    """Flags raised by every engine are listed once; engine-specific ones get a prefix."""
    out = []
    all_flags = [set(r.flags) for r in readings]
    for r in readings:
        for f in r.flags:
            text = f if all(f in s for s in all_flags) else f"{r.engine}: {f}"
            if text not in out:
                out.append(text)
    return out


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
    lang, margin = detect_language(" ".join(ln.text for ln in lines))
    if not force_lang and lang and lang != "en" and tess_lang == "eng" and lang in LANG_TO_TESS:
        tess_lang = LANG_TO_TESS[lang]
        lines = ocr.tesseract_lines(page_img, tess_lang)  # re-read with the right language model
    if lang and margin < 2.0:
        reasons.append(f"language identification uncertain (best guess '{lang}')")

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
    reasons += _merge_engine_flags(readings) + date.reasons + words.reasons
    if not date.value:
        reasons.append("no release date found")
    if not words.value:
        reasons.append("no article words found")
    printed = next((r.date.printed for r in readings if r.date and r.date.iso == date.value), "")
    reasons = list(dict.fromkeys(reasons))
    return Row(
        file=file, page=page, item_number=item_number,
        release_date=date.value, release_date_as_printed=" ".join(printed.split()),
        first_five_words=words.value,
        date_confidence=f"{date.confidence:.0f}", words_confidence=f"{words.confidence:.0f}",
        language=lang or "unknown",
        needs_review="YES" if reasons else "no",
        review_reasons=" | ".join(reasons),
    )


def row_dict(row: Row) -> dict:
    return asdict(row)
