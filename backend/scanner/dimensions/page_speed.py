"""Dimension 6: Page Speed — 10pts (Google PageSpeed Insights)."""

import os
from typing import Optional, Tuple

import httpx

from ..utils import SCORE_WEIGHTS, HEAVY_PLATFORMS

MAX_PTS = SCORE_WEIGHTS["page_speed"]
PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


async def score(
    page_url: str,
    client: httpx.AsyncClient,
    detected_platform: Optional[str],
) -> dict:
    api_key = os.environ.get("GOOGLE_PAGESPEED_API_KEY", "")
    params = {"url": page_url, "strategy": "mobile", "category": "performance"}
    if api_key:
        params["key"] = api_key

    try:
        r = await client.get(PSI_URL, params=params, timeout=35.0)
        data = r.json()
        cats   = data.get("lighthouseResult", {}).get("categories", {})
        audits = data.get("lighthouseResult", {}).get("audits", {})
        perf   = cats.get("performance", {}).get("score")
        lcp    = audits.get("largest-contentful-paint", {}).get("displayValue", "")
        fcp    = audits.get("first-contentful-paint", {}).get("displayValue", "")
        tbt    = audits.get("total-blocking-time", {}).get("displayValue", "")
    except Exception:
        return {
            "score": round(MAX_PTS * 0.5, 1),
            "max_score": MAX_PTS,
            "finding": "Page speed not measured (set GOOGLE_PAGESPEED_API_KEY for a live mobile score).",
            "perf_score": None, "lcp": "", "fcp": "", "tbt": "",
        }

    if perf is None:
        # Unmeasured (no key / quota). Don't fabricate a low score — neutral
        # placeholder, clearly flagged, and the pitch must not claim "slow".
        return {
            "score": round(MAX_PTS * 0.5, 1), "max_score": MAX_PTS,
            "finding": "Page speed not measured (set GOOGLE_PAGESPEED_API_KEY for a live mobile score).",
            "perf_score": None, "lcp": "", "fcp": "", "tbt": "",
        }

    pct = perf * 100
    if pct >= 90:    pts = MAX_PTS
    elif pct >= 75:  pts = MAX_PTS * 0.75
    elif pct >= 50:  pts = MAX_PTS * 0.5
    elif pct >= 25:  pts = MAX_PTS * 0.25
    else:            pts = 0.0

    notes = [f"Mobile score: {pct:.0f}/100. LCP: {lcp}, FCP: {fcp}, TBT: {tbt}."]
    if detected_platform in HEAVY_PLATFORMS:
        pts = max(0, pts - 2)
        notes.append(
            f"{detected_platform} detected — known heavy review platform. "
            "Every 100ms of delay costs ~1% conversion."
        )

    return {
        "score": round(min(pts, MAX_PTS), 1),
        "max_score": MAX_PTS,
        "finding": " ".join(notes),
        "perf_score": round(pct, 1),
        "lcp": lcp, "fcp": fcp, "tbt": tbt,
    }
