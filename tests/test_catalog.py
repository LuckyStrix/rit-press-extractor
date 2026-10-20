"""Numbering releases and naming their PDFs from a box and folder."""
from pathlib import Path

import pytest
from PIL import Image

from extractor.catalog import Naming, apply_names, infer_box_folder, write_pdfs
from extractor.folder import assemble_folder

from .test_folder import cont_page, list_page, release_page


@pytest.mark.parametrize("path, expected", [
    ("/scans/Box 12/Folder 3", ("12", "3")),
    ("/scans/box12_folder03", ("12", "03")),
    ("/scans/Box_7/14", ("7", "14")),
    ("/scans/Box 7", ("7", "")),
    ("/scans/misc", ("", "")),
    ("/scans/Boxes/Folder_misc", ("", "")),
    ("/scans/Box A/Folder 3b", ("A", "3b")),
    ("/data/Folder 2024/Box 7/scans", ("7", "")),  # farther up than the parent is unrelated
])
def test_box_and_folder_are_read_from_the_path(path, expected):
    assert infer_box_folder(Path(path)) == expected


def test_releases_are_numbered_in_photo_order_and_multipage_ones_count_once():
    out = assemble_folder("f1", [release_page("a.pdf", more=True), cont_page("a.pdf", 2), list_page("x"),
                                 release_page("b.pdf"), release_page("c.pdf")])
    pdfs = apply_names(out, Naming("12", "3"))
    assert [r.release_no for r in out.rows] == ["1", "2", "3"]
    assert [r.file_name for r in out.rows] == ["Box12_Folder3_001", "Box12_Folder3_002", "Box12_Folder3_003"]
    assert list(pdfs) == ["Box12_Folder3_list", "Box12_Folder3_001", "Box12_Folder3_002", "Box12_Folder3_003"]
    assert pdfs["Box12_Folder3_001"] == [("a.pdf", 1), ("a.pdf", 2)]
    assert pdfs["Box12_Folder3_list"] == [("list1.pdf", 1)]
    assert out.rows[0].box == "12" and out.rows[0].folder_no == "3"


def test_first_release_and_template_can_change():
    out = assemble_folder("f1", [release_page("a.pdf"), release_page("b.pdf")])
    apply_names(out, Naming("1", "2", first_release=40, template="{box}-{folder}-{release}"))
    assert [r.file_name for r in out.rows] == ["1-2-40", "1-2-41"]


@pytest.mark.parametrize("kwargs", [
    dict(box="1/2", folder="3"), dict(box="", folder="3"), dict(box="1", folder="a b"),
    dict(box="1", folder="3", first_release=0), dict(box="1", folder="3", template="{nope}"),
    dict(box="1", folder="3", template="Box{box}_Folder{folder}"),  # same name for every release
    dict(box="1", folder="3", template="{box}/{release}"), dict(box="1", folder="3", template="../{release}"),
    dict(box="1", folder="3", list_template="con"), dict(box="1", folder="3", template="x{release}", list_template="X1"),
    dict(box="1", folder="3", template="x{release}", list_template="x1"),  # list name collides with a release
])
def test_bad_box_folder_or_template_is_refused(kwargs):
    with pytest.raises(ValueError):
        Naming(**kwargs)


def test_pdfs_hold_all_pages_and_never_overwrite(tmp_path):
    src = tmp_path / "Box 1" / "Folder 2"
    src.mkdir(parents=True)
    for n in ("a.png", "b.png"):
        Image.new("RGB", (850, 1100), "white").save(src / n)
    out = tmp_path / "named"
    msgs = write_pdfs(src, {"one": [("a.png", 1), ("b.png", 1)], "two": [("b.png", 1)]}, out, False)
    assert msgs == ["one.pdf (2 pages)", "two.pdf (1 page)"]
    import pypdfium2 as pdfium

    assert len(pdfium.PdfDocument(out / "one.pdf")) == 2
    before = (out / "one.pdf").read_bytes()
    assert "already exists" in write_pdfs(src, {"one": [("a.png", 1)]}, out, False)[0]
    assert (out / "one.pdf").read_bytes() == before
    assert write_pdfs(src, {"one": [("a.png", 1)]}, out, True) == ["one.pdf (1 page)"]


def test_photos_are_stored_without_loss_and_a_bad_page_is_not_fatal(tmp_path):
    import pypdfium2 as pdfium

    src = tmp_path / "in"
    src.mkdir()
    img = Image.effect_noise((300, 400), 80).convert("RGB")
    img.save(src / "a.png")
    out = tmp_path / "named"
    msgs = write_pdfs(src, {"ok": [("a.png", 1)], "bad": [("missing.png", 1)]}, out, False)
    assert msgs[0] == "ok.pdf (1 page)" and "FAILED" in msgs[1] and not (out / "bad.pdf").exists()
    doc = pdfium.PdfDocument(out / "ok.pdf")
    assert len(doc) == 1 and doc[0].get_size() == pytest.approx((72, 96))  # 300x400 px at 300 px/inch
    stream = next(o for o in doc[0].get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE)
    assert stream.get_bitmap().to_pil().convert("RGB").tobytes() == img.tobytes()


def test_a_failed_rewrite_keeps_the_old_pdf_and_a_missing_page_fails_the_whole_pdf(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    Image.new("RGB", (100, 100), "white").save(src / "a.png")
    out = tmp_path / "named"
    write_pdfs(src, {"one": [("a.png", 1)]}, out, False)
    before = (out / "one.pdf").read_bytes()
    msgs = write_pdfs(src, {"one": [("a.png", 1), ("gone.png", 1)]}, out, True)
    assert "FAILED" in msgs[0] and (out / "one.pdf").read_bytes() == before
    assert not list(out.glob("*.part"))
    msgs = write_pdfs(src, {"two": [("a.png", 1), ("a.png", 9)]}, out, False)
    assert "FAILED" in msgs[0] and not (out / "two.pdf").exists()


def test_pdfs_left_from_an_earlier_numbering_are_reported(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    Image.new("RGB", (100, 100), "white").save(src / "a.png")
    out = tmp_path / "named"
    naming = Naming("1", "2")
    write_pdfs(src, {"Box1_Folder2_001": [("a.png", 1)], "Box1_Folder2_002": [("a.png", 1)]}, out, False, naming)
    (out / "Box9_Folder9_001.pdf").write_bytes(b"x")  # another folder's: not ours to mention
    msgs = write_pdfs(src, {"Box1_Folder2_041": [("a.png", 1)]}, out, False, naming)
    stale = [m for m in msgs if "earlier run" in m]
    assert len(stale) == 2 and all("Box9" not in m for m in stale)


def test_a_relative_path_still_has_its_names(tmp_path, monkeypatch):
    d = tmp_path / "Box 12" / "Folder 3"
    d.mkdir(parents=True)
    monkeypatch.chdir(d)
    assert infer_box_folder(Path(".")) == ("12", "3")
    assert infer_box_folder(Path("..")) == ("12", "")
