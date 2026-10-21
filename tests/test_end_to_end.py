"""Full pipeline on generated pages with known answers (slow: runs both OCR engines)."""

import pytest
from PIL import Image

from extractor import netguard
from extractor.loader import load_pages
from extractor.pipeline import process_page

from .samples import SPECS, as_phone_photo, render

netguard.enable()  # the whole run must work with the network blocked


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
@pytest.mark.parametrize("variant", ["scan", "phone"])
def test_fields_correct(spec, variant):
    img = render(spec)
    if variant == "phone":
        img = as_phone_photo(img)
    row = process_page(img, spec.name, 1)
    assert row.release_date == spec.expected_date, row.review_reasons
    assert row.first_five_words == spec.expected_words, row.review_reasons
    assert row.language == spec.lang
    if spec.must_flag:
        assert row.needs_review == "YES"


def test_wrong_answer_never_unflagged():
    """A blurry, low-res shot must either be right or be flagged."""
    spec = SPECS[0]
    img = as_phone_photo(render(spec, width=900))
    row = process_page(img, spec.name, 1)
    correct = row.release_date == spec.expected_date and row.first_five_words == spec.expected_words
    assert correct or row.needs_review == "YES"
    assert row.needs_review == "YES"  # low resolution is always flagged


def test_heic_and_pdf_inputs(tmp_path):
    page = render(SPECS[0], width=1200)
    heic = tmp_path / "0007.heic"
    page.save(heic, format="HEIF")
    pdf = tmp_path / "scan.pdf"
    page.save(pdf, format="PDF", resolution=150)  # 8.5 in wide at 150 dpi; loader renders at 300 dpi
    for path in (heic, pdf):
        pages = list(load_pages(path))
        assert len(pages) == 1 and isinstance(pages[0][1], Image.Image) and pages[0][1].width > 1000


def test_mpo_uses_only_primary_image(tmp_path):
    """iPhones attach an HDR gain map as a second JPEG frame (MPO); it must not become a page."""
    page, gain_map = render(SPECS[0], width=800), Image.new("RGB", (200, 260), "gray")
    path = tmp_path / "0008.jpg"
    page.save(path, format="MPO", save_all=True, append_images=[gain_map])
    with Image.open(path) as img:
        assert img.format == "MPO" and img.n_frames == 2
    pages = list(load_pages(path))
    assert len(pages) == 1 and pages[0][1].size == page.size


def test_folder_with_list_page_and_two_page_release(tmp_path):
    """Pages are grouped into releases and subjects come from the list page."""
    from extractor.cli import main

    from .samples import LIST_PAGE, render_lines, wrapped

    folder = tmp_path / "f1"
    folder.mkdir()
    header = ["NEWS from ROCHESTER INSTITUTE OF TECHNOLOGY", "", "FOR IMMEDIATE RELEASE", "November 2, 1970", "TVR", ""]
    first = [*header, *wrapped("A DAY-LONG PUBLIC SYMPOSIUM ON METROPOLITAN TRANSPORTATION IN THE ROCHESTER "
                               "AREA WILL BE HELD AT THE INSTITUTE'S METROPOLITAN CENTER ON THURSDAY. EIGHT "
                               "SPECIALISTS IN TRANSPORTATION WILL GIVE SHORT PRESENTATIONS TO THE PUBLIC."), "", "-more-"]
    second = ["- 2 -", "", *wrapped("PRESENTATIONS WILL BE FOLLOWED BY OPEN DISCUSSION SESSIONS. EMPHASIS WILL BE ON "
                                    "SOCIAL, ENVIRONMENTAL AND POLITICAL ISSUES SURROUNDING TRANSPORTATION "
                                    "DEVELOPMENT. THE FEE IS FIVE DOLLARS."), "", "-30-"]
    third = [*header[:3], "November 2, 1970", "", *wrapped(
        "SUSAN WOLF, A STUDENT IN THE COLLEGE OF APPLIED SCIENCE, WILL BEGIN A CO-OP ASSIGNMENT WITH A LOCAL "
        "FIRM NEXT MONTH. SHE IS THE DAUGHTER OF MR. AND MRS. JAMES WOLF OF ROCHESTER."), "", "-30-"]
    fourth = [*header[:3], "November 3, 1970", "", *wrapped(
        "THE INSTITUTE'S WINTER SPORTS PROGRAM WILL OPEN ITS SEASON WITH A HOME GAME ON SATURDAY. TICKETS ARE "
        "AVAILABLE AT THE DOOR AND THE PUBLIC IS INVITED TO ATTEND THE OPENING CEREMONIES."), "", "-30-"]
    for name, lines in [("0001.png", first), ("0002.png", second), ("0003.png", third), ("0004.png", fourth),
                        ("list1.png", LIST_PAGE)]:
        render_lines(lines).save(folder / name)
    out = tmp_path / "r.csv"
    assert main(["process", str(folder), "-o", str(out), "--engines", "tesseract", "--reread", "off"]) == 0

    import csv
    rows = list(csv.DictReader(open(out, newline="")))
    by_file = {r["file"]: r for r in rows}
    assert sorted(by_file) == ["0001.png", "0003.png", "0004.png"]  # the continuation and list pages have no row
    a, b, c = by_file["0001.png"], by_file["0003.png"], by_file["0004.png"]
    assert a["first_five_words"].startswith("DAY-LONG PUBLIC SYMPOSIUM")  # all caps is not mistaken for Cyrillic
    assert a["page_count"] == "2" and a["pages"] == "0001.png p1, 0002.png p1"
    assert (a["subject"], a["subject_match"]) == ("TVR Transportation", "date+text")
    assert b["subject"] == "Susan Wolf - Co-op" and b["release_date"] == "1970-11-02"
    assert c["subject"] == "" and c["needs_review"] == "YES" and "no subject found" in c["review_reasons"]
    unmatched = list(csv.DictReader(open(tmp_path / "r_unmatched_subjects.csv", newline="")))
    assert [u["subject"] for u in unmatched] == ["Football schedule"]


def test_one_pdf_holding_the_whole_folder(tmp_path):
    """A scanner's single PDF: the list page and every release in one file, read page by page."""
    import csv
    import json

    from openpyxl import load_workbook

    from extractor.cli import main

    from .samples import LIST_PAGE, render_lines, wrapped

    folder = tmp_path / "Box 12" / "Folder 3"
    folder.mkdir(parents=True)
    header = ["NEWS from ROCHESTER INSTITUTE OF TECHNOLOGY", "", "FOR IMMEDIATE RELEASE"]
    first = [*header, "November 2, 1970", "", *wrapped(
        "SUSAN WOLF, A STUDENT IN THE COLLEGE OF APPLIED SCIENCE, WILL BEGIN A CO-OP ASSIGNMENT WITH A LOCAL "
        "FIRM NEXT MONTH. SHE IS THE DAUGHTER OF MR. AND MRS. JAMES WOLF OF ROCHESTER."), "", "-30-"]
    second = [*header, "November 3, 1970", "", *wrapped(
        "THE INSTITUTE'S WINTER SPORTS PROGRAM WILL OPEN ITS SEASON WITH A HOME GAME ON SATURDAY. TICKETS ARE "
        "AVAILABLE AT THE DOOR AND THE PUBLIC IS INVITED TO ATTEND THE OPENING CEREMONIES."), "", "-30-"]
    pages = [render_lines(lines) for lines in (LIST_PAGE, first, second)]
    pages[0].save(folder / "scan.pdf", save_all=True, append_images=pages[1:], resolution=300)
    template = tmp_path / "t.json"
    template.write_text(json.dumps({"name_template": "t_b{box}_f{folder}_{release:04d}",
                                    "columns": [["Filename", "{file_name}.pdf"], ["Made", "{digitized}"]]}))
    out = tmp_path / "r.csv"
    assert main(["process", str(folder), "-o", str(out), "--engines", "tesseract", "--reread", "off",
                 "--pdfs", str(tmp_path / "pdfs"), "--metadata-template", str(template)]) == 0

    rows = list(csv.DictReader(open(out, newline="")))
    assert [(r["file"], r["page"], r["file_name"]) for r in rows] == [
        ("scan.pdf", "2", "t_b12_f3_0001"), ("scan.pdf", "3", "t_b12_f3_0002")]
    assert rows[0]["subject"] == "Susan Wolf - Co-op"
    assert sorted(p.name for p in (tmp_path / "pdfs").iterdir()) == [
        "Box12_Folder3_list.pdf", "t_b12_f3_0001.pdf", "t_b12_f3_0002.pdf"]
    sheet = [[c.value for c in r] for r in load_workbook(tmp_path / "r.xlsx").active.iter_rows()]
    assert [r[0] for r in sheet] == ["Filename", "t_b12_f3_0001.pdf", "t_b12_f3_0002.pdf"]
    assert sheet[1][1] == sheet[2][1] and len(sheet[1][1]) == 10  # both from the one PDF, yyyy-mm-dd
