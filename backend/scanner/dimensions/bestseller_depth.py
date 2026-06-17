"""Dimension 7: Bestseller Depth — 8pts."""

import re
from typing import List
from bs4 import BeautifulSoup

from ..utils import SCORE_WEIGHTS

MAX_PTS = SCORE_WEIGHTS["bestseller_depth"]


def score(pdp_htmls: List[str]) -> dict:
    """
    Accepts Playwright-rendered HTML for the top PDPs.
    JS-rendered review counts (BazaarVoice, Yotpo, Okendo etc) are now in the DOM.
    Scores by how many of the top products have 50+ reviews.
    """
    if not pdp_htmls:
        return {"score": 0, "max_score": MAX_PTS, "finding": "No product pages could be rendered."}

    products_with_50plus = 0
    counts_found: List[int] = []

    for html in pdp_htmls:
        soup = BeautifulSoup(html, "lxml")
        page_text = soup.get_text(" ", strip=True)

        # Try specific review-count elements first
        count = None
        for el in soup.select(
            "[class*='review-count' i], [class*='reviewCount' i], "
            "[itemprop='reviewCount'], [class*='total-reviews' i], "
            "[class*='rating-count' i], [class*='bv-rating-count' i]"
        ):
            raw = el.get_text(strip=True)
            m = re.search(r"([\d,]+)", raw)
            if m:
                count = int(m.group(1).replace(",", ""))
                break

        # Fallback: first "NNN reviews" pattern in full page text
        if count is None:
            m = re.search(r"([\d,]+)\s*(?:reviews?|ratings?)", page_text, re.I)
            if m:
                count = int(m.group(1).replace(",", ""))

        if count is not None:
            counts_found.append(count)
            if count >= 50:
                products_with_50plus += 1

    total = len(pdp_htmls)
    if not counts_found:
        return {
            "score": 0,
            "max_score": MAX_PTS,
            "finding": "Per-product review counts weren’t readable from the product pages.",
        }

    avg_count = sum(counts_found) // len(counts_found)
    ratio = products_with_50plus / total
    return {
        "score": round(MAX_PTS * ratio, 1),
        "max_score": MAX_PTS,
        "finding": (
            f"{products_with_50plus}/{total} top products have 50+ reviews "
            f"(avg {avg_count} reviews). "
            + ("Strong review depth." if ratio >= 0.8 else
               "Most top SKUs need more reviews to rank and convert.")
        ),
    }
