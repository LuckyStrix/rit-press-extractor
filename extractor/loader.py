"""Turn input files (phone photos, scans, PDFs) into RGB page images, in memory only."""
from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence
from pillow_heif import register_heif_opener

register_heif_opener()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp", ".bmp"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS
PDF_DPI = 300


def find_inputs(paths: list[Path]) -> list[Path]:
    """Expand directories into supported files, sorted for stable output order."""
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            found.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_EXTS))
        elif p.suffix.lower() in SUPPORTED_EXTS:
            found.append(p)
        else:
            raise ValueError(f"Unsupported file type: {p}")
    return found


def load_pages(path: Path) -> Iterator[tuple[int, Image.Image]]:
    """Yield (1-based page number, RGB image) for every page in the file."""
    if path.suffix.lower() in PDF_EXTS:
        with pymupdf.open(path) as doc:
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=PDF_DPI)
                yield i, Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        return
    with Image.open(path) as img:
        for i, frame in enumerate(ImageSequence.Iterator(img), start=1):
            # Phone photos store rotation in EXIF; apply it before anything else.
            yield i, ImageOps.exif_transpose(frame.copy()).convert("RGB")
