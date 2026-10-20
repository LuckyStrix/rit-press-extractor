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
_ID = re.compile(r"[A-Za-z0-9]{1,8}")  # box and folder labels go into file names
_BOX = re.compile(r"(?<![A-Za-z])box[\s_.-]*([A-Za-z0-9]+)", re.I)
_FOLDER = re.compile(r"(?<![A-Za-z])folder[\s_.-]*([A-Za-z0-9]+)", re.I)


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
    left alone unless force. Returns one message per file written or refused."""
    from .loader import load_pages

    out_dir.mkdir(parents=True, exist_ok=True)
    messages = []
    for name, pages in pdfs.items():
        target = out_dir / f"{name}.pdf"
        if target.exists() and not force:
            messages.append(f"{target.name} already exists; left alone (use --force-pdfs to replace it)")
            continue
        images = []
        for file in dict.fromkeys(f for f, _ in pages):
            wanted = {p for f, p in pages if f == file}
            images += [img for n, img in load_pages(folder_path / file) if n in wanted]
        if not images:
            messages.append(f"{target.name}: could not read its pages")
            continue
        dpi = max(images[0].width / 8.5, 72)  # page size in the PDF: about letter width
        images[0].save(target, "PDF", save_all=True, append_images=images[1:], resolution=dpi, quality=95)
        messages.append(f"{target.name} ({len(images)} page{'s' if len(images) != 1 else ''})")
    return messages
