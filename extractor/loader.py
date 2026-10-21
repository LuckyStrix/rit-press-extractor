"""Turn input files (phone photos, scans, PDFs) into RGB page images, in memory only."""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps, ImageSequence
from pillow_heif import register_heif_opener

register_heif_opener()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp", ".bmp"}
PDF_EXTS = {".pdf"}
SUPPORTED_EXTS = IMAGE_EXTS | PDF_EXTS
PDF_DPI = 300


def natural_key(path: Path) -> list:
    """Sort key that reads digit runs as numbers, so release2 comes before release10."""
    return [[int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", part)] for part in path.parts]


def find_inputs(paths: list[Path]) -> list[Path]:
    """Expand directories into supported files, sorted for stable output order."""
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            found.extend(sorted((f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_EXTS), key=natural_key))
        elif p.suffix.lower() in SUPPORTED_EXTS:
            found.append(p)
        else:
            raise ValueError(f"Unsupported file type: {p}")
    return found


def page_count(path: Path) -> int:
    """How many pages load_pages yields, without rendering any."""
    if path.suffix.lower() in PDF_EXTS:
        pdf = pdfium.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()
    with Image.open(path) as img:
        return 1 if img.format == "MPO" else getattr(img, "n_frames", 1)


def load_pages(path: Path, only: int | None = None) -> Iterator[tuple[int, Image.Image]]:
    """Yield (1-based page number, RGB image) for every page in the file, one at a time (a
    scanner's PDF can hold a whole folder). With only, just that page of a PDF."""
    if path.suffix.lower() in PDF_EXTS:
        pdf = pdfium.PdfDocument(path)
        try:
            for i in [only - 1] if only else range(len(pdf)):
                yield i + 1, pdf[i].render(scale=PDF_DPI / 72).to_pil().convert("RGB")
        finally:
            pdf.close()
        return
    with Image.open(path) as img:
        if img.format == "MPO":  # extra frames are gain maps/depth data, not pages
            yield 1, ImageOps.exif_transpose(img.copy()).convert("RGB")
            return
        for i, frame in enumerate(ImageSequence.Iterator(img), start=1):
            # Phone photos store rotation in EXIF; apply it before anything else.
            yield i, ImageOps.exif_transpose(frame.copy()).convert("RGB")
