"""A third reader: PP-OCRv5's Latin text-line recognizer, reading the lines Tesseract found.

EasyOCR and docTR can share Tesseract's mistakes on typewritten text (both read "alumi" where
the list says "Alumni"). PP-OCRv5 is trained differently and reads each line on its own, so its
agreement is a more independent check. It only recognizes: the lines come from Tesseract's
boxes, so its words line up with Tesseract's.

The model is PaddlePaddle's latin_PP-OCRv5_mobile_rec (Apache-2.0; English, French and other
Latin-script languages), run from its official ONNX export with onnxruntime on the CPU. It is
fetched once by `setup --ppocr`.
"""
from __future__ import annotations

import math
import os
from functools import lru_cache

import numpy as np
from PIL import Image

from .models import Box, Line, Word, split_dashes
from .ocr import MODELS_DIR

PPOCR_DIR = MODELS_DIR / "ppocr"
PPOCR_REPO = "PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx"
PPOCR_REVISION = "89d3a50e2c27e2e7cceeab0e944c25c807d5db4f"
MODEL_FILE = PPOCR_DIR / "inference.onnx"
HEIGHT = 48  # the model reads a line scaled to this height
PAD = (0.5, 0.2)  # margin kept around Tesseract's words, in line heights (x, y), so no letter is clipped
COLUMN_GAP = 2.0  # a gap between words wider than this many line heights separates two columns
LATIN = {"eng", "fra", "deu", "spa", "ita", "por", "nld", "lat"}  # Tesseract languages it can read
threads = 0  # onnxruntime threads; 0 lets it use every core (set lower when pages run in parallel)


@lru_cache(maxsize=1)
def ppocr_available() -> bool:
    """True if onnxruntime and the model are present. Otherwise warn once and vote without it."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        print("note: onnxruntime not installed; voting without PP-OCR (pip install onnxruntime)", flush=True)
        return False
    if not MODEL_FILE.exists():
        print("note: PP-OCR model not downloaded; voting without it (python -m extractor setup --ppocr)",
              flush=True)
        return False
    return True


@lru_cache(maxsize=1)
def _model():
    import onnxruntime as ort
    import yaml

    cfg = yaml.safe_load((PPOCR_DIR / "inference.yml").read_text(encoding="utf-8"))
    # CTC: class 0 is "no character", then the model's dictionary, then a space.
    chars = ["", *(str(c) for c in cfg["PostProcess"]["character_dict"]), " "]
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    return ort.InferenceSession(str(MODEL_FILE), opts, providers=["CPUExecutionProvider"]), chars


def read_line(img: Image.Image) -> list[tuple[str, float, int, int]]:
    """One text line image as words: (text, confidence 0-100, x0, x1) in the image's pixels."""
    import cv2  # the resize must match the one the model was trained with (OpenCV, bilinear)

    session, chars = _model()
    bgr = np.asarray(img.convert("RGB"))[:, :, ::-1]
    h, w = bgr.shape[:2]
    width = max(HEIGHT // 3, math.ceil(HEIGHT * w / h))
    x = cv2.resize(bgr, (width, HEIGHT), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    x = ((x / 255 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    probs = session.run(None, {session.get_inputs()[0].name: x})[0][0]  # time steps x classes
    best, prob = probs.argmax(1), probs.max(1)
    step = w / len(best)  # image pixels per time step
    words, current, prev = [], [], 0
    for t, (c, p) in enumerate(zip(best, prob)):
        if c != prev and c != 0:
            if chars[c] == " ":
                if current:
                    words.append(current)
                current = []
            else:
                current.append((chars[c], float(p), t))
        prev = c
    if current:
        words.append(current)
    return [("".join(ch for ch, _, _ in wd), 100 * min(p for _, p, _ in wd),
             round(wd[0][2] * step), round((wd[-1][2] + 1) * step)) for wd in words]


def ppocr_lines(page: Image.Image, lines: list[Line]) -> list[Line]:
    """Tesseract's lines as PP-OCR reads them (a line it reads nothing on is left out)."""
    out = []
    for ln in (ln for ln in lines if ln.words):
        words, h = [], _letter_height(ln)
        for x0, y0, x1, y1 in _stretches(ln):
            left, top = max(0, round(x0 - PAD[0] * h)), max(0, round(y0 - PAD[1] * h))
            crop = page.crop((left, top, min(page.width, round(x1 + PAD[0] * h)), min(page.height, round(y1 + PAD[1] * h))))
            words += [Word(text, conf, (left + a, y0, left + b, y1)) for text, conf, a, b in read_line(crop)]
        if words:
            out.append(Line(split_dashes(words)))
    return out


def _letter_height(line: Line) -> int:
    """The line's typical word height; its box is taller where the page is tilted."""
    return sorted(w.box[3] - w.box[1] for w in line.words)[len(line.words) // 2]


def _stretches(line: Line) -> list[Box]:
    """The line's runs of text, split where a wide gap separates two columns ("October 9, 1969"
    on the left, a phone number on the right): read as one, the model runs them together. Each
    run keeps its own top and bottom, as a tilted page's line climbs from one column to the next."""
    height = _letter_height(line)
    runs = [[line.words[0]]]
    for w in line.words[1:]:
        if w.box[0] - max(v.box[2] for v in runs[-1]) > COLUMN_GAP * height:
            runs.append([w])
        else:
            runs[-1].append(w)
    return [Line(run).box for run in runs]


def download() -> None:
    """Fetch the model (setup --ppocr): the only time this module uses the network."""
    os.environ["HF_HUB_DISABLE_XET"] = "1"  # the xet backend can fail on its own cache permissions
    from huggingface_hub import constants, hf_hub_download

    constants.HF_HUB_DISABLE_XET = True  # also when huggingface_hub was imported before the line above
    for name in ("inference.onnx", "inference.yml", "README.md"):
        hf_hub_download(PPOCR_REPO, name, revision=PPOCR_REVISION, local_dir=str(PPOCR_DIR))
