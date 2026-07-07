"""
Full LLM-crawlability report.

Extends the single-product AEO probe (aeo_probe.py) into the multi-PDP report
shape of YotpoLtd/llm-report-generator: for every product page we render, ask a
web-search LLM the canonical review questions and judge each answer 0-5 against
the page's own review content. Roll the per-PDP results up into metrics
(discovery hit rate, found %, refusals, mean score) + a PDP leaderboard, and feed
the aggregate back into the 'AI & LLM Readability' dimension score.

Model-agnostic by construction: the report data nests companies -> models -> pdps,
so ChatGPT/Gemini can be added later as extra models without changing the shape.
Today it runs one model, Claude (web search), on the key the tool already has.

Fully defensive: no key / any failure -> returns None and the caller keeps the
static crawlability score.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import anthropic

from .aeo_probe import QUESTIONS, _answer, _judge

log = logging.getLogger("scanner.llm_report")

MODEL_LABEL = "Claude"
MODEL_KEY = "claude"
_MAX_CONCURRENCY = int(os.environ.get("LLM_REPORT_CONCURRENCY", "5"))


async def _eval_pdp(client, sem, brand: str, pdp: dict) -> dict:
    """Run every question against one PDP; return per-question judgements."""
    async def one(q):
        async with sem:
            try:
                ans = await _answer(client, pdp["url"], brand, q)
            except Exception as exc:
                log.warning("answer failed [%s]: %s", q[:40], exc)
                return None
            try:
                return await _judge(client, q, ans, pdp.get("ground_truth", "") or "",
                                    pdp.get("title", ""))
            except Exception as exc:
                log.warning("judge failed [%s]: %s", q[:40], exc)
                return None

    results = await asyncio.gather(*[one(q) for q in QUESTIONS])
    questions = [r for r in results if isinstance(r, dict)]
    evaluable = [r for r in questions if r.get("found_in_page")]
    avg = round(sum(r["score"] for r in evaluable) / len(evaluable), 2) if evaluable else None
    return {
        "label": pdp.get("label") or pdp.get("url", ""),
        "url": pdp.get("url", ""),
        "avg_score": avg,
        "questions": questions,
        "evaluable": len(evaluable),
    }


def _metrics(pdps: List[dict]) -> dict:
    all_q = [q for p in pdps for q in p["questions"]]
    evaluable = [q for q in all_q if q.get("found_in_page")]
    found = len(evaluable)
    refusals = sum(1 for q in evaluable if q.get("refusal"))
    mean = round(sum(q["score"] for q in evaluable) / found, 2) if found else 0.0
    return {
        "pdps": len(pdps),
        "questions_judged": len(all_q),
        "found": found,
        "found_pct": round(found / len(all_q) * 100) if all_q else 0,
        "refusals": refusals,
        "mean_score": mean,  # 0-5, found only
    }


def _dimension(metrics: dict, max_pts: int) -> dict:
    """Turn the aggregate into the 'AI & LLM Readability' dimension score/finding."""
    found = metrics["found"]
    if not found:
        return None  # nothing evaluable — let the static scorer stand
    mean = metrics["mean_score"]
    score = round(mean / 5 * max_pts, 1)
    well = None  # computed by caller if needed
    if score >= max_pts * 0.7:
        finding = (f"AI assistants can read this brand's reviews: across {metrics['pdps']} product "
                   f"pages a web-search AI scored {mean:.1f}/5 on the review questions it could verify.")
    elif metrics["refusals"] or score < max_pts * 0.3:
        finding = (f"AI assistants struggle to read this brand's reviews: across {metrics['pdps']} product "
                   f"pages a web-search AI scored just {mean:.1f}/5 and "
                   f"{'refused on some, ' if metrics['refusals'] else ''}"
                   f"missed most review questions. Largely invisible to ChatGPT, Perplexity, and Gemini.")
    else:
        finding = (f"Partial AI readability: across {metrics['pdps']} product pages a web-search AI "
                   f"scored {mean:.1f}/5 on the review questions it could verify; the rest were wrong or vague.")
    return {"score": score, "max_score": max_pts, "finding": finding, "measured": True}


async def run_llm_report(brand: str, pdps: List[dict], max_pts: int = 20) -> Optional[dict]:
    """pdps: [{url, label, title, ground_truth}]. Returns {dimension, report} or None."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    pdps = [p for p in (pdps or []) if p.get("url")]
    if not key or not pdps:
        return None
    client = anthropic.AsyncAnthropic(api_key=key)
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    try:
        evaluated = await asyncio.gather(*[_eval_pdp(client, sem, brand, p) for p in pdps])
    except Exception as exc:
        log.warning("LLM report failed: %s", exc)
        return None
    evaluated = [e for e in evaluated if e and e["questions"]]
    if not evaluated:
        return None

    metrics = _metrics(evaluated)
    dimension = _dimension(metrics, max_pts)
    leaderboard = sorted(
        [{"label": p["label"], "url": p["url"], "avg_score": p["avg_score"]} for p in evaluated],
        key=lambda x: (x["avg_score"] is None, -(x["avg_score"] or 0)),
    )
    report = {
        "brand": brand,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "companies": [{
            "name": brand,
            "default_model": MODEL_KEY,
            "models": {MODEL_KEY: {
                "label": MODEL_LABEL,
                "metrics": metrics,
                "pdps": evaluated,
                "leaderboard": leaderboard,
            }},
        }],
        "overall_metrics": {"companies": 1, **metrics},
    }
    return {"dimension": dimension, "report": report}
