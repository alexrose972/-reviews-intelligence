"""Dimension 3: Review Recency — 15pts."""

from datetime import datetime
from typing import List
from bs4 import BeautifulSoup
from ..utils import SCORE_WEIGHTS, extract_review_dates, parse_date

MAX_PTS = SCORE_WEIGHTS["review_recency"]


def score(pdp_htmls: List[str]) -> dict:
    now = datetime.utcnow()
    all_dates: List[datetime] = []
    for html in pdp_htmls:
        soup = BeautifulSoup(html, "lxml")
        for raw in extract_review_dates(soup):
            d = parse_date(raw)
            if d:
                all_dates.append(d)

    if not all_dates:
        return {
            "score": 3,
            "max_score": MAX_PTS,
            "finding": "Could not extract review dates from visible reviews.",
        }

    most_recent = max(all_dates)
    days_old = (now - most_recent).days

    if days_old <= 30:
        pts, label = MAX_PTS, "very fresh"
    elif days_old <= 60:
        pts, label = MAX_PTS * 0.8, "fresh"
    elif days_old <= 90:
        pts, label = MAX_PTS * 0.6, "acceptable"
    elif days_old <= 180:
        pts, label = MAX_PTS * 0.3, "stale"
    else:
        pts, label = 0, "very stale (180+ days)"

    return {
        "score": round(pts, 1),
        "max_score": MAX_PTS,
        "finding": (
            f"Most recent visible review: {days_old} days ago ({label}). "
            f"Checked {len(all_dates)} dated reviews."
        ),
    }
