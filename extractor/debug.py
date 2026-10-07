"""Print a page's OCR line layout with letters masked, so layout can be shared without content."""
from __future__ import annotations

import re
from pathlib import Path

from . import ocr
from .dates import parse_dates_in_line
from .layout import find_body_start
from .loader import load_pages
from .preprocess import flatten_page, normalize_size


def mask(text: str) -> str:
    out = re.sub(r"[^\W\d_]", lambda m: "X" if m.group(0).isupper() else "x", text)
    return re.sub(r"\d", "9", out)


def dump(path: Path, unmasked: bool = False) -> None:
    for page_no, img in load_pages(path):
        flat, found = flatten_page(img)
        rotate = 0  # rotation detection is off: captures are always upright
        page = normalize_size(flat)
        lines = ocr.tesseract_lines(page, "eng")
        start = find_body_start(lines)
        print(f"== {path.name} p{page_no}: page outline {'found' if found else 'NOT found'}, "
              f"rotated {rotate}, {len(lines)} lines, body start "
              f"{(start.line, start.word, start.flags) if start else None}")
        print("  #   x%   y%  gap  words lower conf  text")
        prev_bottom = None
        for i, ln in enumerate(lines):
            x0, y0, _, y1 = ln.box
            gap = "" if prev_bottom is None else f"{(y0 - prev_bottom) / max(y1 - y0, 1):.1f}"
            prev_bottom = y1
            toks = [w.text for w in ln.words]
            lower = sum(1 for t in toks if t[:1].islower())
            conf = min(w.conf for w in ln.words)
            marks = ""
            if start and i == start.line:
                marks += f" <== BODY STARTS at word {start.word}"
            if parse_dates_in_line(ln, i):
                marks += " [DATE]"
            text = ln.text if unmasked else mask(ln.text)
            print(f"{i:3} {100 * x0 / page.width:4.0f} {100 * y0 / page.height:4.0f} {gap:>4} {len(toks):5} {lower:5} "
                  f"{conf:4.0f}  {text}{marks}")
