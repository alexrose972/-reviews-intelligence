"""Main scan orchestration — Playwright-first, full JS rendering."""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from ..database import AsyncSessionLocal, ScanRun
from .utils import (
    SCORE_WEIGHTS, VERTICAL_PLAYS, WHY_IT_MATTERS, DIMENSION_LABELS,
    make_client, fetch_html, detect_platform, detect_vertical,
    domain_to_url, clean_domain,
)
from .browser import PlaywrightAuditor
from .dimensions import (
    llm_crawlability, review_richness, review_recency,
    visibility, rich_snippets, page_speed,
    bestseller_depth, stars_on_category, vertical_signals,
)
from .pdf_generator import generate as generate_pdf
from .slinger import build_context, generate_drafts

log = logging.getLogger("scanner.engine")

BroadcastFn = Callable[[str, Dict[str, Any]], None]


def compute_grade(score: float) -> str:
    if score >= 80: return "A"
    if score >= 60: return "B"
    if score >= 40: return "C"
    return "D"


def build_pitch_angles(
    brand_name: str,
    scores: Dict[str, dict],
    detected_platform: Optional[str],
    sf_platform: Optional[str],
    platform_mismatch: bool,
    llm_quote: str,
    llm_failed: bool,
    vertical: Optional[str],
    vertical_play: str,
) -> List[str]:
    angles = []

    llm_dim = scores.get("llm_crawlability", {})
    if llm_failed or llm_dim.get("score", 0) < 10:
        quote_excerpt = (llm_quote or "I cannot access that information")[:100]
        angles.append(
            f"When we asked Claude to quote a review from {brand_name}'s site, it said: "
            f"\"{quote_excerpt}\". "
            f"That's what every AI assistant sees when shoppers ask for recommendations."
        )

    ps_dim = scores.get("page_speed", {})
    if ps_dim.get("score", SCORE_WEIGHTS["page_speed"]) < 6:
        platform_note = (
            f" (your {detected_platform} widget is part of this)"
            if detected_platform in {"BazaarVoice", "PowerReviews"} else ""
        )
        angles.append(
            f"{brand_name}'s mobile performance score is low{platform_note}. "
            f"At 100ms of delay per 1% conversion loss, that adds up fast on mobile."
        )

    rec_dim = scores.get("review_recency", {})
    if rec_dim.get("score", 99) < 8:
        angles.append(
            f"The most recent visible review on {brand_name} appears to be 90+ days old. "
            f"60% of shoppers won't buy if the newest review is that stale."
        )

    rs_dim = scores.get("rich_snippets", {})
    if rs_dim.get("score", 99) == 0:
        angles.append(
            f"{brand_name} is missing AggregateRating schema — no star ratings "
            f"in Google search results. Every competitor with schema gets a visual edge."
        )

    if vertical_play and len(angles) < 3:
        angles.append(vertical_play)

    if platform_mismatch and len(angles) < 3:
        angles.append(
            f"Salesforce shows {sf_platform} but the scanner detected "
            f"{detected_platform} on the live site. Worth confirming before outreach."
        )

    sc_dim = scores.get("stars_on_category", {})
    if sc_dim.get("score", 99) == 0 and len(angles) < 3:
        angles.append(
            f"{brand_name} doesn't show star ratings on collection pages. "
            f"Adding them (like True Religion on their denim collections) can lift CTR ~30%."
        )

    bd_dim = scores.get("bestseller_depth", {})
    if bd_dim.get("score", 99) < 6 and len(angles) < 3:
        angles.append(
            f"Several of {brand_name}'s top products have fewer than 50 reviews, "
            f"which limits both search ranking and conversion rate on those PDPs."
        )

    return angles[:3]


async def _broadcast(broadcast: Optional[BroadcastFn], scan_id: str, msg: dict):
    if broadcast:
        try:
            await broadcast(scan_id, msg)
        except Exception:
            pass


async def run_scan(
    scan_id: str,
    brand_name: str,
    domain: str,
    account_owner: str,
    sf_reviews_provider: Optional[str],
    triggered_by: str,
    skip_llm: bool = False,
    skip_screenshots: bool = False,
    broadcast: Optional[BroadcastFn] = None,
):
    """Full scan pipeline using Playwright for all page analysis."""

    async def emit(step: str, status: str, **extra):
        await _broadcast(broadcast, scan_id, {"type": "progress", "step": step, "status": status, **extra})

    base_url = domain_to_url(domain)
    log.info("Starting Playwright scan %s for %s (%s)", scan_id, brand_name, base_url)

    async with AsyncSessionLocal() as db:
        result = await db.get(ScanRun, scan_id)
        if result:
            result.status = "running"
            await db.commit()

    all_scores: Dict[str, dict] = {}
    llm_review_quote = ""
    llm_complaint_quote = ""
    llm_failed = False
    detected_platform = None
    vertical = None
    vertical_play = ""
    page_speed_score = None
    page_speed_lcp = ""
    brand_logo_b64 = ""
    screenshots: List[str] = []

    try:
        async with PlaywrightAuditor() as auditor:

            # ── Phase 1: Find real PDP URLs by navigating the site ────────
            await emit("fetch", "running", message=f"Navigating {domain} to find product pages...")
            pdp_urls = await auditor.find_pdp_urls(base_url)

            # ── Phase 2: Render homepage (JS-executed) ────────────────────
            await emit("fetch", "running", message="Rendering homepage...")
            homepage_html = await auditor.get_html(base_url) or ""
            if not homepage_html:
                raise RuntimeError(f"Could not render {base_url}")

            detected_platform = detect_platform(homepage_html)
            await emit("fetch", "complete",
                       message=f"Found {len(pdp_urls)} product pages.",
                       platform=detected_platform)

            # Extract brand logo
            try:
                from bs4 import BeautifulSoup
                soup_home = BeautifulSoup(homepage_html, "lxml")
                for hdr in soup_home.find_all(["header", "nav"]):
                    for img in hdr.find_all("img"):
                        attrs = " ".join([
                            (img.get("class") or [""])[0],
                            img.get("id", ""), img.get("alt", ""), img.get("src", ""),
                        ]).lower()
                        if "logo" in attrs and img.get("src"):
                            from urllib.parse import urljoin as _urljoin
                            logo_url = _urljoin(base_url, img["src"])
                            async with make_client() as client:
                                from .utils import fetch_bytes
                                raw = await fetch_bytes(client, logo_url)
                            if raw and len(raw) > 200:
                                ext = "png" if logo_url.lower().endswith(".png") else "jpeg"
                                brand_logo_b64 = f"data:image/{ext};base64,{base64.b64encode(raw).decode()}"
                            break
                    if brand_logo_b64:
                        break
            except Exception:
                pass

            # ── Phase 3: Render each PDP with full JS + scroll to reviews ─
            await emit("review_richness", "running",
                       message=f"Rendering {len(pdp_urls)} product pages (JS + review scroll)...")
            pdp_htmls: List[str] = []
            for i, url in enumerate(pdp_urls[:5]):
                log.info("Rendering PDP %d/%d: %s", i + 1, len(pdp_urls), url)
                html = await auditor.get_html(url, wait_for_reviews=True)
                if html:
                    pdp_htmls.append(html)

            if not pdp_htmls:
                log.warning("No PDPs rendered — falling back to homepage")
                pdp_htmls = [homepage_html]

            # ── Phase 4: Render category page ─────────────────────────────
            await emit("stars_on_category", "running", message="Rendering category page...")
            cat_url, cat_html = await auditor.get_category_html(base_url)

            # ── Phase 5: Try to render a /reviews page for visibility check ─
            reviews_page_html: Optional[str] = None
            for path in ["/reviews", "/testimonials", "/customer-reviews"]:
                html = await auditor.get_html(urljoin(base_url, path))
                if html and len(html) > 2000:
                    reviews_page_html = html
                    break

            # ── Dimension 1: LLM Crawlability ─────────────────────────────
            await emit("llm_crawlability", "running", message="Probing LLM crawlability...")
            # Use first PDP for schema check (JS-rendered)
            llm_result = await llm_crawlability.score(
                base_url, pdp_htmls[0] if pdp_htmls else homepage_html, skip_llm
            )
            all_scores["llm_crawlability"] = {
                "score": llm_result["score"],
                "max_score": llm_result["max_score"],
                "finding": llm_result["finding"],
            }
            llm_review_quote = llm_result.get("review_quote", "")
            llm_complaint_quote = llm_result.get("complaint_quote", "")
            llm_failed = llm_result.get("failed", False)
            await emit("llm_crawlability", "complete",
                       score=llm_result["score"], max_score=llm_result["max_score"],
                       finding=llm_result["finding"])

            # ── Dimension 2: Review Richness ──────────────────────────────
            await emit("review_richness", "running", message="Analyzing review quality...")
            rr = review_richness.score(pdp_htmls)
            all_scores["review_richness"] = rr
            await emit("review_richness", "complete", **rr)

            # ── Dimension 3: Review Recency ───────────────────────────────
            await emit("review_recency", "running", message="Checking review dates...")
            rc = review_recency.score(pdp_htmls)
            all_scores["review_recency"] = rc
            await emit("review_recency", "complete", **rc)

            # ── Dimension 4: Visibility ───────────────────────────────────
            await emit("visibility", "running", message="Checking review discoverability...")
            vis = visibility.score(homepage_html, pdp_htmls, reviews_page_html)
            all_scores["visibility"] = vis
            await emit("visibility", "complete", **vis)

            # ── Dimension 5: Rich Snippets ────────────────────────────────
            await emit("rich_snippets", "running", message="Checking schema markup...")
            rs = rich_snippets.score(pdp_htmls, homepage_html)
            all_scores["rich_snippets"] = rs
            await emit("rich_snippets", "complete", **rs)

            # ── Dimension 6: Page Speed ───────────────────────────────────
            await emit("page_speed", "running", message="Running PageSpeed Insights...")
            # Use a real PDP URL for PageSpeed (not just the homepage)
            pdp_for_speed = pdp_urls[0] if pdp_urls else base_url
            async with make_client() as client:
                ps = await page_speed.score(pdp_for_speed, client, detected_platform)
            all_scores["page_speed"] = {
                "score": ps["score"], "max_score": ps["max_score"], "finding": ps["finding"],
            }
            page_speed_score = ps.get("perf_score")
            page_speed_lcp = ps.get("lcp", "")
            await emit("page_speed", "complete",
                       score=ps["score"], max_score=ps["max_score"],
                       perf_score=page_speed_score, lcp=page_speed_lcp)

            # ── Dimension 7: Bestseller Depth ─────────────────────────────
            await emit("bestseller_depth", "running", message="Checking bestseller review depth...")
            bd = bestseller_depth.score(pdp_htmls)
            all_scores["bestseller_depth"] = bd
            await emit("bestseller_depth", "complete", **bd)

            # ── Dimension 8: Stars on Category ────────────────────────────
            await emit("stars_on_category", "running", message="Checking category page stars...")
            sc = stars_on_category.score(cat_html, cat_url)
            all_scores["stars_on_category"] = sc
            await emit("stars_on_category", "complete", **sc)

            # ── Dimension 9: Vertical Signals ─────────────────────────────
            await emit("vertical_signals", "running", message="Detecting vertical...")
            vs = vertical_signals.score(pdp_htmls, homepage_html)
            all_scores["vertical_signals"] = {
                "score": vs["score"], "max_score": vs["max_score"], "finding": vs["finding"],
            }
            vertical = vs.get("vertical")
            vertical_play = vs.get("play", "")
            await emit("vertical_signals", "complete",
                       score=vs["score"], max_score=vs["max_score"],
                       vertical=vertical)

            # ── Screenshots ───────────────────────────────────────────────
            if not skip_screenshots:
                await emit("screenshots", "running", message="Taking targeted screenshots...")
                screenshots = await auditor.take_screenshots(scan_id, base_url, pdp_urls)
                await emit("screenshots", "complete",
                           message=f"{len(screenshots)} screenshots captured.", count=len(screenshots))
            else:
                await emit("screenshots", "complete", message="Screenshots skipped.", count=0)

        # ── Compute totals (outside Playwright context) ───────────────────
        total = round(sum(d["score"] for d in all_scores.values()), 1)
        grade = compute_grade(total)
        platform_mismatch = bool(
            detected_platform and sf_reviews_provider and
            detected_platform.lower() != sf_reviews_provider.lower()
        )

        pitch_angles = build_pitch_angles(
            brand_name, all_scores, detected_platform, sf_reviews_provider,
            platform_mismatch, llm_review_quote, llm_failed, vertical, vertical_play,
        )

        recommendations = [
            f"[{DIMENSION_LABELS.get(k, k)}] {v.get('finding', '')} — {WHY_IT_MATTERS.get(k, '')}"
            for k, v in sorted(
                all_scores.items(),
                key=lambda x: x[1].get("score", 0) / max(x[1].get("max_score", 1), 1)
            )[:5]
        ]

        # ── PDF ───────────────────────────────────────────────────────────
        await emit("pdf", "running", message="Generating PDF brief...")
        pdf_path = generate_pdf(
            scan_id=scan_id,
            brand_name=brand_name,
            domain=clean_domain(base_url),
            account_owner=account_owner,
            overall_score=int(total),
            grade=grade,
            scores=all_scores,
            pitch_angles=pitch_angles,
            detected_platform=detected_platform,
            sf_platform=sf_reviews_provider,
            platform_mismatch=platform_mismatch,
            vertical=vertical,
            page_speed_score=page_speed_score,
            page_speed_lcp=page_speed_lcp,
            screenshot_paths=screenshots,
            brand_logo_b64=brand_logo_b64,
            scan_ts=datetime.utcnow().isoformat(),
        )
        await emit("pdf", "complete", message="PDF brief generated.")

        # ── Slinger 3000 ──────────────────────────────────────────────────
        await emit("slinger", "running", message="Drafting Slinger 3000 emails...")
        context_str = build_context(
            brand_name=brand_name,
            domain=clean_domain(base_url),
            overall_score=int(total),
            grade=grade,
            scores=all_scores,
            pitch_angles=pitch_angles,
            detected_platform=detected_platform,
            sf_platform=sf_reviews_provider,
            platform_mismatch=platform_mismatch,
            vertical=vertical,
            page_speed_score=page_speed_score,
            llm_quote=llm_review_quote,
            llm_failed=llm_failed,
        )
        slinger_result = generate_drafts(brand_name, context_str, email_count=3)
        await emit("slinger", "complete", message="Slinger 3000 drafts ready.")

        # ── Save to DB ────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            run = await db.get(ScanRun, scan_id)
            if run:
                run.status = "complete"
                run.overall_score = int(total)
                run.grade = grade
                run.scores_json = all_scores
                run.recommendations_json = recommendations
                run.pitch_angles_json = pitch_angles
                run.llm_probe_json = {
                    "review_quote": llm_review_quote,
                    "complaint_quote": llm_complaint_quote,
                    "failed": llm_failed,
                }
                run.detected_platform = detected_platform
                run.sf_platform = sf_reviews_provider
                run.platform_mismatch = platform_mismatch
                run.pdf_path = pdf_path
                run.slinger_drafts_json = slinger_result
                run.screenshots_json = screenshots
                await db.commit()

        # Normalize screenshot paths for frontend
        from pathlib import Path as _Path
        normalized_screenshots = [
            {"label": _Path(p).stem, "path": p}
            for p in screenshots
            if isinstance(p, str)
        ]

        full_result = {
            "id": scan_id,
            "brand_name": brand_name,
            "domain": domain,
            "status": "complete",
            "overall_score": int(total),
            "grade": grade,
            "scores": all_scores,
            "pitch_angles": pitch_angles,
            "recommendations": recommendations,
            "detected_platform": detected_platform,
            "sf_platform": sf_reviews_provider,
            "platform_mismatch": platform_mismatch,
            "slinger_drafts": slinger_result,
            "screenshots": normalized_screenshots,
            "pdf_path": pdf_path,
            "vertical": vertical,
            "page_speed_score": page_speed_score,
        }
        await _broadcast(broadcast, scan_id, {"type": "complete", "result": full_result})
        log.info("Scan %s complete: %s/100 grade %s", scan_id, total, grade)

    except Exception as e:
        log.exception("Scan %s failed: %s", scan_id, e)
        async with AsyncSessionLocal() as db:
            run = await db.get(ScanRun, scan_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                await db.commit()
        await _broadcast(broadcast, scan_id, {"type": "error", "message": str(e)})
