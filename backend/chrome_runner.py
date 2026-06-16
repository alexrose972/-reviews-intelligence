"""
Browser Scan runner — runs on YOUR Mac, NOT on Railway.

Railway scans from a datacenter IP with headless Chromium, so premium DTC sites
(Cloudflare / PerimeterX / DataDome) block it. This runner performs the exact
same audit from your real, local Chrome — a residential IP and a genuine browser
fingerprint — so the sites that block the server can finally be scored.

It is a thin pull-loop:
  1. Claim the next queued Browser Scan job from the app.
  2. Run the normal PlaywrightAuditor extraction, but in a real/attached Chrome.
  3. POST the structured result to the existing /api/browser-data webhook, which
     scores every dimension, builds the brief, and notifies the UI.

Usage (from the repo root):
    export API_BASE_URL=https://reviews-intelligence-production.up.railway.app
    export BROWSER_WEBHOOK_SECRET=...        # must match the value set on Railway
    python -m backend.chrome_runner

Optional:
    # Attach to a Chrome you launched yourself (uses your real logged-in profile):
    #   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
    #     --remote-debugging-port=9222
    export CHROME_CDP_URL=http://localhost:9222

    export GOOGLE_PAGESPEED_API_KEY=...      # enables the Page Speed dimension
    export RUNNER_POLL_SECONDS=8             # how often to poll for work
"""

from __future__ import annotations

import os
import tempfile

# Screenshots must land somewhere writable on a Mac (module default is
# /screenshots). Set this BEFORE importing the browser module, which reads it.
os.environ.setdefault(
    "SCREENSHOTS_DIR", os.path.join(tempfile.gettempdir(), "ri_runner_shots")
)

import asyncio
import base64
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from .scanner.browser import PlaywrightAuditor, detect_block
from .scanner.utils import (
    detect_platform, detect_vertical, extract_jsonld,
    has_aggregate_rating, has_review_schema, domain_to_url,
    VERTICAL_SIGNALS_MAP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chrome_runner")

API_BASE = os.environ.get(
    "API_BASE_URL",
    "https://reviews-intelligence-production.up.railway.app",
).rstrip("/")
SECRET = os.environ.get("BROWSER_WEBHOOK_SECRET", "")
CDP_URL = os.environ.get("CHROME_CDP_URL") or None
PSI_KEY = os.environ.get("GOOGLE_PAGESPEED_API_KEY", "")
POLL = int(os.environ.get("RUNNER_POLL_SECONDS", "8"))


class BrowserScanBlocked(RuntimeError):
    """The real browser still received a block/challenge page."""


def _b64_file(path: str) -> str:
    try:
        return base64.b64encode(Path(path).read_bytes()).decode()
    except Exception:
        return ""


def _vertical_signals_found(vertical: str, text: str) -> list:
    if not vertical:
        return []
    low = text.lower()
    return [s for s in VERTICAL_SIGNALS_MAP.get(vertical, []) if s in low][:6]


def _product_name_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return unquote(slug).replace("-", " ").replace("_", " ").strip().title()


async def claim_job(api: httpx.AsyncClient) -> dict | None:
    r = await api.post(
        f"{API_BASE}/api/chrome-jobs/next",
        headers={"X-Webhook-Secret": SECRET},
    )
    r.raise_for_status()
    return r.json().get("job")


async def post_results(api: httpx.AsyncClient, scan_id: str, payload: dict):
    r = await api.post(
        f"{API_BASE}/api/browser-data/{scan_id}",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )
    r.raise_for_status()


async def report_failure(api: httpx.AsyncClient, job: dict, error: str, blocked: bool = False):
    job_id = job.get("id")
    if not job_id:
        return
    try:
        r = await api.post(
            f"{API_BASE}/api/chrome-jobs/{job_id}/fail",
            json={"error": error, "blocked": blocked},
            headers={"X-Webhook-Secret": SECRET},
        )
        r.raise_for_status()
    except Exception as exc:
        log.warning("Could not report Browser Scan failure for job %s: %s", job_id, exc)


async def fetch_page_speed(url: str) -> dict:
    """Best-effort Google PageSpeed Insights call (skipped without an API key)."""
    out = {"url_tested": url, "score": None, "lcp_ms": None, "fcp_ms": None, "tbt_ms": None}
    if not PSI_KEY:
        return out
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params={"url": url, "strategy": "mobile", "category": "performance", "key": PSI_KEY},
            )
            r.raise_for_status()
            data = r.json()
        lh = data.get("lighthouseResult", {})
        cats = lh.get("categories", {}).get("performance", {})
        audits = lh.get("audits", {})
        if cats.get("score") is not None:
            out["score"] = round(cats["score"] * 100, 1)
        out["lcp_ms"] = audits.get("largest-contentful-paint", {}).get("numericValue")
        out["fcp_ms"] = audits.get("first-contentful-paint", {}).get("numericValue")
        out["tbt_ms"] = audits.get("total-blocking-time", {}).get("numericValue")
    except Exception as exc:
        log.warning("PageSpeed call failed for %s: %s", url, exc)
    return out


async def audit(job: dict) -> dict:
    """Run the full audit in a real/attached browser → ChromeAuditData dict."""
    brand = job["brand"]
    base_url = job.get("base_url") or domain_to_url(job["domain"])
    scan_id = job["scan_id"]

    auditor_kwargs = {"cdp_url": CDP_URL} if CDP_URL else {"real_chrome": True}

    pdps: list[dict] = []
    bestsellers: list[dict] = []
    homepage_html = ""
    cat_url = ""
    cat_html = ""
    shots: list[str] = []

    async with PlaywrightAuditor(**auditor_kwargs) as auditor:
        pdp_urls = (await auditor.find_pdp_urls(base_url)) or []
        homepage_html = (await auditor.get_html(base_url)) or ""

        block = detect_block(homepage_html)
        if block:
            raise BrowserScanBlocked(f"Real browser also hit bot protection: {block}")

        for i, url in enumerate(pdp_urls[:5]):
            html, rd = await auditor.get_pdp_with_reviews(url)
            if not html:
                continue
            jsonld = extract_jsonld(html)
            texts = rd.get("review_texts", []) or []
            dates = rd.get("dates", []) or []
            reviews = []
            for j, t in enumerate(texts):
                reviews.append({
                    "text": t,
                    "word_count": len(t.split()),
                    "date": dates[j] if j < len(dates) else "",
                })
            pdps.append({
                "url": url,
                "product_name": _product_name_from_url(url),
                "reviews": reviews,
                "total_review_count": rd.get("review_count"),
                "has_ai_summary": bool(rd.get("has_ai_summary")),
                "stars_above_fold": bool(rd.get("star_ratings")),
                "has_review_schema": has_review_schema(jsonld),
                "has_aggregate_rating_schema": has_aggregate_rating(jsonld),
                "review_platform_detected": detect_platform(html) or "",
                "screenshot_base64": "",
            })

        for pdp in pdps[:5]:
            count = pdp.get("total_review_count")
            bestsellers.append({
                "url": pdp["url"],
                "product_name": pdp.get("product_name") or _product_name_from_url(pdp["url"]),
                "review_count": count,
                "has_50_plus": bool(count is not None and count >= 50),
            })

        cat_url, cat_html = await auditor.get_category_html(base_url)
        cat_html = cat_html or ""

        shots = (await auditor.take_screenshots(scan_id, base_url, pdp_urls)) or []

    # ── Map screenshots onto the schema slots the converter reads ──────────────
    shot_b64 = {Path(p).stem: _b64_file(p) for p in shots}
    if pdps:
        pdps[0]["screenshot_base64"] = shot_b64.get("pdp_reviews", "")
    if len(pdps) > 1:
        pdps[1]["screenshot_base64"] = shot_b64.get("pdp_above_fold", "")

    # ── Roll-ups ──────────────────────────────────────────────────────────────
    platform = detect_platform(homepage_html) or (
        pdps[0]["review_platform_detected"] if pdps else ""
    )
    agg = any(p["has_aggregate_rating_schema"] for p in pdps)
    rev_schema = any(p["has_review_schema"] for p in pdps)
    cat_stars = bool(cat_html) and ("star" in cat_html.lower() or "rating" in cat_html.lower())
    nav_link = "/reviews" in homepage_html.lower() or "review" in homepage_html.lower()

    vtext = " ".join(r["text"] for p in pdps for r in p["reviews"]) + " " + homepage_html[:6000]
    vertical = detect_vertical(vtext) or ""

    page_speed = await fetch_page_speed(pdp_urls[0] if pdp_urls else base_url)

    mode_label = "attached Chrome (CDP)" if CDP_URL else "local Chrome"
    notes = [f"Browser Scan via {mode_label} on a residential IP."]
    if not pdps:
        notes.append("No product pages reachable even from a real browser.")
    if bestsellers:
        notes.append("Bestseller depth uses the first discovered top-product pages from the local browser audit.")

    return {
        "scan_id": scan_id,
        "brand": brand,
        "base_url": base_url,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "mode": "chrome",
        "pdps_visited": pdps,
        "category_page": {
            "url": cat_url or "",
            "has_stars_on_cards": cat_stars,
            "screenshot_base64": shot_b64.get("category_stars", ""),
        },
        "bestsellers": bestsellers,
        "homepage": {
            "detected_platform": platform,
            "has_nav_review_link": nav_link,
            "screenshot_base64": "",
        },
        "llm_probe": {"can_quote": False, "quote_response": ""},
        "page_speed": page_speed,
        "vertical_signals": {
            "detected_vertical": vertical,
            "signals_found": _vertical_signals_found(vertical, vtext),
        },
        "rich_snippets": {
            "has_review_schema": rev_schema,
            "has_aggregate_rating": agg,
            "schema_types_found": [],
        },
        "audit_notes": notes,
    }


async def main():
    if not SECRET:
        log.error("BROWSER_WEBHOOK_SECRET is required and must match Railway. Exiting.")
        sys.exit(1)
    log.info(
        "Browser Scan runner started → %s | chrome=%s | pagespeed=%s",
        API_BASE, ("CDP:" + CDP_URL) if CDP_URL else "launch local Chrome",
        "on" if PSI_KEY else "off",
    )
    async with httpx.AsyncClient(timeout=120) as api:
        while True:
            try:
                job = await claim_job(api)
            except Exception as exc:
                log.warning("Could not claim a job: %s", exc)
                await asyncio.sleep(POLL)
                continue

            if not job:
                await asyncio.sleep(POLL)
                continue

            log.info("Claimed job: %s (%s)", job.get("brand"), job.get("domain"))
            try:
                payload = await audit(job)
                await post_results(api, job["scan_id"], payload)
                log.info(
                    "Done: %s — %d PDPs, %d reviews posted.",
                    job.get("brand"),
                    len(payload["pdps_visited"]),
                    sum(len(p["reviews"]) for p in payload["pdps_visited"]),
                )
            except BrowserScanBlocked as exc:
                message = str(exc)
                log.error("Browser Scan blocked for %s: %s", job.get("brand"), message)
                await report_failure(api, job, message, blocked=True)
                await asyncio.sleep(POLL)
            except Exception as exc:
                log.error("Audit failed for %s: %s", job.get("brand"), exc, exc_info=True)
                await report_failure(api, job, str(exc), blocked=False)
                await asyncio.sleep(POLL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Runner stopped.")
