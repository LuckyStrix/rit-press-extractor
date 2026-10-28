"""Local OCR engines. Images are piped in memory; nothing is written to disk."""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import threading
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .models import Line, Word, merge_rows, split_dashes

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
TESSDATA_BEST = MODELS_DIR / "tessdata_best"  # optional, filled by `setup --tess-best`
CELL_PAD = 40  # white margin around a single cell read on its own
# The neural engines' models are loaded once per process and shared by its threads, which take
# turns with each model (on a GPU each turn is short). Each model has its own lock, so one thread
# can read with EasyOCR while another reads with docTR. Tesseract runs as its own program.
EASYOCR_LOCK, DOCTR_LOCK, TROCR_LOCK = threading.RLock(), threading.RLock(), threading.RLock()
def _find_tesseract() -> str:
    """$TESSERACT, else PATH, else where a Windows install puts it: per-user (no administrator
    needed), a copy inside the project folder, or the all-users default."""
    if found := os.environ.get("TESSERACT") or shutil.which("tesseract"):
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        MODELS_DIR.parent / "tesseract" / "tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    ]
    return str(next((c for c in candidates if c.is_file()), candidates[-1]))


TESSERACT = _find_tesseract()

# Harmless PyTorch notices from EasyOCR on a CPU-only machine; they don't affect results.
warnings.filterwarnings("ignore", message=r".*pin_memory.*no accelerator", category=UserWarning)
warnings.filterwarnings("ignore", message=r".*quantize_per_tensor.*deprecated", category=UserWarning)
# EasyOCR's beam search overflows on crops where almost all probability sat on ignored
# characters; that read comes out as garbage, and the re-read tie-breaker discards any
# read that doesn't match Tesseract exactly, so the warning is noise.
warnings.filterwarnings("ignore", message=r"overflow encountered", category=RuntimeWarning, module=r"easyocr")

# Tesseract script name (from OSD) -> Tesseract language model to use.
SCRIPT_TO_TESS = {
    "Latin": "eng",
    "Fraktur": "eng",  # a Latin typeface; OSD reports it for some typewriter faces
    "Cyrillic": "rus+ukr+bul+srp",
    "Greek": "ell",
    "Han": "chi_sim+chi_tra",
    "Japanese": "jpn",
    "Hangul": "kor",
    "Korean": "kor",
    "Arabic": "ara+fas",
    "Hebrew": "heb",
    "Devanagari": "hin",
    "Thai": "tha",
}

# Tesseract language code -> EasyOCR language code (None = EasyOCR can't read it).
TESS_TO_EASY = {
    "eng": "en", "fra": "fr", "deu": "de", "spa": "es", "ita": "it", "por": "pt",
    "nld": "nl", "swe": "sv", "dan": "da", "nor": "no", "pol": "pl", "ces": "cs",
    "ron": "ro", "hun": "hu", "tur": "tr", "lat": "la", "cat": "ca", "fin": "fi",
    "rus": "ru", "ukr": "uk", "bul": "bg", "srp": "rs_cyrillic", "chi_sim": "ch_sim",
    "chi_tra": "ch_tra", "jpn": "ja", "kor": "ko", "ara": "ar", "fas": "fa", "hin": "hi",
    "tha": "th", "ell": None, "heb": None,
}


def check_tesseract() -> None:
    """Stop with a clear message if Tesseract can't be run, instead of failing every page."""
    try:
        subprocess.run([TESSERACT, "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            f"Cannot run Tesseract at '{TESSERACT}' ({exc}).\n"
            "Install it (see the setup guide for your system), or point to it: on Windows run\n"
            '  setx TESSERACT "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"\n'
            "with your real install path, then open a new PowerShell window.")


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _run_tesseract(img: Image.Image, args: list[str]) -> str:
    proc = subprocess.run(
        [TESSERACT, "stdin", "stdout", *args],
        input=_png_bytes(img), capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode("utf-8", errors="replace")


def tesseract_osd(img: Image.Image) -> tuple[int, str | None]:
    """Detect page rotation (degrees clockwise to fix) and script. (0, None) if undetectable."""
    small = img.copy()
    small.thumbnail((2000, 2000))
    try:
        out = _run_tesseract(small, ["--psm", "0", "--dpi", "300"])
    except RuntimeError:
        return 0, None  # too little text for OSD; not an error
    rotate = re.search(r"Rotate:\s*(\d+)", out)
    conf = re.search(r"Orientation confidence:\s*([\d.]+)", out)
    script = re.search(r"Script:\s*(\w+)", out)
    script_conf = re.search(r"Script confidence:\s*([\d.]+)", out)
    rot = int(rotate.group(1)) if rotate and conf and float(conf.group(1)) >= 2.0 else 0
    # Weak script guesses are noise; fall back to Latin (the language check runs afterwards anyway).
    sure = script and script_conf and float(script_conf.group(1)) >= 2.0
    return rot, script.group(1) if sure else None


def best_model_available(lang: str) -> bool:
    return all((TESSDATA_BEST / f"{part}.traineddata").exists() for part in lang.split("+"))


def tesseract_lines(img: Image.Image, lang: str, psm: int = 3, threshold: int = 2, best: bool = False) -> list[Line]:
    """threshold: 2 = Sauvola (copes with uneven phone lighting), 0 = Otsu.
    best: use the slower, more accurate models in TESSDATA_BEST if present."""
    extra = ["--tessdata-dir", str(TESSDATA_BEST)] if best and best_model_available(lang) else []
    tsv = _run_tesseract(img, [
        *extra, "-l", lang, "--psm", str(psm), "--dpi", "300",
        "-c", f"thresholding_method={threshold}",
        # Ask for TSV directly rather than via the "tsv" config file, which lives in the
        # system tessdata folder and isn't found when --tessdata-dir points elsewhere.
        "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0",
    ])
    lines: dict[tuple[int, int, int], Line] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] != "5" or not (row.get("text") or "").strip():
            continue
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, Line()).words.append(Word(row["text"], float(row["conf"]), (x, y, x + w, y + h)))
    # Drop specks and edge shadows far taller than text; they would glue rows together.
    heights = sorted(w.box[3] - w.box[1] for ln in lines.values() for w in ln.words)
    max_h = 2.5 * heights[len(heights) // 2] if heights else 0
    kept = []
    for line in lines.values():
        line.words = split_dashes([w for w in line.words if w.box[3] - w.box[1] <= max_h])
        if line.words:
            kept.append(line)
    return merge_rows(kept)


def tesseract_digits(img: Image.Image, box: tuple[int, int, int, int], cell: bool = False,
                     pad: int | None = None, gray: bool | None = None) -> list[Word]:
    """Numbers in one region (a column of days), in page coordinates. Read on their own because
    in a full-page read Tesseract often drops one or two digits standing apart from the text.
    cell: the region is one row's day, read as a single line with a white margin around it
    (Tesseract misses a lone digit cropped tight). pad, gray: the white margin and whether to
    read in grey, which by default go with cell."""
    x0, y0, _, _ = box
    pad = (CELL_PAD if cell else 0) if pad is None else pad
    crop = img.crop(box)
    if cell if gray is None else gray:
        crop = crop.convert("L")
    if pad:
        crop = ImageOps.expand(crop, pad, fill=255 if crop.mode == "L" else (255,) * len(crop.getbands()))
        x0, y0 = x0 - pad, y0 - pad
    tsv = _run_tesseract(crop, [
        "-l", "eng", "--psm", "7" if cell else "6", "--dpi", "300", "-c", "tessedit_char_whitelist=0123456789",
        "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0",
    ])
    words = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] == "5" and (text := (row.get("text") or "").strip()):
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            words.append(Word(text, float(row["conf"]), (x0 + x, y0 + y, x0 + x + w, y0 + y + h)))
    return words


def tesseract_line(img: Image.Image, box: tuple[int, int, int, int], lang: str, best: bool = False) -> Line:
    """One line of text read on its own, with a white margin around it, in page coordinates.
    A line next to handwriting can come out garbled in a full-page read and clean by itself."""
    extra = ["--tessdata-dir", str(TESSDATA_BEST)] if best and best_model_available(lang) else []
    crop = ImageOps.expand(img.crop(box).convert("L"), CELL_PAD, fill=255)
    tsv = _run_tesseract(crop, [
        *extra, "-l", lang, "--psm", "7", "--dpi", "300",
        "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0",
    ])
    x0, y0 = box[0] - CELL_PAD, box[1] - CELL_PAD
    words = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] == "5" and (text := (row.get("text") or "").strip()):
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            words.append(Word(text, float(row["conf"]), (x0 + x, y0 + y, x0 + x + w, y0 + y + h)))
    return Line(split_dashes(words))


@lru_cache(maxsize=4)
def _easy_reader(langs: tuple[str, ...]):
    import easyocr  # heavy import; only load when needed
    import torch

    # Use an NVIDIA GPU when present (much faster); PRX_GPU=0 forces CPU.
    gpu = torch.cuda.is_available() and os.environ.get("PRX_GPU", "1") != "0"
    return easyocr.Reader(
        list(langs), gpu=gpu, verbose=False,
        model_storage_directory=str(MODELS_DIR), download_enabled=False,
    )


def easy_langs_for(tess_lang: str) -> tuple[str, ...] | None:
    codes = []
    for t in tess_lang.split("+"):
        e = TESS_TO_EASY.get(t)
        if e is None:
            return None
        codes.append(e)
    if "en" not in codes:
        codes.append("en")  # every EasyOCR model can be paired with English
    return tuple(dict.fromkeys(codes))


def easyocr_lines(img: Image.Image, langs: tuple[str, ...], beam: bool = False) -> list[Line]:
    """beam: beam-search decoding (slower; better on small punctuation). Used for field crops."""
    with EASYOCR_LOCK:
        results = _easy_reader(langs).readtext(
            np.array(img), detail=1, paragraph=False,
            decoder="beamsearch" if beam else "greedy", beamWidth=5,
        )
    segments = []
    for pts, text, conf in results:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        segments.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), text, float(conf) * 100))
    return _group_segments(segments)


def _group_segments(segments) -> list[Line]:
    """Group EasyOCR phrase boxes into text lines by vertical overlap, then split into words."""
    rows: list[list] = []
    for seg in sorted(segments, key=lambda s: (s[1] + s[3]) / 2):
        cy, h = (seg[1] + seg[3]) / 2, seg[3] - seg[1]
        for row in rows:
            r_cy = sum((s[1] + s[3]) / 2 for s in row) / len(row)
            r_h = sum(s[3] - s[1] for s in row) / len(row)
            if abs(cy - r_cy) < 0.5 * min(h, r_h):
                row.append(seg)
                break
        else:
            rows.append([seg])
    lines = []
    for row in rows:
        words: list[Word] = []
        for x0, y0, x1, y1, text, conf in sorted(row, key=lambda s: s[0]):
            tokens = text.split()
            per_char = (x1 - x0) / max(len(text), 1)
            cursor = x0
            for tok in tokens:
                start = text.find(tok, int((cursor - x0) / per_char) if per_char else 0)
                wx0 = x0 + per_char * max(start, 0)
                words.append(Word(tok, conf, (int(wx0), y0, int(wx0 + per_char * len(tok)), y1)))
                cursor = wx0 + per_char * len(tok)
        if words:
            lines.append(Line(split_dashes(words)))
    lines.sort(key=lambda ln: ln.box[1])
    return lines


# --- Optional engines (python-doctr, transformers); models fetched once by `setup` -------

DOCTR_DIR = MODELS_DIR / "doctr"
TROCR_DIR = MODELS_DIR / "trocr-base-printed"
TROCR_REPO = "microsoft/trocr-base-printed"


def _torch_device():
    import torch

    return "cuda" if torch.cuda.is_available() and os.environ.get("PRX_GPU", "1") != "0" else "cpu"


@lru_cache(maxsize=1)
def doctr_available() -> bool:
    """True if python-doctr and its downloaded models are present. Otherwise warn once and
    let the vote run without it (two engines) rather than fail."""
    try:
        import doctr  # noqa: F401
    except ImportError:
        print("note: python-doctr not installed; voting with two engines (pip install python-doctr)", flush=True)
        return False
    if not any(DOCTR_DIR.rglob("*.pt")):
        print("note: docTR models not downloaded; voting with two engines (python -m extractor setup --doctr)",
              flush=True)
        return False
    return True


@lru_cache(maxsize=1)
def _doctr_predictor():
    os.environ["DOCTR_CACHE_DIR"] = str(DOCTR_DIR)  # weights load from here; no download at run time
    from doctr.models import ocr_predictor

    predictor = ocr_predictor(det_arch="db_resnet50", reco_arch="parseq", pretrained=True,
                              assume_straight_pages=True)
    return predictor.cuda() if _torch_device() == "cuda" else predictor


def doctr_lines(img: Image.Image) -> list[Line]:
    arr = np.array(img.convert("RGB"))
    with DOCTR_LOCK:
        page = _doctr_predictor()([arr]).pages[0]
    h, w = arr.shape[:2]
    lines = []
    for block in page.blocks:
        for line in block.lines:
            words = [Word(wd.value, float(wd.confidence) * 100,
                          (int(wd.geometry[0][0] * w), int(wd.geometry[0][1] * h),
                           int(wd.geometry[1][0] * w), int(wd.geometry[1][1] * h)))
                     for wd in line.words if wd.value.strip()]
            if words:
                lines.append(Line(split_dashes(words)))
    return merge_rows(lines)


@lru_cache(maxsize=1)
def _trocr():
    os.environ["HF_HUB_OFFLINE"] = "1"  # never contact the Hub at run time
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    if not TROCR_DIR.exists():
        raise FileNotFoundError(f"TrOCR model not installed in {TROCR_DIR} (run: python -m extractor setup --trocr)")
    processor = TrOCRProcessor.from_pretrained(TROCR_DIR, local_files_only=True)
    model = VisionEncoderDecoderModel.from_pretrained(TROCR_DIR, local_files_only=True).eval().to(_torch_device())
    return processor, model


def trocr_line(img: Image.Image) -> tuple[str, float]:
    """Read one text line. Returns (text, confidence 0-100 from the beam's sequence probability)."""
    import torch

    with TROCR_LOCK, torch.no_grad():
        processor, model = _trocr()
        pixels = processor(images=img.convert("RGB"), return_tensors="pt").pixel_values.to(model.device)
        out = model.generate(pixels, max_new_tokens=64, num_beams=4,
                             output_scores=True, return_dict_in_generate=True)
        text = processor.batch_decode(out.sequences, skip_special_tokens=True)[0].strip()
    scores = getattr(out, "sequences_scores", None)
    return text, float(torch.exp(scores[0])) * 100 if scores is not None else 100.0
