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


def dump_list(path: Path, pages: list[int]) -> None:
    """How each list page is read, step by step, with real text: the Tesseract build, the lines,
    the day column and the days read in it, and the dated entries. For comparing machines."""
    import subprocess

    from .listpage import day_column, has_month_line, header_band, missing_day_cells, parse_list_pages, with_days
    from .pipeline import Options, analyze_page

    version = subprocess.run([ocr.TESSERACT, "--version"], capture_output=True, text=True)
    print(f"tesseract: {ocr.TESSERACT}\n{(version.stdout or version.stderr).strip()}\n")
    found = []
    for page_no in pages:
        _, img = next(load_pages(path, page_no))
        page = normalize_size(flatten_page(img)[0])
        lines = ocr.tesseract_lines(page, "eng")
        print(f"== {path.name} p{page_no}: {page.width}x{page.height}, {len(lines)} lines, "
              f"month line read: {has_month_line(lines)}, header band: {header_band(lines)}")
        for i, ln in enumerate(lines):
            print(f"  {i:3} x{ln.box[0]:5} y{ln.box[1]:5}  {ln.text}")
        box = day_column(lines)
        print(f"  day column: {box}")
        if box:
            days = ocr.tesseract_digits(page, box)
            print("  days read: " + " ".join(f"{w.text}@y{w.box[1]}" for w in days))
            print(f"  cells re-read: {missing_day_cells(with_days(lines, days), box)}")
        result = analyze_page(img, path.name, page_no, opts=Options(engines=("tesseract",)), detect_list=True)
        if result.list_lines is None:
            print("  NOT read as a list page")
            continue
        print("  list lines as used:")
        for ln in result.list_lines:
            print(f"      x{ln.box[0]:5} y{ln.box[1]:5}  {ln.text}")
        found.append(result.list_lines)
    print("\nentries:")
    for e in parse_list_pages(found).entries:
        print(f"  {e.date} | printed {e.printed!r} | {e.subject} | {' | '.join(e.flags)}")
