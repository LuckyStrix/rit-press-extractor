# Using the tool

Commands below are written for Linux (`.venv/bin/python`). On Windows, use
`.venv\Scripts\python` and backslashes in paths. Run everything from inside the
`rit-press-extractor` folder.

## The everyday loop

```
 1. Photograph or scan  ──▶  2. Process  ──▶  3. Review flagged rows  ──▶  done
    (phone page or files)       (one command)     (needs_review = YES)
                                                       │
                       now and then: 4. check accuracy with an answer key
```

---

## 1. Take good photos

The tool copes with phone photos, but the better the photo, the more rows come
out verified:

- **The whole page in the frame**, filling most of it, held flat.
- **Even light, no shadows** across the text: daylight or a desk lamp from the side.
- **Straight on**, not at a steep angle. Small tilts are fine.
- **Sharp:** tap to focus and hold still. Blurry photos get flagged.
- **Name files by item number** if you can (`0042.jpg`). The digits at the
  start of a filename go into the `item_number` column.

Accepted formats: JPG, PNG, TIFF, HEIC (iPhone), WEBP, BMP and PDF. Each PDF
page is treated as its own release.

## 2. Process a folder

```bash
.venv/bin/python -m extractor process data/captures -o data/batch01.csv -j 4
```

- `data/captures` is a folder (searched including subfolders) or individual files.
- `-o` is the spreadsheet to write. Rows are **added** to it, so re-running
  appends rather than replaces; use a new name for a fresh run.
- `-j 4` processes 4 photos at a time (see the speed tables in the setup guides).

Each photo prints a line as it finishes:
```
  [ok    ] 0003.jpg p1: 1969-01-09 | Miss Jane Doe, who is
  [REVIEW] 0006.jpg p1: 1969-01-09 | Four seniors majoring in printing
Done. 9 item(s) need review. Results appended to data/batch01.csv
```

Keep outputs in `data/`: it's private and never committed to git.

### What's in the spreadsheet

| Column | Meaning |
|---|---|
| `file`, `page`, `item_number` | which photo (and PDF page) the row came from |
| `release_date` | the release date as `YYYY-MM-DD` (`YYYY-MM` if the page gives no day) |
| `release_date_as_printed` | the date exactly as typed on the page |
| `first_five_words` | the first five words of the article, as printed |
| `date_verified`, `words_verified` | `YES` when that field passed every check |
| `date_confidence`, `words_confidence` | Tesseract's lowest word confidence (0–100) when the engines agree, else `0`. Handy for sorting; it rarely reaches 100 even when right |
| `language` | the language the article was read in |
| `needs_review` | `YES` if either field isn't verified |
| `review_reasons` | every reason, in plain words |

**How the first five words are written:**
- Exactly as printed, punctuation included: `Smith,` `(R.I.T.)` `"Winter`.
- Leading articles are skipped and the next word capitalized: "A special
  showing of…" becomes `Special showing of…`.
- The `ROCHESTER, N.Y. —` dateline is skipped.
- A run-in caps headline counts as text: `ACME GIVES COLLEGE GRANT---J. R.`

Full rules: [How accuracy is measured](accuracy.md#how-the-fields-are-chosen).

## 3. Review the flagged rows

Open the CSV in Excel, LibreOffice or Google Sheets (choose **UTF-8** if asked),
filter `needs_review` to `YES`, and check each one against the paper or photo.
Rows marked `no` passed every check. It's still worth spot-checking a few now
and then.

### What the reasons mean

| Reason (abbreviated) | What happened | What to check |
|---|---|---|
| `engines disagree on first words: tesseract '…' vs easyocr '…'` | the engines read the text differently | which reading matches the paper (often a single letter or punctuation mark) |
| `tesseract confidence 73 < 90 on 'Hargrove,'` | the engines agree, but Tesseract was unsure of a word | that word, often a name |
| `engines disagree on date` / `found no date` | the date was misread or not found | the date on the page |
| `numeric date '5/14/82' read as US month/day` | the date was typed as numbers | that day and month aren't swapped |
| `two-digit year '82' assumed to be 1982` | the year was printed as two digits | the century |
| `other dates also found above the body` | several dates in the header | the tool picked the release date, not another one |
| `no dateline or paragraph indent; body start inferred from spacing` | the layout was unusual | the words come from the start of the article |
| `text above the chosen start reads like article text` | the tool may have skipped the real first paragraph | the words come from the first paragraph |
| `… hyphenated across a line break; joined as '…'` | a word split by a line break was joined | the joined word |
| `low-resolution page` | the photo is small or far away | retake it closer if the text is hard to read |
| `could not open file` / `processing failed` | an unreadable or corrupt file | re-export or retake the photo |

Correct the cells in your spreadsheet. If you want to keep the tool's original
output, save your corrected version under a different name.

---

## Capture with a phone

Your computer runs a small web page; your phone opens it over
[Tailscale](https://tailscale.com) (a private, encrypted network between your
own devices). Every photo goes straight to your computer and is processed in the
background.

**One-time setup:**
1. Install Tailscale on the computer and the phone, and sign in to the same account on both.
2. In the Tailscale admin console, under **DNS**, enable **MagicDNS** and **HTTPS certificates**.
   The phone camera only works over HTTPS.

**Each session:**
```bash
.venv/bin/python -m extractor serve -o data/batch01.csv
```
In a second terminal (only needed once; it stays on until you turn it off):
```bash
tailscale serve --bg --https=8443 8765
```
The command prints the address, `https://<your-computer>.<your-tailnet>.ts.net:8443`.
Open that **including `https://`** on the phone. Allow camera access. Add it to
your home screen for one-tap access next time.

**On the phone:**
- **Number** (bottom left): the item number for the next photo. It goes up by
  one after each shot; tap it to type a different number.
- **Shutter** (middle): takes the photo.
- **Status** (bottom right): `✓ 12` means saved. `2 sending` means photos are
  queued. If it shows a reason (`waiting – …`), the photos are kept on the
  phone and retried until the computer has them. Keep the page open until it
  shows ✓.

Photos are saved on the computer as `data/captures/0012.jpg`. Reusing a number
never overwrites an earlier photo (it saves `0012-2.jpg`). The computer's terminal
prints each result as it finishes.

**When you're done:** stop `serve` with Ctrl+C, and stop sharing with
`tailscale serve --https=8443 off`.

> ⚠️ **Never use `tailscale funnel`.** It would publish the page on the public
> internet. `tailscale serve` keeps it inside your private tailnet.

> If you already use `tailscale serve` for something else on port 443, the
> `--https=8443` above leaves it alone.

| Phone problem | Fix |
|---|---|
| "Client sent an HTTP request to an HTTPS server" / a `.txt` download | Type the address with `https://` at the start |
| "camera blocked" | Allow camera access for the site in the browser settings (iPhone: Settings → Safari → Camera) |
| "needs https" | You opened an `http://` address; use the `https://…:8443` one |
| `waiting – not a JPEG image` | Update the tool (`git pull`) and restart `serve` |
| Page won't load | Check that `serve` is running and that Tailscale is connected on both devices |

Optional: to accept uploads only from your own Tailscale login, start the server
with `PRX_ALLOWED_USERS=you@example.com`.

---

## 4. Check accuracy with an answer key

The tool flags what it doubts. To find out how often it's actually right on
*your* material, especially a new batch or a different layout, type the
correct answers for a sample and compare.

**Type the answers** (about 30 seconds per photo):
```bash
.venv/bin/python -m extractor truth data/captures -o data/truth.csv
```
Each photo opens in your image viewer. Type the release date (`1969-01-09` or
`January 9, 1969`) and the first five words **exactly as on the paper**, using
the conventions above. Enter leaves a field blank, `b` goes back, `s` skips, and
`q` saves and quits. Running it again continues where you left off. The tool's
own answers are never shown, so they can't bias yours.

**Score a run:**
```bash
.venv/bin/python -m extractor evaluate data/batch01.csv data/truth.csv
```
```
first_five_words (17 checked)
  VERIFIED BUT WRONG (must be 0)            0
  verified and right                       12
  flagged and wrong (caught)                1   0006.jpg
  flagged but right (needless review)       4   0007.jpg, 0008.jpg, 0012.jpg, 0017.jpg
```
**"VERIFIED BUT WRONG" is the number that matters.** It must be 0 before you
trust unflagged rows. If it isn't:
- `--diff` describes each wrong answer with letters masked (safe to share when asking for help).
- `--show` prints the actual text (for your eyes only).

Before blaming the tool, check the answer key itself: it's easy to type what a
release *should* say instead of what it literally says.

---

## Troubleshooting a page

```bash
.venv/bin/python -m extractor debug data/captures/0008.jpg
```
This prints every line the OCR found, with its position, spacing and
confidence, and marks where the tool decided the article starts. Letters are
masked (`Xxxxx xx 9999`), so the output is safe to paste when asking for help.
`--unmasked` shows the real text, for your own use.

## Command reference

| Command | What it does |
|---|---|
| `setup [--doctr] [--trocr] [--tess-best]` | one-time model download (the only command that uses the internet) |
| `process FILES/FOLDERS -o OUT.csv [-j N]` | read photos and append rows to a CSV |
| `serve [-o OUT.csv] [--port 8765]` | phone capture page on this computer |
| `truth FOLDER [-o data/truth.csv] [--no-open]` | type an answer key |
| `evaluate RESULTS.csv TRUTH.csv [--diff] [--show]` | score results against an answer key |
| `debug FILE [--unmasked]` | show how a page was read |

`process` and `serve` also accept the OCR options described in
[accuracy](accuracy.md#optional-settings-and-their-measured-effect)
(`--engines`, `--reread`, `--best-model`, `--clean`, `--multipass`). The
defaults are the best measured settings.
