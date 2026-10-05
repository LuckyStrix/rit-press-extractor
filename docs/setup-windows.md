# Windows setup

For Windows 10 and 11. It takes about 20 minutes, most of it downloads (longer
with a GPU). You only do this once. All commands are typed into **PowerShell**.

**Which path do I follow?** Open PowerShell and run `nvidia-smi`.
- If it prints a table with your graphics card, follow the **GPU** steps.
  Processing is much faster.
- If it says "not recognized", follow the **CPU** steps. Everything works the
  same, just slower.

---

## 1. Install Python, Git and Tesseract

**Python 3.11 and Git:**
```powershell
winget install --id Python.Python.3.11 -e
winget install --id Git.Git -e
```
Close and reopen PowerShell afterwards so the new commands are found.

**Tesseract:** download the installer from the
[UB Mannheim Tesseract page](https://github.com/UB-Mannheim/tesseract/wiki) and
run it with the default options. English is included. Tick extra languages only
if you have releases in other languages.

Tell the tool where Tesseract is. This is permanent; reopen PowerShell after:
```powershell
setx TESSERACT "C:\Program Files\Tesseract-OCR\tesseract.exe"
```
Check it (in a **new** PowerShell window):
```powershell
& $env:TESSERACT --version
& $env:TESSERACT --list-langs
```
The version should start with **5**, and the language list must include `eng` and `osd`.

## 2. Get the code

```powershell
git clone https://github.com/<your-account>/rit-press-extractor.git
cd rit-press-extractor
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

All later commands are run **inside this `rit-press-extractor` folder**.

## 3. PyTorch

**CPU only:** nothing to do. Step 2 installed the standard Windows build, which
is CPU-only.

**GPU (NVIDIA):** replace that build with the graphics-card build. It's a
~2.7 GB download:
```powershell
.venv\Scripts\python -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python -c "import torch; print(torch.__version__, 'GPU:', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
You want a version ending in `+cu128` and `GPU: True` with your card's name.

- `cu128` covers current NVIDIA cards, including the RTX 50-series, which
  *requires* it. `nvidia-smi` must show "CUDA Version" 12.8 or higher. If it
  doesn't, update your NVIDIA driver.
- **Slow or unreliable internet?** pip can't resume a broken download. Copy the
  `https://download-r2.pytorch.org/...whl` address from pip's "Downloading" line
  and fetch it with `curl`, which resumes after drops (re-run it if it stops):
  ```powershell
  curl.exe -L -C - --retry 50 --retry-all-errors -o "<file name from the URL, with %2B written as +>" "<URL>"
  .venv\Scripts\python -m pip install --force-reinstall --no-deps ".\<that file name>"
  ```

## 4. Download the OCR models

This is the **only step that uses the internet**. It downloads about 300 MB of
model files into the `models\` folder. After this, the tool never goes online.

```powershell
.venv\Scripts\python -m extractor setup --doctr
```

## 5. Check it works

```powershell
.venv\Scripts\python -m pytest -q tests\test_units.py
```

All tests should pass. You're ready: continue with **[Using the tool](using.md)**.
On Windows, write commands as `.venv\Scripts\python -m extractor ...` wherever
the guide says `python -m extractor ...`.

---

## Speed and parallel jobs

Add `-j N` to `process` to handle several photos at once.

| Computer | Suggested `-j` | Notes |
|---|---|---|
| GPU with 12+ GB video memory | `-j 4` | each job uses ~2 GB of video memory |
| GPU with 6–8 GB | `-j 2` | |
| CPU only | about half your core count, capped by RAM | each job needs ~1.5 GB RAM |

## Windows-specific notes

- **File protection:** on Linux the tool makes everything it writes readable only
  by you. Windows doesn't support that the same way, so protect the data
  yourself:
  - Keep the folder inside your own user folder (for example under `Documents`).
  - Turn on BitLocker device encryption if it's available.
  - Delete `data\` when a project is finished.
- **Using a Windows PC over SSH:** everything works in an SSH session. Keep the
  session open until a run finishes. `$env:TESSERACT` from `setx` only applies
  to sessions opened *after* you ran it.
- **`truth` command:** photos open in your default image viewer, but Windows
  doesn't let the tool close the previous window. Close them yourself as you go.

## Optional extras

- **Phone capture over Tailscale:** install the Tailscale app for Windows and
  sign in. Setup is in [Using the tool → Phone capture](using.md#capture-with-a-phone).
- **Experimental engines and models** (not recommended by default; see
  [accuracy](accuracy.md#optional-settings-and-their-measured-effect)):
  `setup --tess-best` and `setup --trocr` (the latter also needs `pip install transformers`).

## Updating

```powershell
git pull
.venv\Scripts\python -m pip install -r requirements.txt
```
If `pip` replaces your GPU PyTorch with the CPU build during an update (the
check in step 3 shows `+cpu`), re-run step 3. Your `data\` and `models\` folders
are never touched by git.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Torch not compiled with CUDA enabled` | You have the CPU build; do step 3 (GPU). |
| `tesseract ... not recognized` / Tesseract not found | Re-run the `setx` line in step 1 with your actual install path, then open a new PowerShell. |
| `py` not recognized | Use `python -m venv .venv` instead, or reinstall Python with "Add to PATH" ticked. |
| `ReadTimeoutError` while installing PyTorch | Use the `curl` method in step 3. |
| `note: docTR models not downloaded; voting with two engines` | Run step 4. |
| Two copies of the folder (commands seem to use old code) | Make sure you `cd` into the folder that contains `data\` and `.venv\`, and run `git pull` there. |
