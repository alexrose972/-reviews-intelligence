"""Dimension 1: LLM Crawlability / AEO — 20pts.

Measures whether an AI assistant or search crawler can actually READ the brand's
reviews from the page: structured data (AggregateRating / Review JSON-LD) plus
review text present in the rendered HTML (not locked behind a JS-only widget).

We deliberately do NOT ask a no-web-tool model to "quote a review" — it always
refuses ("I can't browse the internet"), which measures the probe, not the site.
"""

from typing import Optional

from ..utils import (
    SCORE_WEIGHTS, clean_domain, extract_jsonld,
    has_aggregate_rating, has_review_schema, extract_review_texts,
)
from bs4 import BeautifulSoup

MAX_PTS = SCORE_WEIGHTS["llm_crawlability"]


async def score(domain_url: str, rendered_html: str, skip_llm: bool = False) -> dict:
    html = rendered_html or ""
    jsonld = extract_jsonld(html) if html else []
    has_agg = has_aggregate_rating(jsonld)
    has_rev = has_review_schema(jsonld)

    n_texts = 0
    if html:
        try:
            n_texts = len(extract_review_texts(BeautifulSoup(html, "lxml")))
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

    return {
        "score": pts,
        "max_score": MAX_PTS,
        "finding": finding,
        "review_quote": "",      # kept for downstream compatibility — never a refusal
        "complaint_quote": "",
        "failed": False,
        "has_schema": has_agg or has_rev,
        "review_texts_in_html": n_texts,
    }
