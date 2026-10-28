"""Page layout from a document layout model: where the letterhead, the release and contact
blocks, and each paragraph are, whatever the release's layout.

The model is PaddlePaddle's PP-DocLayout_plus-L (Apache-2.0), run from its official ONNX
export with onnxruntime on the CPU. Its weights are fetched once by `setup --layout`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from .models import Box
from .ocr import MODELS_DIR

LAYOUT_DIR = MODELS_DIR / "layout"
LAYOUT_REPO = "PaddlePaddle/PP-DocLayout_plus-L_onnx"
LAYOUT_REVISION = "feb74619326f634e0e883218598096a3733ad9f7"
MODEL_FILE = LAYOUT_DIR / "inference.onnx"
INPUT_SIZE = 800  # the model reads the page squeezed to 800 x 800
MIN_SCORE = 0.5
# The model's classes, in the order of its output (label_list in the model's inference.yml).
LABELS = ["paragraph_title", "image", "text", "number", "abstract", "content", "figure_title", "formula",
          "table", "reference", "doc_title", "footnote", "header", "algorithm", "footer", "seal", "chart",
          "formula_number", "aside_text", "reference_content"]
threads = 0  # onnxruntime threads; 0 lets it use every core (set lower when pages run in parallel)


@dataclass
class Region:
    label: str
    score: float
    box: Box


@lru_cache(maxsize=1)
def layout_available() -> bool:
    """True if onnxruntime and the layout model are present. Otherwise warn once and let the
    article be found from the lines alone."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        print("note: onnxruntime not installed; finding the article from the lines alone "
              "(pip install onnxruntime)", flush=True)
        return False
    if not MODEL_FILE.exists():
        print("note: layout model not downloaded; finding the article from the lines alone "
              "(python -m extractor setup --layout)", flush=True)
        return False
    return True


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    return ort.InferenceSession(str(MODEL_FILE), opts, providers=["CPUExecutionProvider"])


def find_regions(img: Image.Image) -> list[Region]:
    """The page's blocks the model is reasonably sure of, in page coordinates."""
    import cv2  # the resize must match the one the model was trained with (OpenCV, bicubic)

    w, h = img.size
    x = cv2.resize(np.asarray(img.convert("RGB")), (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_CUBIC)
    x = (x.astype(np.float32) / 255).transpose(2, 0, 1)[None]
    out = _session().run(None, {"image": x, "im_shape": np.array([[INPUT_SIZE, INPUT_SIZE]], np.float32),
                                "scale_factor": np.array([[INPUT_SIZE / h, INPUT_SIZE / w]], np.float32)})[0]
    return [Region(LABELS[int(c)], float(s), (round(x0), round(y0), round(x1), round(y1)))
            for c, s, x0, y0, x1, y1 in out if s >= MIN_SCORE and 0 <= int(c) < len(LABELS)]


def download() -> None:
    """Fetch the model (setup --layout): the only time this module uses the network."""
    os.environ["HF_HUB_DISABLE_XET"] = "1"  # the xet backend can fail on its own cache permissions
    from huggingface_hub import constants, hf_hub_download

    constants.HF_HUB_DISABLE_XET = True  # also when huggingface_hub was imported before the line above
    for name in ("inference.onnx", "inference.yml", "README.md"):
        hf_hub_download(LAYOUT_REPO, name, revision=LAYOUT_REVISION, local_dir=str(LAYOUT_DIR))
