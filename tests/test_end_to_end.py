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
