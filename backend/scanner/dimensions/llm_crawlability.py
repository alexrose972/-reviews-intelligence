"""Dimension 1: LLM Crawlability — 20pts."""

import os
from typing import Optional

import anthropic
import httpx

from ..utils import SCORE_WEIGHTS, clean_domain, extract_jsonld, has_aggregate_rating, has_review_schema

MAX_PTS = SCORE_WEIGHTS["llm_crawlability"]

VAGUE_SIGNALS = [
    "i cannot", "i can't", "i don't have", "unable to access", "i'm not able",
    "as an ai", "no access", "cannot browse", "don't have real-time", "can't browse",
    "i apologize", "i'm unable", "not able to access",
]


async def score(
    domain_url: str,
    client: httpx.AsyncClient,
    skip_llm: bool = False,
) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    homepage_html = ""
    try:
        r = await client.get(domain_url, timeout=20)
        homepage_html = r.text
    except Exception:
        pass

    jsonld = extract_jsonld(homepage_html) if homepage_html else []
    has_schema = has_aggregate_rating(jsonld) or has_review_schema(jsonld)

    if skip_llm or not api_key:
        pts = (MAX_PTS * 0.5) + (6 if has_schema else 0)
        pts = min(pts, MAX_PTS)
        return {
            "score": round(pts, 1),
            "max_score": MAX_PTS,
            "finding": "LLM probe skipped. " + ("Schema markup: present." if has_schema else "Schema markup: missing."),
            "review_quote": "",
            "complaint_quote": "",
            "failed": False,
        }

    aclient = anthropic.Anthropic(api_key=api_key)
    quote_response = ""
    complaint_response = ""
    llm_failed = False
    pts = 0.0

    try:
        msg1 = aclient.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": (
                f"Please quote the exact text of the first customer review on {domain_url} "
                "for their best-selling product. Copy the review word-for-word."
            )}],
        )
        quote_response = msg1.content[0].text.strip()
        quote_failed = any(s in quote_response.lower() for s in VAGUE_SIGNALS)

        msg2 = aclient.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": (
                f"What is the most common complaint customers mention in reviews on "
                f"{domain_url}? Be specific. Name the actual complaint."
            )}],
        )
        complaint_response = msg2.content[0].text.strip()
        complaint_vague = any(s in complaint_response.lower() for s in VAGUE_SIGNALS)

        if not quote_failed:
            pts += 8
        if not complaint_vague:
            pts += 6
        if has_schema:
            pts += 6

        if quote_failed and complaint_vague:
            llm_failed = True
            finding = (
                f"Claude cannot read reviews on {clean_domain(domain_url)}. "
                f"When asked to quote a review, it said: \"{quote_response[:120]}...\""
            )
        else:
            finding = (
                f"Claude {'can' if not quote_failed else 'cannot'} quote reviews. "
                f"Schema: {'present' if has_schema else 'missing'}."
            )
    except Exception as e:
        pts = MAX_PTS * 0.4
        llm_failed = True
        finding = f"LLM probe error: {e}"

    return {
        "score": round(min(pts, MAX_PTS), 1),
        "max_score": MAX_PTS,
        "finding": finding,
        "review_quote": quote_response,
        "complaint_quote": complaint_response,
        "failed": llm_failed,
    }
