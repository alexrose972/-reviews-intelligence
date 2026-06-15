"""Dimension 4: Visibility / Discoverability — 12pts."""

from typing import List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..utils import SCORE_WEIGHTS, fetch_html

MAX_PTS = SCORE_WEIGHTS["visibility"]


async def score(
    base_url: str,
    client: httpx.AsyncClient,
    homepage_html: str,
    pdp_htmls: List[str],
) -> dict:
    pts = 0.0
    notes = []

    # Stars above fold on PDPs
    for html in pdp_htmls:
        soup = BeautifulSoup(html, "lxml")
        if soup.select("[class*='star'], [class*='rating'], [itemprop='ratingValue']"):
            pts += 5
            notes.append("stars visible on PDPs")
            break

    # Nav link to reviews
    soup_home = BeautifulSoup(homepage_html, "lxml")
    nav_text = " ".join(
        t.get_text(strip=True).lower() for t in soup_home.find_all(["nav", "header"])
    )
    if "review" in nav_text or "testimonial" in nav_text:
        pts += 3
        notes.append("nav link to reviews")

    # Dedicated reviews page
    for path in ["/reviews", "/testimonials", "/customer-reviews"]:
        html = await fetch_html(client, urljoin(base_url, path))
        if html and len(html) > 1000:
            pts += 4
            notes.append(f"dedicated reviews page at {path}")
            break

    return {
        "score": round(pts, 1),
        "max_score": MAX_PTS,
        "finding": ", ".join(notes) if notes else "No star ratings above fold, no nav link, no reviews page found.",
    }
