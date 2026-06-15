"""Dimension 8: Stars on Category Pages — 4pts."""

from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..utils import SCORE_WEIGHTS, fetch_html

MAX_PTS = SCORE_WEIGHTS["stars_on_category"]

CAT_PATHS = ["/collections/all", "/collections", "/shop", "/category", "/categories", "/products"]


async def score(base_url: str, client: httpx.AsyncClient) -> dict:
    for path in CAT_PATHS:
        html = await fetch_html(client, urljoin(base_url, path))
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        if soup.select("[class*='star'],[class*='rating'],[class*='bv-rating'],[class*='pr-rating']"):
            return {
                "score": MAX_PTS,
                "max_score": MAX_PTS,
                "finding": f"Star ratings found on {path}. Benchmark: True Religion /denim-view-all-womens.",
            }
    return {
        "score": 0,
        "max_score": MAX_PTS,
        "finding": "No star ratings found on category pages. Adding them lifts PDP click-through ~30%.",
    }
