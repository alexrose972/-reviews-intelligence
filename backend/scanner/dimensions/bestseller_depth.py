"""Dimension 7: Bestseller Depth — 8pts."""

import re
from typing import List

import httpx
from bs4 import BeautifulSoup

from ..utils import SCORE_WEIGHTS, fetch_html, find_bestseller_urls, find_pdp_urls

MAX_PTS = SCORE_WEIGHTS["bestseller_depth"]


async def score(base_url: str, client: httpx.AsyncClient) -> dict:
    pages = await find_bestseller_urls(client, base_url)
    if not pages:
        return {"score": 0, "max_score": MAX_PTS, "finding": "Could not reach bestseller pages."}

    pdp_urls: List[str] = []
    for page_url, html in pages:
        pdp_urls.extend(await find_pdp_urls(client, base_url, html))
        if len(pdp_urls) >= 5:
            break
    pdp_urls = pdp_urls[:5]

    if not pdp_urls:
        return {"score": 0, "max_score": MAX_PTS, "finding": "No product pages found."}

    products_with_50plus = 0
    total_checked = 0
    for url in pdp_urls:
        html = await fetch_html(client, url)
        if not html:
            continue
        total_checked += 1
        soup = BeautifulSoup(html, "lxml")
        count_text = ""
        for el in soup.select("[class*='review-count'],[class*='reviewCount'],[itemprop='reviewCount']"):
            count_text = el.get_text(strip=True)
            break
        m = re.search(r"(\d+)\s*(?:reviews?|ratings?)", soup.get_text(), re.I)
        if m:
            count_text = m.group(1)
        try:
            if int(re.sub(r"[^\d]", "", count_text)) >= 50:
                products_with_50plus += 1
        except Exception:
            pass

    if not total_checked:
        return {"score": 0, "max_score": MAX_PTS, "finding": "Could not fetch product pages."}

    ratio = products_with_50plus / total_checked
    return {
        "score": round(MAX_PTS * ratio, 1),
        "max_score": MAX_PTS,
        "finding": f"{products_with_50plus}/{total_checked} top products have 50+ reviews ({ratio*100:.0f}%).",
    }
