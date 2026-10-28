"""Command line: setup (one-time model download), process (files -> CSV), gui (a window for process), serve (phone capture)."""
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
    if args.doctr:
        os.environ["DOCTR_CACHE_DIR"] = str(MODELS_DIR / "doctr")
        from doctr.models import ocr_predictor

        print("Fetching docTR models (db_resnet50 + parseq) ...")
        ocr_predictor(det_arch="db_resnet50", reco_arch="parseq", pretrained=True)
    if args.trocr:
        from huggingface_hub import snapshot_download

        from .ocr import TROCR_DIR, TROCR_REPO

        print(f"Fetching TrOCR model {TROCR_REPO} ...")
        os.environ["HF_HUB_DISABLE_XET"] = "1"  # the xet backend can fail on its own cache permissions
        snapshot_download(TROCR_REPO, local_dir=str(TROCR_DIR), allow_patterns=["*.json", "*.txt", "model.safetensors"])
        if not (TROCR_DIR / "model.safetensors").exists():
            raise SystemExit("TrOCR weights did not download; re-run setup --trocr")
    if args.layout:
        from .regions import LAYOUT_REPO, MODEL_FILE, download

        print(f"Fetching layout model {LAYOUT_REPO} ...")
        download()
        if not MODEL_FILE.exists():
            raise SystemExit("The layout model did not download; re-run setup --layout")
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

    return Options(reread=args.reread, best_model=args.best_model, multipass=args.multipass, clean=args.clean,
                   engines=tuple(e.strip() for e in args.engines.split(",")), layout=args.layout)


def _init_worker(jobs: int) -> None:
    from . import netguard

    os.umask(0o077)
    netguard.enable()
    if jobs > 1:  # share the cores out instead of every worker grabbing all of them
        import torch

        from . import regions

        os.environ["OMP_THREAD_LIMIT"] = "1"  # Tesseract
        torch.set_num_threads(max(1, (os.cpu_count() or 1) // jobs))
        regions.threads = max(1, (os.cpu_count() or 1) // jobs)


def _threads_suffice(opts) -> bool:
    """Can parallel pages share one process? Yes when the neural engines run on a GPU (or not at
    all): then they are a small share of the work and the rest runs outside Python's lock. On a
    CPU they are most of the work, so each worker needs a process (and a copy of the models)."""
    from . import ocr

    if not {"easyocr", "doctr", "trocr"} & set(opts.engines):
        return True
    return ocr._torch_device() == "cuda"


def _work_units(files: list[Path]) -> list[tuple[Path, int | None]]:
    """What one worker reads at a time: a photo, or one page of a PDF (a scanner's PDF can hold
    a whole folder, which then still spreads over the workers and shows its progress)."""
    from .loader import PDF_EXTS, page_count

    units: list[tuple[Path, int | None]] = []
    for f in files:
        try:
            n = page_count(f) if f.suffix.lower() in PDF_EXTS else 0
        except Exception:  # unreadable: read whole, so the failure is recorded like any other
            n = 0
        units += [(f, p) for p in range(1, n + 1)] if n else [(f, None)]
    return units


def _process_file(path: Path, lang, opts, only: int | None = None) -> list:
    """Every page of one input file (or just page `only` of a PDF) as a PageResult (one per page,
    or a failure result). Pages are rendered one at a time, so a long PDF needs no more memory."""
    from .loader import load_pages
    from .pages import PageSignals
    from .pipeline import PageResult, analyze_page, failed_row

    item = m.group(1) if (m := re.match(r"(\d+)", path.stem)) else ""

    def failed(page_no: int, reason: str):
        row = failed_row(path.name, item, reason)
        row.page = page_no
        return page_no, PageResult(row, PageSignals(starts=True))  # a failed page stands alone

    results = []
    pages = load_pages(path, only)
    while True:
        try:
            page_no, img = next(pages)
        except StopIteration:
            break
        except Exception as exc:  # unreadable/corrupt file or page: record it so nothing goes missing
            page_no = only or len(results) + 1
            results.append(failed(page_no, f"could not {'read page' if results else 'open file'}: {exc}"))
            break
        try:
            results.append((page_no, analyze_page(img, path.name, page_no, item, lang, opts)))
        except Exception as exc:  # one bad page must not stop the batch; record it for review
            results.append(failed(page_no, f"processing failed: {type(exc).__name__}: {exc}"))
    return results


def _finish_folder(folder_path: Path, pages: list, out: Path, naming_args=None) -> int:
    """Group a folder's pages into releases, attach list-page subjects, and replace the
    per-page rows written while it ran. Returns how many releases need review."""
    from .folder import assemble_folder
    from .output import merge_rows, write_unmatched

    name = folder_path.name
    result = assemble_folder(name, pages)
    pdfs = {}
    naming = _naming_for(folder_path, naming_args)
    if naming:
        from .catalog import apply_names

        pdfs = apply_names(result, naming)
    if getattr(naming_args, "template", None):  # only the metadata spreadsheet uses it
        from .metadata import digitized_date

        dates: dict[str, str] = {}  # one PDF can hold many releases; read its date once
        for row, pages in zip(result.rows, result.release_pages):
            file = pages[0][0]
            if file not in dates:
                dates[file] = digitized_date(folder_path / file)
            row.digitized = dates[file]
    merge_rows(out, result.rows, result.consumed, name)
    unmatched_path = out.with_name(out.stem + "_unmatched_subjects.csv")
    write_unmatched(unmatched_path, name, result.unmatched)
    flagged = 0
    for row in result.rows:
        flagged += row.needs_review == "YES"
        mark = "REVIEW" if row.needs_review == "YES" else "ok"
        span = f"p{row.page}" if row.page_count == 1 else f"{row.page_count} pages from p{row.page}"
        subject = f" | {row.subject}" if row.subject else ""
        print(f"  [{mark:6}] {row.file} {span}: {row.release_date or '-'} | {row.first_five_words or '-'}{subject}",
              flush=True)
    if pdfs and naming_args.pdfs:
        from .catalog import write_pdfs

        try:
            messages = write_pdfs(folder_path, pdfs, Path(naming_args.pdfs), naming_args.force_pdfs, naming)
        except OSError as exc:  # the CSV is already saved; say so and go on to the next folder
            messages = [f"FAILED, no PDFs written for {name}: {exc}"]
        for message in messages:
            print(f"  named {message}", flush=True)
    elif not naming and naming_args is not None and (naming_args.pdfs or naming_args.box or naming_args.folder):
        print(f"  {name}: no box/folder number, so the releases are not numbered or named "
              "(pass --box and --folder, or name the folder like 'Box 12/Folder 3')", flush=True)
    s = result.summary
    if s["list_pages"]:
        print(f"  {name}: {s['list_pages']} list page(s), {s['entries']} entries; {s['releases']} releases: "
              f"{s['matched']} with a subject, {s['ambiguous']} undecided, {s['no_subject']} without; "
              f"{s['unmatched_entries']} entries matched no release"
              + (f" (see {unmatched_path.name})" if s["unmatched_entries"] else ""), flush=True)
    return flagged


def _naming_for(folder_path: Path, args):
    """The box/folder/release naming for one input folder: typed values win over the folder's own name."""
    from .catalog import LIST_TEMPLATE, RELEASE_TEMPLATE, Naming, infer_box_folder

    if args is None:
        return None
    box, folder_no = infer_box_folder(folder_path)
    box, folder_no = args.box or box, args.folder or folder_no
    if not (box and folder_no):
        return None
    local = getattr(args, "template", None)  # typed templates win over the metadata template's
    return Naming(box, folder_no, args.first_release,
                  args.name_template or (local and local.name_template) or RELEASE_TEMPLATE,
                  args.list_name_template or (local and local.list_name_template) or LIST_TEMPLATE)


def _template(args):
    """The metadata template: --metadata-template FILE, none for --metadata-template "", else the default one."""
    from .metadata import load_template

    if args.metadata_template == "":
        return None
    return load_template(Path(args.metadata_template) if args.metadata_template else None)


def _xlsx_path(args, out: Path) -> Path:
    """Where the metadata spreadsheet goes; never onto the results CSV."""
    xlsx = Path(args.xlsx) if args.xlsx else out.with_suffix(".xlsx")
    if xlsx.suffix.lower() != ".xlsx":
        raise ValueError(f"The metadata spreadsheet must be an .xlsx file (got {xlsx}).")
    if xlsx.resolve() == out.resolve():
        raise ValueError("The metadata spreadsheet and the results CSV must be different files.")
    return xlsx


def _write_xlsx(out: Path, template, xlsx: Path) -> None:
    from .metadata import write_xlsx

    try:
        count = write_xlsx(out, template, xlsx)
    except ValueError as exc:  # a results CSV it cannot use, e.g. re-saved in another format
        print(f"FAILED to write {xlsx}: {exc}", flush=True)
        return
    except OSError as exc:  # e.g. the workbook is open in Excel; the CSV is saved either way
        print(f"FAILED to write {xlsx} ({exc}); close it if it is open, then run: "
              f"python -m extractor xlsx \"{out}\"", flush=True)
        return
    print(f"Metadata spreadsheet: {count} release(s) in {xlsx}"
          + ("" if count else " (no release has a file name: give a box and folder number)"), flush=True)


def cmd_process(args) -> int:
    from dataclasses import replace

    from .folder import PageIn
    from .loader import find_inputs
    from .output import append_rows

    from . import ocr

    ocr.check_tesseract()
    _init_worker(1)
    ensure_private_dir(DATA_DIR)
    out = Path(args.output)
    files = find_inputs([Path(p) for p in args.inputs])
    if not files:
        print("No supported files found.", file=sys.stderr)
        return 1
    opts = _options(args)
    try:
        args.template = _template(args)
        if args.xlsx and not args.template:
            raise ValueError("--xlsx needs a metadata template: put one at local/metadata_template.json "
                             "or pass --metadata-template (see docs/using.md).")
        if args.template:
            _xlsx_path(args, out)  # a bad spreadsheet path stops the run before the long part
        labels: dict[tuple[str, str], Path] = {}
        unlabelled = []
        for d in sorted({f.parent for f in files}):
            naming = _naming_for(d, args)  # a bad box, folder or template stops the run before the long part
            if not naming:
                unlabelled.append(d)
                continue
            key = (naming.box.lower(), naming.folder.lower())  # file names may ignore case
            if key in labels:
                raise ValueError(f"{labels[key]} and {d} are both Box {key[0]} Folder {key[1]}, so their "
                                 "releases would get the same names. Run them separately.")
            labels[key] = d
        if labels and unlabelled:
            print("These folders have no box/folder number, so their releases will not be numbered or named: "
                  + ", ".join(str(d) for d in unlabelled), file=sys.stderr, flush=True)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.first_release != 1 and len({f.parent for f in files}) > 1:
        print("--first-release continues one folder's numbering, but the inputs span several folders. "
              "Run them separately.", file=sys.stderr)
        return 2
    if (args.box or args.folder) and len({f.parent for f in files}) > 1:
        print("--box/--folder name one physical folder, but the inputs span several folders. "
              "Run them separately, or name the folders like 'Box 12/Folder 3'.", file=sys.stderr)
        return 2
    pool = None
    if args.jobs > 1 and _threads_suffice(opts):
        from concurrent.futures import ThreadPoolExecutor

        # One copy of the models (on the GPU) shared by threads; Tesseract runs as separate
        # programs, so the pages are still read side by side.
        os.environ["OMP_THREAD_LIMIT"] = "1"  # Tesseract
        pool = ThreadPoolExecutor(args.jobs)
        print(f"Reading {args.jobs} pages at a time in one process (the OCR models are loaded once).", flush=True)
    elif args.jobs > 1:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        # "spawn": safe with CUDA; each worker loads its own OCR models once.
        pool = ProcessPoolExecutor(args.jobs, mp.get_context("spawn"), _init_worker, (args.jobs,))
    units = _work_units(files)
    if args.jobs > 1:
        results = pool.map(_process_file, [u[0] for u in units], [args.lang] * len(units), [opts] * len(units),
                           [u[1] for u in units])
    else:
        pool, results = None, (_process_file(f, args.lang, opts, p) for f, p in units)
    flagged = 0
    folders: dict[Path, list] = {}
    last_unit = {u[0].parent: i for i, u in enumerate(units)}  # a folder is finished after its last unit
    try:
        for i, ((path, _), path_results) in enumerate(zip(units, results)):  # in input order
            pages = folders.setdefault(path.parent, [])
            for page_no, res in path_results:
                pages.append(PageIn(path.name, page_no, res.row.item_number if res.row else "", res))
                if res.row is not None:  # saved at once; the folder pass replaces it when the folder is done
                    append_rows(out, [replace(res.row, folder=path.parent.name)])
                    print(f"  read {path.name} p{page_no}", flush=True)
                else:
                    print(f"  read {path.name} p{page_no} (list page)", flush=True)
            if last_unit[path.parent] == i:
                flagged += _finish_folder(path.parent, folders.pop(path.parent), out, args)
    finally:
        if pool:
            pool.shutdown(cancel_futures=True)
    if args.template:
        _write_xlsx(out, args.template, _xlsx_path(args, out))
    print(f"Done. {flagged} item(s) need review. Results saved to {out}")
    return 0


def cmd_xlsx(args) -> int:
    out = Path(args.results)
    try:
        template = _template(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not template:
        print("No metadata template: put one at local/metadata_template.json or pass --metadata-template.",
              file=sys.stderr)
        return 2
    if not out.exists():
        print(f"{out} does not exist.", file=sys.stderr)
        return 1
    try:
        xlsx = _xlsx_path(args, out)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    _write_xlsx(out, template, xlsx)
    return 0


def cmd_gui(args) -> int:
    from .gui import run

    return run()


def cmd_debug(args) -> int:
    from . import netguard

    netguard.enable()
    from .debug import dump, dump_list

    for p in args.files:
        if args.list_pages:
            dump_list(Path(p), [int(n) for n in args.list_pages.split(",")])
        else:
            dump(Path(p), args.unmasked)
    return 0


def cmd_evaluate(args) -> int:
    from . import netguard

    netguard.enable()
    from .evaluate import evaluate, make_template

    if args.template:
        return make_template(Path(args.results), Path(args.truth))
    return evaluate(Path(args.results), Path(args.truth), args.show, args.diff)


def cmd_truth(args) -> int:
    from . import netguard

    netguard.enable()
    from .truth import run

    ensure_private_dir(DATA_DIR)
    return run(Path(args.folder), Path(args.output), not args.no_open)


def cmd_serve(args) -> int:
    from . import netguard

    netguard.enable()
    from . import ocr
    from .server import serve

    ocr.check_tesseract()

    serve(args.port, ensure_private_dir(DATA_DIR), Path(args.output), _options(args))
    return 0


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)  # anything this program creates is private to the current user
    p = argparse.ArgumentParser(prog="python -m extractor", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="one-time download of EasyOCR models (needs internet)")
    s.add_argument("--langs", nargs="+", default=["fr"],
                   help="EasyOCR language codes to fetch; 'fr' pulls the shared Latin-script model")
    s.add_argument("--doctr", action="store_true", help="also fetch docTR models for --engines ...,doctr")
    s.add_argument("--trocr", action="store_true", help="also fetch the TrOCR model for --engines ...,trocr")
    s.add_argument("--layout", action="store_true", help="also fetch the layout model for --layout model")
    s.add_argument("--tess-best", nargs="*", metavar="LANG",
                   help="also fetch Tesseract 'best' models (default: eng) for --best-model")
    s.set_defaults(func=cmd_setup)

    def add_ocr_options(sp):
        g = sp.add_argument_group("OCR options")
        g.add_argument("--reread", choices=["off", "tiebreak", "easyocr", "all"], default="tiebreak",
                       help="crop and re-read fields: 'tiebreak' (default) = EasyOCR re-reads only where the "
                            "engines disagree; 'easyocr' = always; 'all' = both engines; 'off'")
        g.add_argument("--engines", default="tesseract,easyocr,doctr",
                       help="voting engines, comma-separated: tesseract (always first), easyocr, doctr, trocr")
        g.add_argument("--layout", choices=["model", "rules"], default="model",
                       help="where the article starts: 'model' (default) = a layout model's blocks, checked "
                            "against the line layout; 'rules' = the line layout alone")
        g.add_argument("--clean", action="store_true",
                       help="deskew, remove uneven lighting and denoise each page before OCR")
        g.add_argument("--best-model", action="store_true", help="use Tesseract 'best' models (slower, more accurate)")
        g.add_argument("--multipass", action="store_true",
                       help="read each field with 3 differently cleaned Tesseract passes and take the majority")

    s = sub.add_parser("process", help="read photos/PDFs and append rows to a CSV (offline)")
    s.add_argument("inputs", nargs="+", help="files or folders")
    s.add_argument("-o", "--output", default=str(DEFAULT_CSV))
    s.add_argument("--lang", help="force a Tesseract language, e.g. 'fra' or 'eng+deu'")
    s.add_argument("-j", "--jobs", type=int, default=1, help="photos to process in parallel (each needs ~1.5 GB RAM)")
    g = s.add_argument_group("filing: number the releases and name their PDFs")
    g.add_argument("--box", help="box label (e.g. 12); otherwise read from a folder named like 'Box 12'")
    g.add_argument("--folder", help="folder label (e.g. 3); otherwise read from a folder named like 'Folder 3'")
    g.add_argument("--first-release", type=int, default=1, help="release number of the first release (default 1)")
    g.add_argument("--pdfs", metavar="DIR", help="write one named PDF per release (and the list page) into DIR; "
                   "without it the proposed names are only added to the spreadsheet")
    g.add_argument("--force-pdfs", action="store_true", help="replace PDFs that already exist in --pdfs")
    g.add_argument("--name-template", help="release PDF name; {box} {folder} {release} (default: the metadata "
                   "template's, else Box{box}_Folder{folder}_{release:03d})")
    g.add_argument("--list-name-template", help="list page PDF name; {box} {folder}")
    g.add_argument("--metadata-template", metavar="JSON", help="metadata spreadsheet layout (and PDF naming); "
                   "default local/metadata_template.json when it exists; \"\" for none")
    g.add_argument("--xlsx", metavar="FILE", help="where to write the metadata spreadsheet "
                   "(default: the results file with .xlsx); written whenever there is a template")
    add_ocr_options(s)
    s.set_defaults(func=cmd_process)

    s = sub.add_parser("xlsx", help="rebuild the metadata spreadsheet from a results CSV (e.g. after fixing it)")
    s.add_argument("results", nargs="?", default=str(DEFAULT_CSV))
    s.add_argument("--metadata-template", metavar="JSON", help="default local/metadata_template.json")
    s.add_argument("--xlsx", metavar="FILE", help="default: the results file with .xlsx")
    s.set_defaults(func=cmd_xlsx)

    s = sub.add_parser("gui", help="a small window: choose a folder and an output file, press Start")
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("evaluate", help="score a results CSV against a hand-made answer key")
    s.add_argument("results")
    s.add_argument("truth")
    s.add_argument("--template", action="store_true", help="create a blank answer key listing the results' files")
    s.add_argument("--show", action="store_true", help="print the wrong values (for your eyes only)")
    s.add_argument("--diff", action="store_true", help="describe each wrong value with letters masked (safe to share)")
    s.set_defaults(func=cmd_evaluate)

    s = sub.add_parser("debug", help="print OCR line layout with letters masked (safe to share)")
    s.add_argument("files", nargs="+")
    s.add_argument("--unmasked", action="store_true", help="show real text (for your eyes only)")
    s.add_argument("--list-pages", metavar="N,N", help="show, with real text, how these list pages are read")
    s.set_defaults(func=cmd_debug)

    s = sub.add_parser("truth", help="type the correct answers for a folder of photos (answer key)")
    s.add_argument("folder")
    s.add_argument("-o", "--output", default=str(DATA_DIR / "truth.csv"))
    s.add_argument("--no-open", action="store_true", help="don't open each photo in the image viewer")
    s.set_defaults(func=cmd_truth)

    s = sub.add_parser("serve", help="phone capture page on localhost (expose with tailscale serve)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("-o", "--output", default=str(DEFAULT_CSV))
    add_ocr_options(s)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    if args.cmd == "setup" and args.tess_best == []:
        args.tess_best = ["eng"]
    return args.func(args)
