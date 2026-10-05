# How accuracy is measured

## The short version

- Every page is read by **three OCR engines**: Tesseract, EasyOCR and docTR.
- A field is **verified** only when a majority of engines read it identically
  and nothing about the page is in doubt.
- Everything else is **flagged** with the reason, for a person to check.
- Accuracy is measured against **answer keys** typed from the paper originals.
  The one number that must stay at zero is *verified but wrong*.

---

## How the fields are chosen

### Where the article starts

Checked in this order:

1. **After a dateline** like `ROCHESTER, N.Y. —`: the article starts after the dash.
2. **The first indented paragraph.** In typewritten releases the article's first
   line is indented about 3–15 characters relative to the line below it. The
   indent is measured line to line, so a tilted photo still works. To count, the
   paragraph has to read as prose and its first line has to run to the right
   margin. That rules out letterheads, contact blocks and centered titles.
3. **The first flush paragraph after a big blank space** *(flagged as a layout guess)*.
4. **The first line that reads like prose** *(flagged)*.

Before this:
- Line pieces the OCR split apart on the same row are rejoined.
- Specks and shadows at the photo's edge are trimmed off, so they can't hide
  the paragraph indent.

As a safety check, if any line *above* the chosen start reads like article
text, the words are flagged ("the tool may have skipped the first paragraph").

### The first five words

- **As printed**, punctuation included (`Smith,` `(R.I.T.)` `"Winter`), counted as
  whitespace-separated words.
- A lone dash isn't a word. A dash typed without spaces stays attached (`GRANT---J.`).
- **Leading articles are skipped**, including stacked and elided ones (`The`,
  `A`, `Los`, `L'université`), and the next word gets a capital letter:
  "A special showing" → `Special showing`.
- A run-in caps headline (`ACME GIVES COLLEGE GRANT---J. R.`) is part of the text.
- A word split across a line break (`uni-` / `versity`) is joined, and the row is flagged.

### The release date

- Only the header and dateline are searched, never the article body (body dates
  are usually about events).
- A date next to a release cue ("For release:", "Embargoed until") wins.
  Otherwise the dateline's date, otherwise the header's date.
- Flagged:
  - several different dates in the header
  - numeric dates (`5/3/87` is read as US month/day)
  - two-digit years
  - dates without a day
  - years outside 1829 (RIT's founding) to today

### Language

Pages are read as English. A page switches to another language only when that
language clearly dominates the text. A weak hint of another language keeps
English and flags the row.

---

## What "verified" means

A field is marked verified (and the row isn't flagged for it) only when **all**
of these hold:

1. **Majority agreement.** Tesseract's reading is matched by more engines than
   disagree, and by at least two in total (two of three is enough).
   - Letters and digits must be identical, capitals included.
   - Another engine may *leave out* punctuation that Tesseract read, but not add
     or change any.
   - For dates, the engines must agree on the calendar date and on the date as printed.
2. **Confidence.** Every word Tesseract read for the field scored at least 90.
3. **No doubts about the page:** no layout guess, no ambiguous date, no
   uncertain language, no low-resolution warning.

Tesseract always supplies the reported value, and the other engines only vote. If
the others outvote Tesseract, the field is flagged rather than "corrected".

**Tie-breaker re-read:** when EasyOCR disagrees on a field, it re-reads just that
row from a full-resolution crop. The re-read only counts if it then agrees with
Tesseract, so it can settle a disagreement but never undo an agreement.

Thresholds live in `extractor/extract.py` (`MIN_CONF`). Changing them should be
backed by an answer key.

## Measuring accuracy on your own material

Results depend on the material, photo quality, and even the computer: different
Tesseract versions read slightly differently. Measure each new batch type, and
each computer you use, against an answer key:

```bash
python -m extractor truth data/captures -o data/truth.csv     # type the correct answers
python -m extractor evaluate data/results.csv data/truth.csv  # compare
```

The report sorts each field into one of five buckets:

| Bucket | Meaning | Goal |
|---|---|---|
| **verified but wrong** | marked verified, but differs from the key | **must be 0** |
| verified and right | correct and verified | as high as possible |
| flagged and wrong | wrong, but flagged, so a person will catch it | fine |
| flagged but right | correct, but flagged anyway | lower means less review work |
| no answer | the tool found nothing | investigate |

`--diff` describes each wrong answer with letters masked (safe to share), and
`--show` prints the actual text. Before treating a mismatch as a tool error,
check the key: typing what a release *should* say instead of what it literally
says is an easy slip.

## Measured results

Measured on 17 real 1969 releases (typewritten, photographed with a phone at
4032×3024), against a hand-made answer key:

| | release date | first five words |
|---|---|---|
| verified and right | 14 | 12 |
| **verified but wrong** | **0** | **0** |
| flagged and wrong | 1 | 1 |
| flagged but right | 2 | 4 |

The two wrong answers were both hard-to-read edge cases, and both were flagged.
On a Windows PC with an NVIDIA GPU, the same set gave the same word results
(12 verified and right, 0 verified but wrong).

### Optional settings and their measured effect

Each change was kept only if it improved results without producing a
verified-but-wrong field. Figures are *words verified & right / words wrong
in total / verified but wrong*, on the same 17 releases.

| Setting | What it does | Result |
|---|---|---|
| **default** (`--engines tesseract,easyocr,doctr --reread tiebreak`) | three-engine majority vote with the EasyOCR tie-breaker | **12 / 1 / 0** (dates: 14 verified, 0 wrong) |
| `--engines tesseract,easyocr` | two engines only | 10 / 1 / 0 |
| `--engines tesseract,doctr` | docTR replacing EasyOCR | 9 / 1 / 0 |
| `--engines …,trocr` | adds TrOCR-printed as a re-reader of the date and opening rows | not usable: it answers in capitals (it was trained on receipts) |
| `--reread off` | no tie-breaker (two engines) | 9 / 1 / 0 |
| `--reread easyocr` | EasyOCR always re-reads the rows | 9 / 1 / 0: fixed one row, lost another |
| `--reread all` | both engines re-read the rows | verified fields fell from 23 to 9 of 34 |
| `--best-model` | Tesseract's "best" model (`setup --tess-best`) | 5 / 3 / 0: more misreads |
| `--clean` | deskew, even out lighting, denoise before OCR | 5 / 1 / 0 |
| `--best-model --clean` | both | 4 / 1 / **1**: **don't use** |
| `--multipass` | three differently cleaned Tesseract passes per field, majority vote (only takes effect with `--reread all`) | not measured |

These were measured on a single batch. Re-measure with your own answer keys
before relying on any non-default setting.

## Known limits

- **Two engines can agree on the same wrong reading.** It's rare (it never
  happened in the measured set), but possible. Spot-check some unflagged rows,
  especially on a new kind of material.
- **The layout rules are tuned on typewritten releases.** Typeset newsletters,
  multi-column pages or handwritten notes may need new answer keys and rule changes.
- **Common needless flags:**
  - a smudged or unusual name that Tesseract reads correctly but with low confidence
  - small punctuation one engine drops or misreads
  - pages without an indented first paragraph
