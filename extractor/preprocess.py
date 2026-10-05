"""Clean up phone photos so the OCR engines see a flat, upright page."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

MIN_PAGE_AREA = 0.25  # page outline must cover this fraction of the photo
TARGET_WIDTH = 2550  # ~300 dpi across a US-letter page


def _order_corners(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype="float32")


def find_page_quad(gray: np.ndarray) -> np.ndarray | None:
    """Return the 4 corners of the page if a clear outline is visible, else None."""
    scale = 1000 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    scale = min(scale, 1.0)
    edges = cv2.Canny(cv2.GaussianBlur(small, (5, 5), 0), 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_area = MIN_PAGE_AREA * small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(c) < min_area:
            break
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return _order_corners(approx.reshape(4, 2) / scale)
    return None


def flatten_page(img: Image.Image) -> tuple[Image.Image, bool]:
    """Perspective-correct to the page outline. Returns (image, whether a page was found)."""
    rgb = np.array(img)
    quad = find_page_quad(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    if quad is None:
        return img, False
    tl, tr, br, bl = quad
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    warped = cv2.warpPerspective(rgb, cv2.getPerspectiveTransform(quad, dst), (w, h))
    return Image.fromarray(warped), True


def normalize_size(img: Image.Image) -> Image.Image:
    """Upscale small captures so text has enough pixels; never downscale."""
    if img.width >= TARGET_WIDTH:
        return img
    factor = TARGET_WIDTH / img.width
    return img.resize((TARGET_WIDTH, int(img.height * factor)), Image.LANCZOS)


def deskew(img: Image.Image, max_angle: float = 5.0) -> tuple[Image.Image, float]:
    """Straighten small tilts: pick the angle whose horizontal ink profile is sharpest
    (text rows line up). Returns (image, degrees rotated)."""
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    scale = 1000 / gray.shape[1]
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    h, w = ink.shape

    def score(angle: float) -> float:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rows = cv2.warpAffine(ink, m, (w, h)).sum(axis=1, dtype=np.float64)
        return float(np.var(rows))

    coarse = max(np.arange(-max_angle, max_angle + 0.01, 0.25), key=score)
    best = max(np.arange(coarse - 0.25, coarse + 0.26, 0.05), key=score)
    if abs(best) < 0.1:
        return img, 0.0
    rgb = np.array(img)
    m = cv2.getRotationMatrix2D((rgb.shape[1] / 2, rgb.shape[0] / 2), best, 1.0)
    out = cv2.warpAffine(rgb, m, (rgb.shape[1], rgb.shape[0]), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(out), float(best)


def clean_page(img: Image.Image) -> Image.Image:
    """Remove uneven phone lighting (divide by the blurred paper background) and lightly
    denoise. Returns a grayscale page as RGB, so both engines can take it."""
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    background = cv2.resize(cv2.medianBlur(small, 21), (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    flat = cv2.divide(gray, np.maximum(background, 1), scale=255)
    flat = cv2.fastNlMeansDenoising(flat, None, h=7, templateWindowSize=7, searchWindowSize=21)
    return Image.fromarray(cv2.cvtColor(flat, cv2.COLOR_GRAY2RGB))
