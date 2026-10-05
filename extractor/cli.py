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
    if args.tess_best:
        import urllib.request

        from .ocr import TESSDATA_BEST

        TESSDATA_BEST.mkdir(parents=True, exist_ok=True)
        for lang in args.tess_best:
            url = f"https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata"
            print(f"Fetching Tesseract best model '{lang}' ...")
            urllib.request.urlretrieve(url, TESSDATA_BEST / f"{lang}.traineddata")
    print(f"Models stored in {MODELS_DIR}. Processing now runs fully offline.")
    return 0


def _options(args):
    from .pipeline import Options

    return Options(reread=not args.no_reread, best_model=args.best_model, multipass=args.multipass)


def _init_worker(jobs: int) -> None:
    from . import netguard

    os.umask(0o077)
    netguard.enable()
    if jobs > 1:  # share the cores out instead of every worker grabbing all of them
        import torch

        os.environ["OMP_THREAD_LIMIT"] = "1"  # Tesseract
        torch.set_num_threads(max(1, (os.cpu_count() or 1) // jobs))


def _process_file(path: Path, lang, opts) -> list:
    """All rows for one input file (one per page, or one failure row)."""
    from .loader import load_pages
    from .pipeline import failed_row, process_page

    item = m.group(1) if (m := re.match(r"(\d+)", path.stem)) else ""
    try:
        pages = list(load_pages(path))
    except Exception as exc:  # unreadable/corrupt file: record it so nothing goes missing
        return [failed_row(path.name, item, f"could not open file: {exc}")]
    return [process_page(img, path.name, page_no, item, lang, opts) for page_no, img in pages]


def cmd_process(args) -> int:
    from .loader import find_inputs
    from .output import append_rows

    _init_worker(1)
    ensure_private_dir(DATA_DIR)
    out = Path(args.output)
    files = find_inputs([Path(p) for p in args.inputs])
    if not files:
        print("No supported files found.", file=sys.stderr)
        return 1
    opts = _options(args)
    if args.jobs > 1:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        # "spawn": safe with CUDA; each worker loads its own OCR models once.
        pool = ProcessPoolExecutor(args.jobs, mp.get_context("spawn"), _init_worker, (args.jobs,))
        results = pool.map(_process_file, files, [args.lang] * len(files), [opts] * len(files))
    else:
        pool, results = None, (_process_file(f, args.lang, opts) for f in files)
    flagged = 0
    try:
        for rows in results:  # in input order
            append_rows(out, rows)
            for row in rows:
                flagged += row.needs_review == "YES"
                mark = "REVIEW" if row.needs_review == "YES" else "ok"
                print(f"  [{mark:6}] {row.file} p{row.page}: {row.release_date or '-'} | {row.first_five_words or '-'}",
                      flush=True)
    finally:
        if pool:
            pool.shutdown(cancel_futures=True)
    print(f"Done. {flagged} item(s) need review. Results appended to {out}")
    return 0


def cmd_debug(args) -> int:
    from . import netguard

    netguard.enable()
    from .debug import dump

    for p in args.files:
        dump(Path(p), args.unmasked)
    return 0


def cmd_evaluate(args) -> int:
    from .evaluate import evaluate, make_template

    if args.template:
        return make_template(Path(args.results), Path(args.truth))
    return evaluate(Path(args.results), Path(args.truth), args.show)


def cmd_serve(args) -> int:
    from . import netguard

    netguard.enable()
    from .server import serve

    serve(args.port, ensure_private_dir(DATA_DIR), Path(args.output), _options(args))
    return 0


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)  # anything this program creates is private to the current user
    p = argparse.ArgumentParser(prog="python -m extractor", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="one-time download of EasyOCR models (needs internet)")
    s.add_argument("--langs", nargs="+", default=["fr"],
                   help="EasyOCR language codes to fetch; 'fr' pulls the shared Latin-script model")
    s.add_argument("--tess-best", nargs="*", metavar="LANG",
                   help="also fetch Tesseract 'best' models (default: eng) for --best-model")
    s.set_defaults(func=cmd_setup)

    def add_ocr_options(sp):
        g = sp.add_argument_group("OCR options")
        g.add_argument("--no-reread", action="store_true", help="skip the focused second read of each field")
        g.add_argument("--best-model", action="store_true", help="use Tesseract 'best' models (slower, more accurate)")
        g.add_argument("--multipass", action="store_true",
                       help="read each field with 3 differently cleaned Tesseract passes and take the majority")

    s = sub.add_parser("process", help="read photos/PDFs and append rows to a CSV (offline)")
    s.add_argument("inputs", nargs="+", help="files or folders")
    s.add_argument("-o", "--output", default=str(DEFAULT_CSV))
    s.add_argument("--lang", help="force a Tesseract language, e.g. 'fra' or 'eng+deu'")
    s.add_argument("-j", "--jobs", type=int, default=1, help="photos to process in parallel (each needs ~1.5 GB RAM)")
    add_ocr_options(s)
    s.set_defaults(func=cmd_process)

    s = sub.add_parser("evaluate", help="score a results CSV against a hand-made answer key")
    s.add_argument("results")
    s.add_argument("truth")
    s.add_argument("--template", action="store_true", help="create a blank answer key listing the results' files")
    s.add_argument("--show", action="store_true", help="print the wrong values (for your eyes only)")
    s.set_defaults(func=cmd_evaluate)

    s = sub.add_parser("debug", help="print OCR line layout with letters masked (safe to share)")
    s.add_argument("files", nargs="+")
    s.add_argument("--unmasked", action="store_true", help="show real text (for your eyes only)")
    s.set_defaults(func=cmd_debug)

    s = sub.add_parser("serve", help="phone capture page on localhost (expose with tailscale serve)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("-o", "--output", default=str(DEFAULT_CSV))
    add_ocr_options(s)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    if args.cmd == "setup" and args.tess_best == []:
        args.tess_best = ["eng"]
    return args.func(args)
