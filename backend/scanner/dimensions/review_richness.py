"""Dimension 2: Review Richness — 18pts."""

from typing import List
from bs4 import BeautifulSoup
from ..utils import SCORE_WEIGHTS, extract_review_texts

MAX_PTS = SCORE_WEIGHTS["review_richness"]


def score(pdp_htmls: List[str]) -> dict:
    all_reviews: List[str] = []
    for html in pdp_htmls:
        soup = BeautifulSoup(html, "lxml")
        all_reviews.extend(extract_review_texts(soup))

    if not all_reviews:
        return {
            "score": 0,
            "max_score": MAX_PTS,
            "finding": "No review text was readable on the product pages.",
        }

    word_counts = [len(r.split()) for r in all_reviews]
    avg_words = sum(word_counts) / len(word_counts)
    pct_thin = sum(1 for w in word_counts if w < 5) / len(word_counts)
    total_vol = len(all_reviews)

    pts = 0.0
    if avg_words >= 40:   pts += 8
    elif avg_words >= 25: pts += 5
    elif avg_words >= 15: pts += 2
    if pct_thin < 0.05:   pts += 5
    elif pct_thin < 0.15: pts += 3
    elif pct_thin < 0.30: pts += 1
    if total_vol >= 20:   pts += 5
    elif total_vol >= 10: pts += 3
    elif total_vol >= 5:  pts += 1

    return {
        "score": round(pts, 1),
        "max_score": MAX_PTS,
        "finding": (
            f"Found {total_vol} visible reviews. "
            f"Avg length: {avg_words:.0f} words. "
            f"{pct_thin*100:.0f}% under 5 words."
        ),
    }
