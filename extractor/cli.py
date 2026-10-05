"""Command line: setup (one-time model download), process (files -> CSV), serve (phone capture)."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
DEFAULT_CSV = DATA_DIR / "results.csv"


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def cmd_setup(args) -> int:
    # The only command that is allowed to use the network: fetch EasyOCR model files once.
    import easyocr

    from .ocr import MODELS_DIR

    MODELS_DIR.mkdir(exist_ok=True)
    groups = [["en"]] + [[lang, "en"] for lang in args.langs if lang != "en"]
    for langs in groups:
        print(f"Fetching EasyOCR models for {langs} ...")
        easyocr.Reader(langs, gpu=False, model_storage_directory=str(MODELS_DIR), verbose=False)
    print(f"Models stored in {MODELS_DIR}. Processing now runs fully offline.")
    return 0


def cmd_process(args) -> int:
    from . import netguard

    netguard.enable()
    from .loader import find_inputs, load_pages
    from .output import append_rows
    from .pipeline import failed_row, process_page

    ensure_private_dir(DATA_DIR)
    out = Path(args.output)
    files = find_inputs([Path(p) for p in args.inputs])
    if not files:
        print("No supported files found.", file=sys.stderr)
        return 1
    flagged = 0
    for path in files:
        item = m.group(1) if (m := re.match(r"(\d+)", path.stem)) else ""
        try:
            pages = list(load_pages(path))
        except Exception as exc:  # unreadable/corrupt file: record it so nothing goes missing
            print(f"  [REVIEW] {path.name}: could not open ({exc})", file=sys.stderr)
            append_rows(out, [failed_row(path.name, item, f"could not open file: {exc}")])
            flagged += 1
            continue
        for page_no, img in pages:
            row = process_page(img, path.name, page_no, item, args.lang)
            append_rows(out, [row])
            flagged += row.needs_review == "YES"
            mark = "REVIEW" if row.needs_review == "YES" else "ok"
            print(f"  [{mark:6}] {path.name} p{page_no}: {row.release_date or '-'} | {row.first_five_words or '-'}")
    print(f"Done. {flagged} item(s) need review. Results appended to {out}")
    return 0


def cmd_debug(args) -> int:
    from . import netguard

    netguard.enable()
    from .debug import dump

    for p in args.files:
        dump(Path(p), args.unmasked)
    return 0


def cmd_serve(args) -> int:
    from . import netguard

    netguard.enable()
    from .server import serve

    serve(args.port, ensure_private_dir(DATA_DIR), Path(args.output))
    return 0


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)  # anything this program creates is private to the current user
    p = argparse.ArgumentParser(prog="python -m extractor", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="one-time download of EasyOCR models (needs internet)")
    s.add_argument("--langs", nargs="+", default=["fr"],
                   help="EasyOCR language codes to fetch; 'fr' pulls the shared Latin-script model")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("process", help="read photos/PDFs and append rows to a CSV (offline)")
    s.add_argument("inputs", nargs="+", help="files or folders")
    s.add_argument("-o", "--output", default=str(DEFAULT_CSV))
    s.add_argument("--lang", help="force a Tesseract language, e.g. 'fra' or 'eng+deu'")
    s.set_defaults(func=cmd_process)

    s = sub.add_parser("debug", help="print OCR line layout with letters masked (safe to share)")
    s.add_argument("files", nargs="+")
    s.add_argument("--unmasked", action="store_true", help="show real text (for your eyes only)")
    s.set_defaults(func=cmd_debug)

    s = sub.add_parser("serve", help="phone capture page on localhost (expose with tailscale serve)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("-o", "--output", default=str(DEFAULT_CSV))
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)
