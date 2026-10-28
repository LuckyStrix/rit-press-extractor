#!/usr/bin/env python3
"""One command: set everything up if it isn't, then open the window.

    python3 run.py          (Linux)          run.bat  (Windows: double-click or type it)

Nothing here needs administrator rights: the Python environment and the OCR models live
inside this folder. Only the first run downloads anything (about 3 GB, 15-20 minutes);
after that this just opens the window. Standard library only, so any Python 3.9+ can start it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MODEL_FILES = ["models/craft_mlt_25k.pth", "models/english_g2.pth", "models/layout/inference.onnx"]
IMPORTS = "import torch, easyocr, doctr, onnxruntime, scipy, cv2, PIL, pypdfium2, pillow_heif, openpyxl, wordfreq"
TORCH_INDEX = {"cpu": "https://download.pytorch.org/whl/cpu", "gpu": "https://download.pytorch.org/whl/cu128"}


def say(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def stop(msg: str) -> None:
    sys.exit(f"\n{msg}\n")


def run(*cmd, **kw) -> int:
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, **kw).returncode


def has_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    return subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0


def ensure_venv() -> None:
    if PY.exists():
        return
    say("Creating the Python environment in .venv (first run only)")
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
    except Exception as exc:  # Debian/Ubuntu ship venv without pip unless python3-venv is installed
        shutil.rmtree(VENV, ignore_errors=True)
        stop(f"Could not create the Python environment ({exc}).\n"
             "On Debian/Ubuntu this usually means the venv package is missing: ask whoever administers\n"
             "this computer to run: sudo apt install python3-venv")


def deps_installed() -> bool:
    return run(PY, "-c", IMPORTS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def ensure_deps(force_cpu: bool) -> None:
    if deps_installed():
        return
    kind = "gpu" if has_gpu() and not force_cpu else "cpu"
    say(f"Installing the OCR software, {'GPU' if kind == 'gpu' else 'CPU-only'} build "
        "(first run only; a large download)")
    # PyTorch first, from the build that matches this computer, then everything else.
    # On Linux the default PyPI build is the GPU one, so only the CPU build needs an index.
    torch_cmd = [PY, "-m", "pip", "install", "torch", "torchvision"]
    if kind == "cpu" or os.name == "nt":
        torch_cmd += ["--index-url", TORCH_INDEX[kind]]
    if run(*torch_cmd) != 0 or run(PY, "-m", "pip", "install", "-r", "requirements.txt") != 0:
        stop("Installing the OCR software failed. Check the internet connection and run this again;\n"
             "it carries on from where it stopped.")


def models_present() -> bool:
    return all((ROOT / f).exists() for f in MODEL_FILES) and any((ROOT / "models" / "doctr").glob("*"))


def ensure_models() -> None:
    if models_present():
        return
    say("Downloading the OCR models (first run only; the only time this program uses the internet)")
    if run(PY, "-m", "extractor", "setup", "--doctr", "--layout") != 0:
        stop("Downloading the OCR models failed. Check the internet connection and run this again.")


TESSERACT_HELP = {
    "nt": ("Tesseract (the text-reading program) is not installed.\n"
           "Get the installer from https://github.com/UB-Mannheim/tesseract/wiki and, if it asks,\n"
           "choose \"Install just for me\" so no administrator rights are needed. Then run this again.\n"
           "(It is found automatically in %LOCALAPPDATA%\\Programs\\Tesseract-OCR.)"),
    "posix": ("Tesseract (the text-reading program) is not installed.\n"
              "Ask whoever administers this computer to run:\n"
              "  sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd"),
}


def ensure_tesseract() -> None:
    probe = "from extractor import ocr; ocr.check_tesseract()"
    if run(PY, "-c", probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        stop(TESSERACT_HELP["nt" if os.name == "nt" else "posix"])


def ensure_tk() -> None:
    if run(PY, "-c", "import tkinter", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        stop("The window toolkit (tkinter) is missing from this Python.\n"
             + ("Reinstall Python from python.org and keep \"tcl/tk and IDLE\" ticked."
                if os.name == "nt" else "Ask whoever administers this computer to run: sudo apt install python3-tk"))


def main(argv: list[str]) -> int:
    if sys.version_info < (3, 9):
        stop("Python 3.9 or newer is needed (3.11 recommended).")
    check_only = "--check" in argv
    ensure_venv()
    ensure_deps(force_cpu="--cpu" in argv)
    ensure_models()
    ensure_tesseract()
    ensure_tk()
    if check_only:
        say("Everything is installed.")
        return 0
    say("Opening the window")
    if os.name == "nt":
        return run(PY, "-m", "extractor", "gui")
    os.chdir(ROOT)
    os.execv(PY, [str(PY), "-m", "extractor", "gui"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
