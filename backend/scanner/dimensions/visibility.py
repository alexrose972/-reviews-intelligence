"""Dimension 4: Visibility / Discoverability — 12pts."""

from typing import List, Optional
from bs4 import BeautifulSoup

from ..utils import SCORE_WEIGHTS

MAX_PTS = SCORE_WEIGHTS["visibility"]


def score(
    homepage_html: str,
    pdp_htmls: List[str],
    reviews_page_html: Optional[str] = None,
) -> dict:
    """
    All inputs are Playwright-rendered HTML — JS review widgets are present.
    Sub-signals:
      +5  Star ratings / review widget visible on any PDP (JS-rendered)
      +3  Nav/header contains a link to reviews or testimonials
      +4  A dedicated /reviews or /testimonials page exists with content
    """
    pts = 0.0
    notes: List[str] = []

    # Stars / ratings present on any PDP after full JS render
    for html in pdp_htmls:
        soup = BeautifulSoup(html, "lxml")
        if soup.select(
            "[class*='star' i], [class*='rating' i], [itemprop='ratingValue'], "
            "[class*='bv-rating' i], [class*='pr-rating' i], "
            "[class*='yotpo' i], [class*='okendo' i], [class*='stamped' i], "
            "[class*='judge-me' i], [class*='loox' i], [class*='reviews-io' i]"
        ):
            pts += 5
            notes.append("star ratings / review widget present on PDPs")
            break

    # Nav link pointing to reviews or testimonials
    soup_home = BeautifulSoup(homepage_html, "lxml")
    nav_text = " ".join(
        t.get_text(strip=True).lower()
        for t in soup_home.find_all(["nav", "header"])
    )
    if "review" in nav_text or "testimonial" in nav_text:
        pts += 3
        notes.append("nav link to reviews")

    # Dedicated reviews page passed in from engine
    if reviews_page_html and len(reviews_page_html) > 1000:
        pts += 4
        notes.append("dedicated reviews page exists")

    return {
        "score": round(min(pts, MAX_PTS), 1),
        "max_score": MAX_PTS,
        "finding": (
            ", ".join(notes) if notes
            else "No review widgets found on PDPs, no nav link, no standalone reviews page."
        ),
    }