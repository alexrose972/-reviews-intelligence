"""
Live AEO / LLM-crawlability probe.

Adapted from YotpoLtd/llm-report-generator: ask a web-search-enabled LLM the
canonical review questions about a product, then judge each answer 0–5 against
the page's actual review content (ground truth) using the same rubric. This
measures what an AI assistant ACTUALLY sees about the brand's reviews — far
stronger than a schema-presence proxy.

Fully defensive: any failure (no key, web search unavailable, parse error)
returns None so the caller falls back to the static crawlability score.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import List, Optional

import anthropic

log = logging.getLogger("scanner.aeo")

ANSWER_MODEL = os.environ.get("AEO_ANSWER_MODEL", "claude-sonnet-4-6")
JUDGE_MODEL = os.environ.get("AEO_JUDGE_MODEL", "claude-sonnet-4-6")

# Focused subset of the report-generator's questions — the highest-signal ones,
# kept small to bound per-scan cost/latency.
QUESTIONS = [
    "How many customer reviews does this product have? Reply with the exact count as shown.",
    "What is the overall star rating for this product? Reply with the number only, or N/A if not shown.",
    "What do customers most commonly say about this product in its reviews? Be specific.",
    "Does this product page have an AI-generated review summary or a highlights/'customers say' block? Reply Yes or No.",
]

# Judge rubric — ported from analyzer.py (llm-report-generator).
_JUDGE_SYSTEM = """You are an impartial evaluator measuring factual alignment between an LLM Answer and Ground Truth (GT) scraped from a live product page, for one question.

STEP 1: Read the LLM Answer literally. Find the exact evidence in the GT (text/number/signal). If absent, note it.

STEP 2 — SCORING (0–5):
- 5: fully correct vs GT.
- 4: essentially correct (minor wording/rounding). Numeric within ~5% of GT = 4.
- 3: partially correct / within ~30%.
- 2: mostly wrong, core claim unsupported.
- 1: completely wrong, fabricated, or a refusal. False absence ("0"/"no reviews"/"N/A") when GT shows a real value = 1 (never higher).
- 0: unevaluable — GT contains no usable evidence for this question.

STEP 3 — FLAGS:
- found_in_page: true only if GT actually contains the material to verify this question (a correct "No" when GT clearly lacks that block also counts). When in doubt, false.
- llm_refusal: true if the LLM says it can't access/view/browse/open the page instead of answering.

STEP 4 — OVERRIDES: if found_in_page is false → score MUST be 0. If llm_refusal is true AND found_in_page true → score MUST be 1.

Respond with ONLY JSON: {"score": <0-5 int>, "explanation": "<short>", "found_in_page": <bool>, "llm_refusal": <bool>}"""

_REFUSAL = re.compile(r"\b(can.?t|cannot|unable to|not able to|don.?t have the ability to)\b.{0,30}\b(access|view|browse|open|visit|see|load|retrieve|fetch)\b", re.I)


def _truncate(t: str, n: int = 18000) -> str:
    return t if len(t) <= n else t[:n] + " […]"


async def _answer(client: anthropic.AsyncAnthropic, product_url: str, brand: str, question: str) -> str:
    """Ask the model the question WITH web search enabled."""
    try:
        resp = await client.messages.create(
            model=ANSWER_MODEL,
            max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": (
                f"For the product at {product_url} (brand: {brand}), answer using current web information: "
                f"{question}"
            )}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:
        log.warning("AEO answer failed [%s]: %s", question[:40], exc)
        raise


async def _judge(client: anthropic.AsyncAnthropic, question: str, answer: str, gt: str, title: str) -> dict:
    resp = await client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=400,
        system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": (
            f"## Question\n{question}\n\n## LLM Answer\n{answer}\n\n"
            f"## Ground Truth (page title: {title})\n{_truncate(gt)}"
        )}],
    )
    raw = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}
    score = max(0, min(5, int(data.get("score", 0))))
    found = bool(data.get("found_in_page", False))
    refusal = bool(data.get("llm_refusal", False)) or bool(_REFUSAL.search(answer or ""))
    if not found:
        score = 0
    elif refusal and score > 1:
        score = 1
    return {"question": question, "answer": answer[:300], "score": score,
            "found_in_page": found, "refusal": refusal, "explanation": data.get("explanation", "")}


async def run_aeo_probe(product_url: str, brand: str, ground_truth: str,
                        page_title: str = "", max_pts: int = 20) -> Optional[dict]:
    """Return {score, max_score, finding, per_question, failed} or None on failure."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not product_url:
        return None
    client = anthropic.AsyncAnthropic(api_key=key)

    async def one(q):
        ans = await _answer(client, product_url, brand, q)
        return await _judge(client, q, ans, ground_truth or "", page_title)

    try:
        results = await asyncio.gather(*[one(q) for q in QUESTIONS], return_exceptions=True)
    except Exception as exc:
        log.warning("AEO probe failed: %s", exc)
        return None

    judged = [r for r in results if isinstance(r, dict)]
    if not judged:
        return None

    evaluable = [r for r in judged if r["found_in_page"]]
    if not evaluable:
        # Nothing to evaluate from the page — let the static scorer decide.
        return None

    avg = sum(r["score"] for r in evaluable) / len(evaluable)   # 0–5
    score = round(avg / 5 * max_pts, 1)
    refusals = sum(1 for r in evaluable if r["refusal"])
    answered_well = sum(1 for r in evaluable if r["score"] >= 4)

    if score >= max_pts * 0.7:
        finding = (f"AI assistants can read this brand's reviews: a web-search AI answered "
                   f"{answered_well}/{len(evaluable)} review questions correctly against the live page.")
    elif refusals or score < max_pts * 0.3:
        finding = (f"AI assistants struggle to read this brand's reviews — a web-search AI got "
                   f"{answered_well}/{len(evaluable)} review questions right and "
                   f"{'refused/' if refusals else ''}missed the rest. Largely invisible to ChatGPT, Perplexity, and Gemini.")
    else:
        finding = (f"Partial AI readability: a web-search AI answered {answered_well}/{len(evaluable)} "
                   f"review questions correctly against the live page; the rest were wrong or vague.")

    return {"score": score, "max_score": max_pts, "finding": finding,
            "per_question": judged, "failed": False}
