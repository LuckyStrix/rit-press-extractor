# Using the tool

> **Start here:** run `python3 run.py` (Linux) or double-click `run.bat` (Windows). The first
> time it installs everything; after that it opens a window where you pick the input folder
> and output file and press **Start**. See [The window](#the-window).

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

## The window

`python3 run.py` (Linux) or `run.bat` (Windows) opens a small window: choose the **input folder**
and the **output file**, press **Start**, and watch the progress bar, the status line and
the log. **Cancel** stops cleanly and keeps the rows saved so far; **Open results folder**
shows the finished spreadsheet. It runs the same `process` command described below. If
the software isn't installed yet, the first run installs it. Everything below can also be
done from a terminal.

## 1. Take good photos

The tool copes with phone photos, but the better the photo, the more rows come
out verified:

- **The whole page in the frame**, filling most of it, held flat.
- **Even light, no shadows** across the text: daylight or a desk lamp from the side.
- **Straight on**, not at a steep angle. Small tilts are fine.
- **Sharp:** tap to focus and hold still. Blurry photos get flagged.
- **Name files by item number** if you can (`0042.jpg`). The digits at the
  start of a filename go into the `item_number` column.

Accepted formats: JPG, PNG, TIFF, HEIC (iPhone), WEBP, BMP and PDF. Pages are
grouped into releases automatically; see
[Folders with a list page and multi-page releases](#folders-with-a-list-page-and-multi-page-releases).

## 2. Process a folder

```bash
.venv/bin/python -m extractor process data/captures -o data/batch01.csv -j 4
```

- `data/captures` is a folder (searched including subfolders) or individual files.
- `-o` is the spreadsheet to write. Rows are **added** to it. Running a folder
  again **replaces** that folder's earlier rows (matched by file and page), so
  re-running after you add a page, or after adding the list page, updates the
  spreadsheet instead of duplicating it. Rows for other folders are left alone.
- `-j 4` processes 4 photos at a time (see the speed tables in the setup guides).

Each page prints a line as it is read, then each release prints a result line when
its folder is finished:
```
  read 0003.jpg p1
  read 0006.jpg p1
  [ok    ] 0003.jpg p1: 1969-01-09 | Miss Jane Doe, who is
  [REVIEW] 0006.jpg p1: 1969-01-09 | Four seniors majoring in printing
Done. 1 item(s) need review. Results saved to data/batch01.csv
```
The spreadsheet is updated after every page, so a stopped run keeps its progress.

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
| `needs_review` | `YES` if either field isn't verified, or anything else needs a look |
| `review_reasons` | every reason, in plain words |
| `subject`, `subject_verified`, `subject_match` | the subject from the folder's list page, whether the match is certain, and how it was found (`date+text`, `date`, `text`, `none`). Blank without a list page |
| `slug`, `opening_text` | the short tag under the date and the first 40 article words, kept so a list page added later can be matched without reading the photos again |
| `page_count`, `pages` | how many pages the release has, and which ones |
| `folder` | the folder the pages came from |

**How the first five words are written:**
- Exactly as printed, punctuation included: `Smith,` `(R.I.T.)` `"Winter`.
- Leading articles are skipped and the next word capitalized: "A special
  showing of…" becomes `Special showing of…`.
- The `ROCHESTER, N.Y. —` dateline is skipped.
- A run-in caps headline counts as text: `ACME GIVES COLLEGE GRANT---J. R.`

Full rules: [How accuracy is measured](accuracy.md#how-the-fields-are-chosen).

## Folders with a list page and multi-page releases

**List page.** Some folders hold a page titled "News releases sent out": a typed
list of dates and subject lines for the releases in the folder. Put it (or, if the list
runs over several pages, all its pages) in the same folder as the releases. The tool
detects it by its title, reads the dated lines, and attaches each subject to the matching
release. A list page produces no row of its own, and the folder summary shows how many
entries it found.

- **Dates are matched first.** Up to five or more releases can share a day, so within a
  day the tool compares each subject with what the release says: the short tag printed under
  the date (the "slug", e.g. `TVR`) and the opening words. A person's name counts for a lot;
  words nearly every subject shares (`Co-op`, `NTID`) count for little.
- **The list is read cautiously.** Its dates are often misread (`Now. 4, 2970`) or missing,
  and the year is only printed on the first page. The tool rebuilds each date from the
  header month, the list's year and the entry above, and flags every repair in the
  unmatched-entries report.
- **Lists laid out in columns work too.** Some lists print only the day in a "Date" column
  (with the month and year on the `MONTH` line), wrap a long subject onto further lines, and
  add notes in an "Additional Info." column. The day column is read on its own, a wrapped line
  is joined to its entry because it sits closer to the line above than entries do, and the
  notes are left out of the subject.
- **A subject is only given when the evidence clearly favours it.** If two entries fit a
  release equally well, the `subject` cell stays empty and the reasons name the candidates.
  A release with no list entry is flagged.
- **Entries no release claimed** are written to `<output>_unmatched_subjects.csv`, e.g.
  `data/batch01_unmatched_subjects.csv`. If you haven't scanned every release yet, those are
  the ones still to come; if you have, they point at a missing or misread release.

**Multi-page releases.** Each release gets one row. A page that carries a release line or a date
near the top starts a new release. A page number, "continued", or a previous page ending
`-more-` joins a page to the release before it, and `-30-` or `###` closes a release.
Where the evidence is weak the tool leans toward splitting, and joins it can't be sure of
are flagged. `page_count` and `pages` show what was joined.

**Adding the list page later.** Add it to the folder and run `process` on that folder
again; the rows are replaced, not duplicated.

## Numbering releases and naming the PDFs

Filing a folder of photos means a box, a folder and a release number for every release.
Type the box and folder once; the tool numbers the releases for you.

```bash
.venv/bin/python -m extractor process "scans/Box 12/Folder 3" -o data/box12.csv --pdfs data/box12_pdfs
```

- **Box and folder** come from `--box 12 --folder 3`, or from the folder's own name
  (`Box 12/Folder 3`, `box12_folder03`; a folder named only by digits inside a `Box` folder
  counts as the folder number). In the window, fill in the **Box / Folder #** boxes
  (choosing a folder named like that fills them in); leave them empty to skip this step.
  Typed values win over the name. `--box` and `--folder` name one physical folder, so they
  are refused when the input spans several; name those folders instead.
- **Release number** is the release's position in photo order (natural file-name order), starting
  at 1 (`--first-release 40` to continue a folder). A release that runs over several pages
  counts once. List pages are found as before and are not numbered.
- **The spreadsheet** gains `box`, `folder_no`, `release_no` and `file_name` columns: the
  proposed name of each release, so the plan can be checked before any file is made.
- **`--pdfs DIR`** writes one PDF per release (all its pages, in order) plus one for the list
  page(s). Your photos are only read, never renamed or moved. An existing PDF is left alone
  unless you add `--force-pdfs`. In the window the PDFs go in `<results name>_pdfs` beside the
  results file.
- **The naming convention** comes from the metadata template (below) when there is one;
  otherwise it is a placeholder, `Box12_Folder3_001.pdf` and `Box12_Folder3_list.pdf`.
  `--name-template "{box}-{folder}-{release:03d}"` and `--list-name-template` override both.
- **The metadata spreadsheet.** With a template at `local/metadata_template.json` (or
  `--metadata-template FILE`; in the window, the **Metadata template** box, which starts out
  with that file when it exists; `--metadata-template ""` or an empty box for none), every
  run also writes `<results name>.xlsx`: one row per named
  release, with the columns the template lists. `local/` is never committed, so the archive's
  layout stays on this computer; keep a copy of it somewhere safe. The template is JSON:

  ```json
  {"name_template": "Box{box}_Folder{folder}_{release:03d}",
   "list_name_template": "Box{box}_Folder{folder}_list",
   "columns": [["Filename", "{file_name}.pdf"], ["Title", "{title}"],
               ["Date", "{release_date}"], ["Scanned", "{digitized}"], ["Type", "Text"], ["Notes", ""]]}
  ```

  Each column is a heading and a value: fixed text, blank (to fill in by hand), or fields from
  the results CSV in braces. `{title}` is the list-page subject, else the first five words;
  `{digitized}` is when the source file was made (a PDF's own creation date, a photo's date
  taken, else the file's date). Every cell is stored as text, so dates stay `yyyy-mm-dd`.
  After correcting the CSV, rebuild the workbook with `python -m extractor xlsx data/results.csv`.
  If you edit the CSV in Excel, save it as **CSV UTF-8**.
- **One PDF for the whole folder** (as some scanners save it) works the same as one file per
  page: the tool reads it page by page, finds the list page and the releases inside it, and
  cuts it into one named PDF per release. Every release in it gets that PDF's date.

Check the release boundaries before filing: a release the grouping split or joined wrongly
shifts every number after it. The rows flagged `needs_review` say where the tool was unsure.

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
| `the layout model and the line layout disagree on where the article starts` | the page's blocks and its lines point to different paragraphs; the blocks' choice was used | the words come from the first paragraph of the article (not a headline or a note to editors) |
| `text above the chosen start reads like article text` | the tool may have skipped the real first paragraph | the words come from the first paragraph |
| `… hyphenated across a line break; joined as '…'` | a word split by a line break was joined | the joined word |
| `subject could not be settled; possible: 'A'; 'B'` | several list entries fit this release equally well | pick the right subject from the ones listed |
| `no subject found in the list page` | no entry for this release's date fits it | whether the list is missing it, or the date was misread |
| `subject matched by date only` / `by its text only` | only one kind of evidence supports the match | that the subject really belongs to this release |
| `subject text was read with low confidence` | the list page's text was hard to read | the spelling of the subject |
| `a page with no header, date or page number was assumed to be a continuation` | a page was joined to the release before it without clear evidence | whether it is really part of that release, or a new one |
| `the page before ended '-more-' but the next page begins a new release` | the pages don't follow the markers | the page order and grouping |
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

For folders with a list page, add two optional columns to the answer key in your
spreadsheet: `subject` (the subject line as the list prints it) and `page_count` (how many
pages the release has). `evaluate` then scores them too, with the same buckets, and
**"verified but wrong" must be 0 for them as well.** For `page_count`, a row that isn't
flagged counts as verified.

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
| `setup [--doctr] [--layout] [--trocr] [--tess-best]` | one-time model download (the only command that uses the internet) |
| `gui` | the window (`python3 run.py` opens it, installing first if needed) |
| `process FILES/FOLDERS -o OUT.csv [-j N]` | read photos, group them into releases, attach list-page subjects, and update the CSV |
| `serve [-o OUT.csv] [--port 8765]` | phone capture page on this computer |
| `truth FOLDER [-o data/truth.csv] [--no-open]` | type an answer key |
| `evaluate RESULTS.csv TRUTH.csv [--diff] [--show]` | score results against an answer key |
| `debug FILE [--unmasked]` | show how a page was read |

`process` and `serve` also accept the OCR options described in
[accuracy](accuracy.md#optional-settings-and-their-measured-effect)
(`--engines`, `--layout`, `--reread`, `--best-model`, `--clean`, `--multipass`). The
defaults are the best measured settings.
