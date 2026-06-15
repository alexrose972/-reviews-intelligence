"""Dimension 5: Rich Snippets — 10pts."""

from typing import List
from bs4 import BeautifulSoup
from ..utils import (
    SCORE_WEIGHTS, extract_jsonld,
    has_aggregate_rating, has_review_schema, has_microdata_rating,
)

MAX_PTS = SCORE_WEIGHTS["rich_snippets"]


def score(pdp_htmls: List[str], homepage_html: str) -> dict:
    has_jsonld = False
    has_micro = False

    for html in ([homepage_html] + pdp_htmls):
        if not html:
            continue
        jsonld = extract_jsonld(html)
        if has_aggregate_rating(jsonld):
            has_jsonld = True
        soup = BeautifulSoup(html, "lxml")
        if has_microdata_rating(soup):
            has_micro = True
        if has_jsonld:
            break

    if has_jsonld:
        return {
            "score": MAX_PTS,
            "max_score": MAX_PTS,
            "finding": "AggregateRating JSON-LD found. Google SERP stars are enabled.",
        }
    if has_micro:
        return {
            "score": round(MAX_PTS * 0.7, 1),
            "max_score": MAX_PTS,
            "finding": "Microdata AggregateRating found (no JSON-LD). SERP stars may be inconsistent.",
        }
    return {
        "score": 0,
        "max_score": MAX_PTS,
        "finding": "No AggregateRating schema found. Missing star ratings in Google search results.",
    }
