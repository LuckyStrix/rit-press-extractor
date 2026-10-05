# Privacy and copyright

> **Not legal advice.** This explains how the tool is designed and the general
> legal landscape (United States law) as it applies to this kind of work. For
> decisions about a specific collection, ask your institution's copyright,
> archives or records staff.

## In short

- **Nothing leaves your computer.** Photos, OCR text and results stay on the
  machine running the tool.
- **The tool keeps very little.** Per release it keeps a date and five words,
  and, if you use phone capture, the photo itself.
- **The photos and spreadsheets contain personal information** (names, sometimes
  addresses or phone numbers), so handle them like any other personal records.
- **The extracted data is low-risk under copyright** (a fact plus a five-word
  identifier). The photos are full copies of the releases, so make and keep
  them only under your institution's digitization authority.

---

## Privacy

### What stays on your computer

Everything you process. When you run `process`, `serve`, `truth`, `evaluate` or
`debug`, the tool first switches off its own ability to make outbound network
connections or look up internet addresses. If any part of it, including a
third-party library, tried to go online, it would fail with an error rather
than send anything.

- Photos go to the OCR engines in memory or through a direct pipe. No temporary
  copies are written.
- No OCR text is cached or logged. The only files written are the ones listed below.
- The OCR engines run locally from model files in `models/`. Your material is
  never used to train anything.

### The one time it goes online: `setup`

`setup` downloads model files once. It sends no data of yours; it only fetches:

| What | From |
|---|---|
| EasyOCR models | EasyOCR's GitHub releases (JaidedAI) |
| docTR models (`--doctr`) | docTR's GitHub releases (Mindee) |
| Tesseract "best" model (`--tess-best`, optional) | `github.com/tesseract-ocr/tessdata_best` |
| TrOCR model (`--trocr`, optional) | Hugging Face (`microsoft/trocr-base-printed`) |

Installing the software itself (`pip`, `apt`, `winget`, the Tesseract installer)
also downloads packages, as with any software.

### What is stored, and where

| File | Contains | Where |
|---|---|---|
| Phone captures | full photos of the releases | `data/captures/` |
| Results spreadsheets | dates, first five words, file names, review notes | wherever you point `-o` (keep them in `data/`) |
| Answer keys | your typed dates and first five words | `data/truth.csv` |
| Models | OCR model files, no material of yours | `models/` |

- **Linux:** everything the tool creates is readable only by your user account
  (folders `0700`, files `0600`).
- **Windows:** these permissions aren't enforced, so:
  - keep the project inside your own user folder,
  - use BitLocker if available,
  - don't put `data\` in a shared or synced folder (OneDrive, Dropbox) unless
    that's allowed for this material.
- **Git:** `data/`, `models/`, images, PDFs and CSVs are excluded, so they can't be
  committed by accident with a normal `git add`. Never override this with `git add -f`.
- **When a project ends:** delete `data/` (and empty the Recycle Bin on Windows).
  Note that ordinary deletion on SSDs isn't guaranteed to be unrecoverable. Use
  full-disk encryption if that matters for your material.

### Phone capture

```
 phone ──(Tailscale: encrypted, only your own devices)──▶ tailscale serve ──▶ capture page on 127.0.0.1
```

- The capture page listens **only on the computer itself** (`127.0.0.1`). The
  only way in from outside is through Tailscale, which connects only devices
  signed in to your own Tailscale network (tailnet), and encrypts everything
  end to end.
- **Tailscale's servers** coordinate which devices may connect, and may relay
  encrypted traffic when a direct connection isn't possible. They can't read it.
- **Never use `tailscale funnel`.** It would publish the page on the public
  internet. `tailscale serve` (what the guide uses) is tailnet-only.
- **HTTPS certificates** from Tailscale are listed in public certificate
  transparency logs. Those logs reveal your computer's Tailscale hostname, never
  any content, so give the computer a name that doesn't identify you or the project.
- Photos are taken inside the web page, so **they aren't saved to the phone's
  camera roll**. Shots waiting to upload exist only in the open page.
- Optional: start `serve` with `PRX_ALLOWED_USERS=you@example.com` to accept
  uploads only from your own Tailscale login. Uploads also require a custom
  header, so other websites open in your browser can't post to the page.

### Personal information in the releases

Press releases name people: students, faculty, staff, donors and guests. They
sometimes include titles, hometowns, home addresses or phone numbers.

- **The photos** contain all of it. Treat them as personal records.
- **The spreadsheet** is minimal, but the first five words often *are* a
  person's name and title ("John Q. Smith, chairman of…").
- **Releases were published, but a new collection of them is still personal
  data.** Follow your institution's records and privacy policies. At a US
  university, those may cover student information under FERPA.
- **Asking for help (from people or AI assistants):** share only the masked
  outputs. `debug` and `evaluate --diff` replace letters with `X`/`x` and digits
  with `9`, which keeps layout and error types while hiding the text. Don't upload
  photos or unmasked output to online services unless you're authorized to share
  that material.

---

## Copyright

### Who owns these releases

Press releases written by university staff as part of their jobs are generally
**works made for hire, owned by the university** (17 U.S.C. § 201(b)). How long
a particular release stays protected depends on facts like whether and how it
was published, and whether it carried a copyright notice. For example, some
works published in the US before 1978 without a notice are in the public
domain. **Unless your institution has confirmed a release's status, treat it as
protected.**

### What the tool extracts

| Field | Copyright position |
|---|---|
| **Release date** | A fact. Facts can't be copyrighted (*Feist Publications v. Rural Telephone*, 1991). |
| **First five words** | Words and short phrases aren't protected by copyright on their own (37 C.F.R. § 202.1(a)). Five words out of a whole release is a tiny, non-substantial portion. Recording them as an identifier for cataloging is the kind of use fair use favors (17 U.S.C. § 107): indexing, not reproduction, with no effect on any market for the release. |

The tool is built to stay on that side of the line:
- It **never stores or exports the full text** of a release.
- Results contain only the two fields above, plus file names and review notes.
- Nothing is published or shared by the tool.

### The photos

A photo of a release is a **copy**, and making copies is one of the copyright
owner's exclusive rights (17 U.S.C. § 106). Common bases for making them:

- **The copyright owner's own authorization.** For example, a university's
  archives digitizing the university's own releases, with the right people's approval.
- **Library and archives copying** (17 U.S.C. § 108). This allows certain
  preservation and replacement copies, under conditions.
- **Fair use** (17 U.S.C. § 107), weighed case by case.

In practice:
- Make sure the digitization is authorized under your library's or archives' policy.
- Keep photos within the project.
- Don't publish photos or transcribed full text without clearance.
- Delete photos you no longer need.

---

## Third-party software licenses

The tool runs on open-source components. All are fine for internal use as described here.

| Component | License |
|---|---|
| Tesseract OCR and its models | Apache-2.0 |
| EasyOCR | Apache-2.0 |
| docTR (python-doctr) | Apache-2.0 |
| PyTorch / torchvision | BSD-style and Apache-2.0 (mixed permissive) |
| OpenCV | Apache-2.0 |
| Pillow | MIT-CMU |
| pillow-heif | BSD-3-Clause (bundles libheif, LGPL-3.0) |
| transformers / TrOCR model (optional) | Apache-2.0 / MIT |
| **PyMuPDF** (reads PDFs) | **AGPL-3.0** or commercial license |

**PyMuPDF's AGPL license matters only if you distribute this tool or offer it
to other people as a network service.** In that case its source-sharing
requirements apply (or a commercial PyMuPDF license is needed). Using it
yourself, including through your own phone over Tailscale, is internal use.

This repository doesn't include a license of its own yet, so by default all
rights are reserved by its author.
