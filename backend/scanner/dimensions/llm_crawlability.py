"""Dimension 1: LLM Crawlability / AEO — 20pts.

Measures whether an AI assistant or search crawler can actually READ the brand's
reviews from the page: structured data (AggregateRating / Review JSON-LD) plus
review text present in the rendered HTML (not locked behind a JS-only widget).

We deliberately do NOT ask a no-web-tool model to "quote a review" — it always
refuses ("I can't browse the internet"), which measures the probe, not the site.
"""

import logging
import os
import re
from typing import Optional

from ..utils import (
    SCORE_WEIGHTS, clean_domain, extract_jsonld,
    has_aggregate_rating, has_review_schema, has_microdata_rating, extract_review_texts,
)
from bs4 import BeautifulSoup

log = logging.getLogger("scanner.llm_crawlability")
MAX_PTS = SCORE_WEIGHTS["llm_crawlability"]


def _ground_truth(soup: BeautifulSoup) -> str:
    """Build review ground-truth text for the AEO judge from the page."""
    texts = extract_review_texts(soup)
    parts = list(texts[:15])
    page_txt = soup.get_text(" ", strip=True)
    m = re.search(r"(\d[\d,]*)\s*(?:reviews?|ratings?)", page_txt, re.I)
    if m:
        parts.append(f"Visible review count: {m.group(1)}.")
    rv = soup.select_one('[itemprop="ratingValue"]')
    if rv:
        parts.append(f"Visible rating value: {rv.get('content') or rv.get_text(strip=True)}.")
    return "\n".join(parts)


async def score(domain_url: str, rendered_html: str, skip_llm: bool = False,
                brand: str = "", product_url: str = "") -> dict:
    html = rendered_html or ""
    jsonld = extract_jsonld(html) if html else []
    _soup = BeautifulSoup(html, "lxml") if html else None
    # AggregateRating via JSON-LD OR microdata (BazaarVoice & co. use microdata).
    has_agg = has_aggregate_rating(jsonld) or (bool(_soup) and has_microdata_rating(_soup))
    has_rev = has_review_schema(jsonld)

    n_texts = 0
    if html:
        try:
            n_texts = len(extract_review_texts(_soup))
        except Exception:
            n_texts = 0

    pts = 0.0
    if has_agg:
        pts += 8
    if has_rev:
        pts += 6
    if n_texts >= 5:
        pts += 6
    elif n_texts >= 1:
        pts += 3

    pts = round(min(pts, MAX_PTS), 1)
    dom = clean_domain(domain_url)

    have, missing = [], []
    (have if has_agg else missing).append("AggregateRating schema")
    (have if has_rev else missing).append("Review schema")
    (have if n_texts else missing).append("review text in page HTML")

    if pts >= 14:
        finding = (
            f"Reviews on {dom} are machine-readable ("
            + ", ".join(have) + f"; {n_texts} review snippets in the HTML). "
            "ChatGPT, Perplexity, Gemini and Google rich results can read them."
        )
    elif pts >= 6:
        finding = (
            f"Partial AI crawlability on {dom}: has " + ", ".join(have)
            + (". Missing " + ", ".join(missing) if missing else ".")
            + " Adding the rest makes reviews fully readable by AI and Google."
        )
    else:
        finding = (
            f"Reviews on {dom} are not machine-readable (missing "
            + ", ".join(missing) + "). They're effectively invisible to "
            "ChatGPT, Perplexity, Gemini, and Google rich results."
        )

    static = {
        "score": pts,
        "max_score": MAX_PTS,
        "finding": finding,
        "review_quote": "",      # kept for downstream compatibility — never a refusal
        "complaint_quote": "",
        "failed": False,
        "has_schema": has_agg or has_rev,
        "review_texts_in_html": n_texts,
    }

    # ── Live AEO probe ────────────────────────────────────────────────────────
    # When enabled, actually ask a web-search AI the canonical review questions
    # and judge its answers against the page's review content. This measures real
    # AI readability, not just schema presence. Falls back to `static` on any issue.
    if (not skip_llm and os.environ.get("ANTHROPIC_API_KEY")
            and os.environ.get("AEO_PROBE", "true").lower() == "true" and html):
        try:
            soup = BeautifulSoup(html, "lxml")
            gt = _ground_truth(soup)
            if gt.strip():  # only probe when the page actually exposes review content
                from ..aeo_probe import run_aeo_probe
                title = (soup.title.string or "")[:120] if soup.title else ""
                aeo = await run_aeo_probe(
                    product_url or domain_url, brand or clean_domain(domain_url), gt, title, MAX_PTS
                )
                if aeo:
                    aeo.update({"review_quote": "", "complaint_quote": "", "failed": False,
                                "has_schema": has_agg or has_rev, "review_texts_in_html": n_texts})
                    return aeo
        except Exception as exc:
            log.warning("AEO probe failed, using static crawlability score: %s", exc)

    return static
