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
