"""Dimension 8: Stars on Category Pages — 4pts."""

from typing import Optional
from bs4 import BeautifulSoup

from ..utils import SCORE_WEIGHTS

MAX_PTS = SCORE_WEIGHTS["stars_on_category"]


def score(category_html: Optional[str], category_url: Optional[str] = None) -> dict:
    """
    Accepts Playwright-rendered category page HTML.
    JS-rendered star widgets (Yotpo, BV inline, etc.) are in the DOM.
    """
    if not category_html:
        return {
            "score": 0,
            "max_score": MAX_PTS,
            "finding": "Could not load a category/collection page.",
        }

    soup = BeautifulSoup(category_html, "lxml")

    # Broad match: any star/rating element visible on the page after JS
    if soup.select(
        "[class*='star' i], [class*='rating' i], "
        "[class*='bv-rating' i], [class*='pr-rating' i], "
        "[itemprop='ratingValue'], [class*='yotpo' i], "
        "[class*='okendo' i], [class*='stamped' i], [class*='judge-me' i]"
    ):
        path_note = f" ({category_url})" if category_url else ""
        return {
            "score": MAX_PTS,
            "max_score": MAX_PTS,
            "finding": f"Star ratings found on category page{path_note}.",
        }

    return {
        "score": 0,
        "max_score": MAX_PTS,
        "finding": "No star ratings on category pages. Adding them lifts PDP click-through ~30%.",
    }
