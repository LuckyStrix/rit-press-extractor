"""Local OCR engines. Images are piped in memory; nothing is written to disk."""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .models import Line, Word, merge_rows, split_dashes

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
TESSDATA_BEST = MODELS_DIR / "tessdata_best"  # optional, filled by `setup --tess-best`
# Tesseract binary: $TESSERACT, else PATH, else the Windows installer's default location.
TESSERACT = (os.environ.get("TESSERACT") or shutil.which("tesseract")
             or r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# Harmless PyTorch notices from EasyOCR on a CPU-only machine; they don't affect results.
warnings.filterwarnings("ignore", message=r".*pin_memory.*no accelerator", category=UserWarning)
warnings.filterwarnings("ignore", message=r".*quantize_per_tensor.*deprecated", category=UserWarning)

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
