# RIT Press Release Extractor

Turns photos and scans of archival RIT press releases into a spreadsheet (CSV)
with each release's **release date** and the **first five words of the article**.

## Quick start: one command

```bash
python3 run.py          # Linux
run.bat                 # Windows: double-click it, or type it in PowerShell
```

That's the whole setup. The first time, it installs everything it needs (about 3 GB,
15-20 minutes, no administrator rights, all inside this folder), downloads the OCR models,
and then opens a small window with an **input folder**, an **output file**, a **Start** button
and a **status** area. After that, the same command just opens the window.

The only things it can't install itself are **Tesseract** (the text-reading program) and, on
Linux, the system packages `python3-tk` and `python3-venv`. It checks for them and tells you
exactly what to do. See [Linux setup](docs/setup-linux.md) or [Windows setup](docs/setup-windows.md).

- **Runs entirely on your own computer.** No photos, text or results are sent anywhere.
- **Reads every page with three OCR engines and cross-checks them.** A field is only
  marked verified when the engines agree. Anything uncertain is flagged for a
  person to check, with the reason spelled out.
- **Understands folders of releases:** pages are grouped into releases (multi-page
  releases get one row), and a folder's "news releases sent out" list page supplies each
  release's subject line.
- **Phone capture page (optional):** photograph releases with your phone's
  camera, and they're processed on your computer as you go.

```
 photos / PDFs / phone          three OCR engines vote           spreadsheet
┌──────────────────┐        ┌─────────────────────────┐     ┌────────────────────────────────┐
│ 0001.jpg  0002…  │  ───▶  │ Tesseract  EasyOCR docTR│ ──▶ │ release_date  first_five_words │
└──────────────────┘        └─────────────────────────┘     │ needs_review  review_reasons   │
                                                            └────────────────────────────────┘
```

## Get started

The quick start above is all most people need. To set things up by hand instead:

1. **Install** with the guide for your computer. Each one covers both GPU
   (NVIDIA graphics card, faster) and CPU-only setups:
   - [Linux setup](docs/setup-linux.md)
   - [Windows setup](docs/setup-windows.md)
2. **Use it** with [the usage guide](docs/using.md): processing a folder,
   capturing with a phone, reviewing flagged rows, and checking accuracy.
3. **Read [Privacy and copyright](docs/privacy-and-copyright.md)** before working
   with real material. It explains what the tool keeps, what it never sends
   anywhere, and how the work relates to copyright law and personal information.

Once installed, everyday use is one command (or the window above):

```bash
python -m extractor process path/to/photos -o data/results.csv
```

Then open `data/results.csv` in a spreadsheet and check the rows where
`needs_review` is `YES`. The `review_reasons` column says what to look at.

## How accurate is it?

On a hand-checked set of 17 real 1969 releases photographed with a phone:

| | release date | first five words |
|---|---|---|
| verified and correct | 14 | 12 |
| **verified but wrong** | **0** | **0** |
| flagged for review | 3 | 5 |

Every wrong answer was flagged. The flagged rows are what a person checks. See
[How accuracy is measured](docs/accuracy.md) for how fields are chosen, what
"verified" means, and how to measure accuracy on your own material.

## More documentation

| | |
|---|---|
| [Linux setup](docs/setup-linux.md) | Debian/Ubuntu, GPU or CPU |
| [Windows setup](docs/setup-windows.md) | Windows 10/11, GPU or CPU |
| [Using the tool](docs/using.md) | everyday workflow, phone capture, review, troubleshooting |
| [How accuracy is measured](docs/accuracy.md) | how fields are chosen, verification rules, answer keys, measured results |
| [Privacy and copyright](docs/privacy-and-copyright.md) | data handling, personal information, copyright, software licenses |

## Development

```bash
python -m pytest -q          # unit tests + end-to-end tests on generated pages (a few minutes)
```

The code is in `extractor/`. `pipeline.py` is the per-page flow, `layout.py`
finds the article, `extract.py` holds the voting rules, `folder.py` groups pages
into releases and attaches list-page subjects (`listpage.py`, `subjects.py`,
`pages.py`), `gui.py` is the window, and `cli.py` defines the commands.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party
components and their licenses are listed in
[Privacy and copyright](docs/privacy-and-copyright.md#licenses).
