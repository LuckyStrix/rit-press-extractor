# RIT Press Release Extractor

Reads photos or scans of RIT press releases and writes a CSV with each release's
**release date** and the **first five words of the article**. Everything runs on
this machine. Any field that isn't fully verified is flagged for a person to check.

## Setup (once)

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-all libheif-dev
python3 -m venv .venv
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m extractor setup          # downloads EasyOCR models (only step that uses the internet)
```

`setup` fetches English plus the shared Latin-script model, which covers French,
German, Spanish, Italian, Portuguese, Dutch, and others. For other scripts, add
them with `setup --langs ru ja ...`.

## Use

**From files** (JPG, PNG, TIFF, HEIC, WEBP, PDF; folders are scanned recursively):

```bash
.venv/bin/python -m extractor process path/to/photos/ -o data/results.csv
```

Each page of a PDF is treated as its own release. If a filename starts with
digits (`0042.jpg`), those digits go in `item_number`.

**From a phone** (camera page, over Tailscale):

```bash
.venv/bin/python -m extractor serve [-o data/batch1.csv]   # listens on 127.0.0.1:8765 only
tailscale serve --bg --https=8443 8765        # HTTPS, reachable only inside your tailnet
```

Open `https://<your-computer>.<your-tailnet>.ts.net:8443` on the phone (port 8443 keeps
your existing `tailscale serve` on 443 untouched). Line the page up in
the preview and tap the shutter. The number is the item number. It goes up by 1
after every shot, and you can tap it to type a different one. Shots queue on the
phone and retry until the laptop has them, so none get lost if the connection
drops. Each photo is saved as `data/captures/<number>.jpg` and processed in the
background, and its row is added to the output CSV (`-o`, default `data/results.csv`). A reused number never
overwrites an earlier photo (it saves `0012-2.jpg`).

Stop sharing with `tailscale serve --https=8443 off`. **Never use `tailscale funnel`**:
it would put the page on the public internet.

## Output columns

| column | meaning |
|---|---|
| `file`, `page`, `item_number` | where the row came from |
| `release_date` | ISO `YYYY-MM-DD` (or `YYYY-MM` if the page gives no day) |
| `release_date_as_printed` | exactly as it appears on the page |
| `first_five_words` | first five words of the body (see rules below) |
| `date_verified`, `words_verified` | `YES` only if that field passed every check below |
| `date_confidence`, `words_confidence` | Tesseract's lowest word confidence (0–100) when both engines agree; `0` if they disagree. Useful for sorting the review queue. It rarely reaches 100 even on correct reads, so use the verified columns to decide what needs checking. |
| `language` | detected body language |
| `needs_review` | `YES` if either field is unverified |
| `review_reasons` | every reason the row was flagged, in plain words |

## How the fields are chosen

* **Article start**, checked in this order:
  1. Right after a dateline (`ROCHESTER, N.Y. —`) or a caps run-in headline at
     the start of a paragraph (`RIT RECEIVES GRANT -- J. R. Smith, ...`).
  2. Otherwise, the first paragraph whose first line is **indented** relative to
     the line below it, by about 3–15 typewriter characters. This is the usual
     layout of 1960s releases. It's measured line to line, so tilted photos
     still work. The paragraph has to read as prose and its first line has to
     run to the right margin, which rules out letterheads, contact blocks, and
     centered titles.
  3. Otherwise, the first flush paragraph after a large blank space (flagged).
  4. Otherwise, the first prose-like line (flagged).

  Line pieces that Tesseract splits apart on the same row are rejoined first,
  and specks far taller than the text are ignored.
* **Language**: pages are read as English. A page switches to another language
  only when that language clearly dominates the text. A weak hint of another
  language keeps English and flags the row.
* **First five words**: all leading articles are skipped, in the body's language,
  including stacked and elided ones (`The`, `Los`, `Die`, `L'université` → `université`).
  Surrounding quotes and punctuation are stripped. Abbreviation periods (`Dr.`,
  `U.S.`) and internal apostrophes and hyphens are kept. A word split across a
  line break (`uni-`/`versity`) is joined and flagged.
* **Release date**: only the header and dateline are searched, never the body.
  A date next to a release cue ("For release:", "Embargoed until") wins. Otherwise
  the dateline's date is used, otherwise the header's date. Other header dates,
  numeric dates (`5/3/87` is read as US month/day), two-digit years, and dates
  without a day are all flagged.

## What "verified" means

No OCR is perfect on phone photos. Instead of guessing, each page is read by
**two independent OCR engines**, Tesseract (LSTM) and EasyOCR (CRNN).

A field is left unflagged only when **all** of these hold:

1. Both engines read the field **character for character the same**. The only
   difference allowed is a period: EasyOCR often drops it after initials (`J`
   vs `J.`), so the period rests on Tesseract's confidence alone. For dates,
   both must also parse to the same calendar date.
2. Every Tesseract word confidence is ≥ 90. EasyOCR scores short words badly even
   when it reads them right, so its floor is lower (30) and only catches reads it
   was itself unsure of. Agreement is the main check.
3. No layout guess was needed, the date isn't ambiguous, and there's no doubt
   about the language.

Anything else is `needs_review=YES`, and the reason says exactly what to check.
Thresholds are in `extractor/extract.py` (`MIN_CONF`). Two engines agreeing on
the same wrong reading is unlikely, but it isn't impossible, so spot-check a
sample of unflagged rows too, especially early on.

## Privacy and copyright

* **No data leaves the machine.** `process` and `serve` install a socket-level
  block on outbound connections and DNS lookups before anything runs. OCR models
  load from `models/` with downloads disabled.
* Images go to Tesseract over a pipe, with no temp files. No OCR text is cached
  or logged. The only outputs are the CSV fields above and, for phone captures,
  the photo.
* `data/` and everything the tool writes are owner-only (`0700` / `0600`), and
  git ignores them.
* The capture server listens on `127.0.0.1` only. Tailscale's encrypted tailnet is
  the only way in. Set `PRX_ALLOWED_USERS=you@example.com` to also require a
  specific Tailscale login. Uploads need a custom header, so other websites
  open in your browser can't post to it. Note that Tailscale HTTPS certificates
  put the machine's hostname (not any content) in public certificate logs.
* The tool keeps only a date and five words per release: minimal factual
  metadata for cataloging, not reproduction of the text. Captured photos are
  full copies of the releases, so keep them only as long as your project needs
  and handle them under your library's digitization policy. This is not legal
  advice; check with RIT's copyright or library staff if in doubt.

## Measuring accuracy (answer key)

The tool can only flag what it doubts. To know how often it's actually right,
build an answer key from the paper originals:

```bash
.venv/bin/python -m extractor truth data/captures                  # type the answers -> data/truth.csv
.venv/bin/python -m extractor evaluate data/results.csv data/truth.csv
```

`truth` opens each photo in your image viewer and asks for the release date
(`1969-01-09` or `January 9, 1969`) and the first five words, typed exactly as
on the paper with leading articles left out. Enter leaves a field blank, `b` goes
back, `s` skips, and `q` saves and quits. Running it again picks up where you
stopped. It never shows the tool's answers, so they can't bias yours.

The report gives counts per field: verified and right, **verified but wrong**,
flagged and wrong (caught), flagged but right (needless review), and no answer.
"Verified but wrong" must be 0 before you trust unflagged rows. Add `--show` to
print the wrong values. Keep the key in `data/` so it stays private.

## Optional OCR settings

These are off by default and planned for evaluation against the answer key:

| flag | what it does | cost |
|---|---|---|
| `--best-model` | Tesseract's float "best" models instead of the integer "fast" ones Debian ships. Run `setup --tess-best` once to download them (~15 MB for English). | slower full-page pass |
| `--multipass` | reads each field with three differently cleaned Tesseract passes (Sauvola, Otsu, no contrast boost) and keeps the majority. Disagreement between passes is flagged. | about 2 more seconds per field |
| `--reread` | crops the date and opening-word rows, scales and contrast-boosts them, and re-reads them in single-line mode. **In testing on 17 real 1969 releases this dropped verified fields from 23 to 9 of 34** (Tesseract was less confident on the crops, and a few crops read worse), so it needs tuning before use. | about 3 more seconds per page |

They work with both `process` and `serve`. Turn one on by default only if the
answer key shows it helps.

## Diagnosing a bad result

```bash
.venv/bin/python -m extractor debug data/captures/0006.jpg      # letters masked: safe to share
.venv/bin/python -m extractor debug --unmasked data/captures/0006.jpg
```

This shows every OCR line with its position, spacing, and confidence, and marks
where the tool decided the body starts.

## Tests

```bash
.venv/bin/python -m pytest -q              # unit tests + end-to-end on generated pages (~3 min)
```
