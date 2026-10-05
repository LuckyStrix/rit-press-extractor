"""Synthetic press-release images with known answers, for end-to-end tests."""
from __future__ import annotations

import textwrap
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"


@dataclass
class Spec:
    name: str
    header: list[str]
    headline: str
    body: str
    expected_date: str
    expected_words: str
    lang: str = "en"
    must_flag: bool = False  # ambiguous by design: the row has to be sent for review


SPECS = [
    Spec(
        "classic",
        ["ROCHESTER INSTITUTE OF TECHNOLOGY", "News and Information Services", "",
         "FOR IMMEDIATE RELEASE", "May 3, 1987", "", "Contact: Jane Smith, 475-2400"],
        "RIT DEDICATES NEW IMAGING SCIENCE BUILDING",
        "ROCHESTER, N.Y. -- The Rochester Institute of Technology dedicated its new "
        "Center for Imaging Science on Friday, marking the completion of a project "
        "that began in 1984. More than 300 guests attended the ceremony.",
        "1987-05-03", "Rochester Institute of Technology dedicated",
    ),
    Spec(
        "release_label",
        ["ROCHESTER INSTITUTE OF TECHNOLOGY", "One Lomb Memorial Drive", "",
         "For release: Oct. 12, 1979", "", "Contact: Robert Jones"],
        "PHOTOGRAPHY STUDENTS WIN NATIONAL AWARDS",
        "ROCHESTER, N.Y. -- A team of photography students from the School of "
        "Photographic Arts and Sciences has won three national awards, the "
        "college announced today. The students will travel to New York City.",
        "1979-10-12", "team of photography students from",
    ),
    Spec(
        "french",
        ["ROCHESTER INSTITUTE OF TECHNOLOGY", "", "POUR DIFFUSION IMMEDIATE",
         "le 14 mars 1992"],
        "UNE DELEGATION DE RIT VISITE MONTREAL",
        "ROCHESTER, N.Y. -- L'université a annoncé aujourd'hui qu'une délégation "
        "de professeurs se rendra à Montréal pour une conférence sur la "
        "technologie et les arts graphiques dans le cadre d'un échange.",
        "1992-03-14", "université a annoncé aujourd'hui qu'une", lang="fr",
    ),
    Spec(
        "numeric_emdash",
        ["NEWS RELEASE", "Rochester Institute of Technology", "", "5/14/82"],
        "Library Exhibit Shows Rare Books",
        "ROCHESTER, N.Y. — An exhibit of rare books from the Cary Collection "
        "opens next week in Wallace Memorial Library and runs through June.",
        "1982-05-14", "exhibit of rare books from", must_flag=True,
    ),
    Spec(
        "no_dateline",
        ["ROCHESTER INSTITUTE OF TECHNOLOGY", "", "FOR RELEASE MONDAY, JUNE 2, 1975"],
        "COMMENCEMENT SET FOR SATURDAY",
        "The Rochester Institute of Technology will hold its annual commencement "
        "exercises on Saturday in the field house, with more than two thousand "
        "graduates expected to receive degrees.",
        "1975-06-02", "Rochester Institute of Technology will", must_flag=True,
    ),
]


def render(spec: Spec, width: int = 2550) -> Image.Image:
    """Render a US-letter page at ~300 dpi in a typewriter face."""
    height = int(width * 11 / 8.5)
    img = Image.new("RGB", (width, height), (250, 248, 240))
    d = ImageDraw.Draw(img)
    size = width // 60
    font, bold = ImageFont.truetype(FONT, size), ImageFont.truetype(FONT_BOLD, size)
    x, y, lh = width // 9, height // 12, int(size * 1.6)
    for line in spec.header:
        d.text((x, y), line, font=font, fill=(20, 20, 20))
        y += lh
    y += lh
    d.text((x, y), spec.headline, font=bold, fill=(20, 20, 20))
    y += 2 * lh
    chars = int((width - 2 * x) / (size * 0.6))
    for line in textwrap.wrap(spec.body, chars):
        d.text((x, y), line, font=font, fill=(20, 20, 20))
        y += int(lh * 1.4)
    return img


def as_phone_photo(page: Image.Image, rotate_exif_like: bool = False) -> Image.Image:
    """Simulate a handheld shot: page on a desk, perspective, shading, slight blur, JPEG-ish."""
    page = np.array(page.resize((page.width * 3 // 4, page.height * 3 // 4)))
    h, w = page.shape[:2]
    canvas_w, canvas_h = int(w * 1.35), int(h * 1.3)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[canvas_w * 0.14, canvas_h * 0.10], [canvas_w * 0.88, canvas_h * 0.07],
                      [canvas_w * 0.92, canvas_h * 0.92], [canvas_w * 0.10, canvas_h * 0.89]])
    desk = np.full((canvas_h, canvas_w, 3), (70, 55, 45), np.uint8)
    warped = cv2.warpPerspective(page, cv2.getPerspectiveTransform(src, dst), (canvas_w, canvas_h),
                                 dst=desk, borderMode=cv2.BORDER_TRANSPARENT)
    shade = np.linspace(1.0, 0.75, canvas_w)[None, :, None]
    warped = np.clip(warped * shade, 0, 255).astype(np.uint8)
    img = Image.fromarray(warped).filter(ImageFilter.GaussianBlur(1.2))
    return img
