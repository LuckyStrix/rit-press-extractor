# RIT Press Release Extractor

Turns photos and scans of archival RIT press releases into a spreadsheet (CSV)
with each release's **release date** and the **first five words of the article**.

- **Runs entirely on your own computer.** No photos, text or results are sent anywhere.
- **Reads every page with three OCR engines and cross-checks them.** A field is only
  marked verified when the engines agree. Anything uncertain is flagged for a
  person to check, with the reason spelled out.
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

1. **Install** with the guide for your computer. Each one covers both GPU
   (NVIDIA graphics card, faster) and CPU-only setups:
   - [Linux setup](docs/setup-linux.md)
   - [Windows setup](docs/setup-windows.md)
2. **Use it** with [the usage guide](docs/using.md): processing a folder,
   capturing with a phone, reviewing flagged rows, and checking accuracy.
3. **Read [Privacy and copyright](docs/privacy-and-copyright.md)** before working
   with real material. It explains what the tool keeps, what it never sends
   anywhere, and how the work relates to copyright law and personal information.

Once installed, everyday use is one command:

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
finds the article, `extract.py` holds the voting rules, and `cli.py` defines the
commands.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party
components and their licenses are listed in
[Privacy and copyright](docs/privacy-and-copyright.md#licenses).
