"""Number a folder's releases and name their PDFs.

Archivists file each release under a box, a folder and a release number, and every PDF is named
from those three. The box and folder are typed in once (or read from the folder's own name:
"Box 12/Folder 3"); the release number is the release's position in photo order, which the
folder pass already knows. A release that runs over several pages becomes one PDF.

The naming convention is two templates, so changing it is changing a string (or passing
--name-template). Originals are only read: the PDFs are new files in another folder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .folder import FolderOutput

# Placeholders until the archive's real convention is settled: {box}, {folder}, {release}.
RELEASE_TEMPLATE = "Box{box}_Folder{folder}_{release:03d}"
LIST_TEMPLATE = "Box{box}_Folder{folder}_list"
PDF_PIXELS_PER_INCH = 300  # photos carry no reliable size; this only sets the PDF page size, not the pixels
_ID = re.compile(r"[A-Za-z0-9]{1,8}")  # box and folder labels go into file names
# A label is a number (maybe with a letter: "12", "3b") or one letter, so "Boxes" and "Folder_misc" are not read as labels.
_LABEL = r"(\d+[A-Za-z]?|[A-Za-z])(?![A-Za-z0-9])"
_BOX = re.compile(rf"(?<![A-Za-z])box[\s_.-]*{_LABEL}", re.I)
_FOLDER = re.compile(rf"(?<![A-Za-z])folder[\s_.-]*{_LABEL}", re.I)
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]|^\.|\.$|^\s|\s$')


@dataclass
class Naming:
    box: str
    folder: str
    first_release: int = 1
    template: str = RELEASE_TEMPLATE
    list_template: str = LIST_TEMPLATE

    def __post_init__(self):
        for label, value in (("box", self.box), ("folder", self.folder)):
            if not _ID.fullmatch(value):
                raise ValueError(f"The {label} must be 1-8 letters or digits (got {value!r}).")
        if self.first_release < 1:
            raise ValueError("The first release number must be 1 or more.")
        for t in (self.template, self.list_template):
            try:
                t.format(box="1", folder="1", release=1)
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"Bad name template {t!r}: use only {{box}}, {{folder}} and {{release}} ({exc}).")
        # Every release needs its own file, so the release template must vary with the number, and no
        # name may be a path or collide with another (the list page included).
        names = [self.release_name(n) for n in (self.first_release, self.first_release + 1, 10**6)] + [self.list_name()]
        if len(set(names)) != len(names):
            raise ValueError(f"The name templates {self.template!r} and {self.list_template!r} would give "
                             "two PDFs the same name: the release template needs {release}, and the two must differ.")
        for name in names:
            if not name or _UNSAFE_NAME.search(name):
                raise ValueError(f"The name {name!r} is not a usable file name (no slashes or other path characters).")

    def release_name(self, number: int) -> str:
        return self.template.format(box=self.box, folder=self.folder, release=number)

    def list_name(self) -> str:
        return self.list_template.format(box=self.box, folder=self.folder, release=0)


def infer_box_folder(folder_path: Path) -> tuple[str, str]:
    """Box and folder labels from the path ("Box 12/Folder 3", "box12_folder3"), blank if absent.
    A folder named only by digits inside a box folder counts as the folder number."""
    box = folder_no = ""
    parts = folder_path.parts
    for part in reversed(parts):
        if not box and (m := _BOX.search(part)):
            box = m[1]
        if not folder_no and (m := _FOLDER.search(part)):
            folder_no = m[1]
    if box and not folder_no and re.fullmatch(r"\d{1,4}", parts[-1] if parts else ""):
        folder_no = parts[-1]
    return box, folder_no


def apply_names(result: FolderOutput, naming: Naming) -> dict[str, list[tuple[str, int]]]:
    """Set box, folder_no, release_no and file_name on each row; returns {file name: its (file, page)s}
    for every PDF to make, the list page(s) first."""
    pdfs: dict[str, list[tuple[str, int]]] = {}
    if result.list_pages:
        pdfs[naming.list_name()] = result.list_pages
    for i, (row, pages) in enumerate(zip(result.rows, result.release_pages)):
        number = naming.first_release + i
        row.box, row.folder_no, row.release_no = naming.box, naming.folder, str(number)
        row.file_name = naming.release_name(number)
        pdfs[row.file_name] = pages
    return pdfs


def write_pdfs(folder_path: Path, pdfs: dict[str, list[tuple[str, int]]], out_dir: Path, force: bool) -> list[str]:
    """Write each named PDF (all of a release's pages, in order) into out_dir. Existing files are
    left alone unless force. Nothing is lost: PDF pages are copied as they are and photos are stored
    as their exact pixels (no JPEG re-compression). A file that cannot be written is reported, not
    fatal. Returns one message per file written or refused."""
    out_dir.mkdir(parents=True, exist_ok=True)
    messages = []
    for name, pages in pdfs.items():
        target = out_dir / f"{name}.pdf"
        if target.exists() and not force:
            messages.append(f"{target.name} already exists; left alone (use --force-pdfs to replace it)")
            continue
        try:
            count = _write_pdf(folder_path, pages, target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            messages.append(f"{target.name}: FAILED, not written ({type(exc).__name__}: {exc})")
            continue
        messages.append(f"{target.name} ({count} page{'s' if count != 1 else ''})" if count
                        else f"{target.name}: could not read its pages")
    return messages


def _write_pdf(folder_path: Path, pages: list[tuple[str, int]], target: Path) -> int:
    import pypdfium2 as pdfium

    from .loader import PDF_EXTS, load_pages

    doc = pdfium.PdfDocument.new()
    sources = []
    try:
        for file, number in pages:
            path = folder_path / file
            if path.suffix.lower() in PDF_EXTS:  # copy the page itself, not a picture of it
                src = pdfium.PdfDocument(path)
                sources.append(src)
                doc.import_pages(src, [number - 1], index=len(doc))
                continue
            img = next((im for n, im in load_pages(path) if n == number), None)
            if img is None:
                continue
            w, h = img.size
            pt_w, pt_h = w * 72 / PDF_PIXELS_PER_INCH, h * 72 / PDF_PIXELS_PER_INCH
            page = doc.new_page(pt_w, pt_h)
            obj = pdfium.PdfImage.new(doc)
            obj.set_bitmap(pdfium.PdfBitmap.from_pil(img))  # stored with lossless (Flate) compression
            obj.set_matrix(pdfium.PdfMatrix().scale(pt_w, pt_h))
            page.insert_obj(obj)
            page.gen_content()
        count = len(doc)
        if count:
            doc.save(target)
        return count
    finally:
        doc.close()
        for src in sources:
            src.close()
