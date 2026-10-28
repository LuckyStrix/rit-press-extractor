# Linux setup

## Quick start: two commands

```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-tk tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd libheif-dev
python3 run.py
```

The first line is the only part that needs `sudo`. The second does the rest by itself, with no
further administrator rights: it creates the Python environment, installs the OCR software (the
GPU build if it finds an NVIDIA card, otherwise the CPU build), downloads the models, and opens
a small window with an input folder, an output file, a Start button and a status area. Run it
from inside the project folder. Next time, `python3 run.py` just opens the window.
Everything below is the same setup done by hand; you only need it if `run.py` reports a problem.

---

## Setup by hand

For Debian 12+, Ubuntu 24.04+ and similar. It takes about 15 minutes, most of it
downloads. You only do this once.

**Which path do I follow?** Run `nvidia-smi` in a terminal.
- If it prints a table with your graphics card, follow the **GPU** steps.
  Processing is much faster.
- If it says "command not found", or you're not sure, follow the **CPU** steps.
  Everything works the same, just slower.

---

## 1. Install system packages

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-tk tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd libheif-dev
```

Check that Tesseract is version **5**:

```bash
tesseract --version | head -1
```

> **Seeing 4.x?** Ubuntu 22.04 ships Tesseract 4, which reads these pages
> differently. Upgrade to Tesseract 5 from the maintained PPA:
> `sudo add-apt-repository ppa:alex-p/tesseract-ocr5 && sudo apt update && sudo apt install -y tesseract-ocr`

Releases in other languages *(optional)*: `sudo apt install -y tesseract-ocr-all`
adds every language Tesseract supports (~600 MB).

## 2. Get the code

```bash
git clone https://github.com/<your-account>/rit-press-extractor.git
cd rit-press-extractor
python3 -m venv .venv
```

All later commands are run **inside this `rit-press-extractor` folder**.

## 3. Install PyTorch (pick one)

**GPU (NVIDIA):**
```bash
.venv/bin/pip install torch torchvision
```

**CPU only:** this smaller build skips about 2.5 GB of graphics-card libraries:
```bash
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

## 4. Install the rest

```bash
.venv/bin/pip install -r requirements.txt
```

**GPU only:** check that PyTorch can see the card:
```bash
.venv/bin/python -c "import torch; print('GPU:', torch.cuda.is_available())"
```
You want `GPU: True`. If it says `False`, see [Troubleshooting](#troubleshooting).

## 5. Download the OCR models

This is the **only step that uses the internet**. It downloads about 430 MB of
model files into the `models/` folder. After this, the tool never goes online.

```bash
.venv/bin/python -m extractor setup --doctr --layout
```

## 6. Check it works

```bash
.venv/bin/python -m pytest -q tests/test_units.py
```

All tests should pass. You're ready: continue with **[Using the tool](using.md)**.

---

## Speed and parallel jobs

Add `-j N` to `process` to handle several photos at once.

| Computer | Suggested `-j` | Notes |
|---|---|---|
| NVIDIA GPU | about half your core count (up to 8) | the jobs share one copy of the OCR models on the GPU, so each extra job costs only ~0.5 GB of RAM and no extra video memory |
| CPU only | about half your core count (`nproc`), capped by RAM | each job needs ~1.5 GB RAM. On a 16-core laptop, `-j 4` does about 20 seconds per photo |

The window picks `-j` for you. With a GPU, the jobs run as threads in one process: the models
load once, and the pages' Tesseract reads still run side by side. Without one, each job is
its own process with its own copy of the models, which is why it needs more RAM.

## Optional extras

- **Phone capture over Tailscale:** install Tailscale (`curl -fsSL https://tailscale.com/install.sh | sh`,
  then `sudo tailscale up`). Setup is in [Using the tool → Phone capture](using.md#capture-with-a-phone).
- **Experimental engines and models** (not recommended by default; see
  [accuracy](accuracy.md#optional-settings-and-their-measured-effect)):
  `setup --tess-best` (Tesseract "best" model) and `setup --trocr` (TrOCR, ~1.3 GB, also needs `pip install transformers`).

## Updating

```bash
git pull
.venv/bin/pip install -r requirements.txt
```

Your photos, results and answer keys are in `data/` and your models are in
`models/`. Git never touches either.

## Troubleshooting

| Problem | Fix |
|---|---|
| `GPU: False` on a machine with an NVIDIA card | Install the NVIDIA driver (`sudo apt install nvidia-driver`, then reboot) and check `nvidia-smi` works. For very new cards (RTX 50-series), make sure `pip show torch` is 2.7 or newer. |
| `tesseract: command not found` | Step 1 didn't finish; re-run it. |
| `EasyOCR model for ... not installed` | Run step 5 again. |
| `note: docTR models not downloaded; voting with two engines` | Run `.venv/bin/python -m extractor setup --doctr`. The tool still works with two engines, just with fewer rows verified. |
| HEIC photos won't open | `sudo apt install libheif-dev`, then `.venv/bin/pip install --force-reinstall pillow-heif` |
| Out of memory | Lower `-j`. |
