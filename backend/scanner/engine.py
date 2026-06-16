"""Main scan orchestration with WebSocket progress broadcasting."""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal, ScanRun
from .utils import (
    SCORE_WEIGHTS, VERTICAL_PLAYS, WHY_IT_MATTERS, DIMENSION_LABELS,
    make_client, fetch_html, fetch_bytes, detect_platform, detect_vertical,
    domain_to_url, clean_domain, find_bestseller_urls, find_pdp_urls,
)
from .dimensions import (
    llm_crawlability, review_richness, review_recency,
    visibility, rich_snippets, page_speed,
    bestseller_depth, stars_on_category, vertical_signals,
)
from .screenshots import capture as take_screenshots
from .pdf_generator import generate as generate_pdf
from .slinger import build_context, generate_drafts

log = logging.getLogger("scanner.engine")

# Broadcast callback type: async fn(scan_id, message_dict)
BroadcastFn = Callable[[str, Dict[str, Any]], None]


def _grade_color(grade: str) -> str:
    return {"A": "#27ae60", "B": "#e67e22", "C": "#f39c12", "D": "#e74c3c"}.get(grade, "#999")


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

    # LLM crawlability failure
    llm_dim = scores.get("llm_crawlability", {})
    if llm_failed or llm_dim.get("score", 0) < 10:
        quote_excerpt = (llm_quote or "I cannot access that information")[:100]
        angles.append(
            f"When we asked Claude to quote a review from {brand_name}'s site, it said: "
            f"\"{quote_excerpt}\". "
            f"That's what every AI assistant sees when shoppers ask for recommendations."
        )

    # Page speed (especially heavy platforms)
    ps_dim = scores.get("page_speed", {})
    if ps_dim.get("score", MAX := SCORE_WEIGHTS["page_speed"]) < 6:
        platform_note = (
            f" (your {detected_platform} widget is part of this)"
            if detected_platform in {"BazaarVoice", "PowerReviews"} else ""
        )
        angles.append(
            f"{brand_name}'s mobile performance score is low{platform_note}. "
            f"At 100ms of delay per 1% conversion loss, that adds up fast on mobile."
        )

    # Review recency
    rec_dim = scores.get("review_recency", {})
    if rec_dim.get("score", 99) < 8:
        angles.append(
            f"The most recent visible review on {brand_name} appears to be 90+ days old. "
            f"60% of shoppers won't buy if the newest review is that stale."
        )

    # Rich snippets
    rs_dim = scores.get("rich_snippets", {})
    if rs_dim.get("score", 99) == 0:
        angles.append(
            f"{brand_name} is missing AggregateRating schema, which means no star ratings "
            f"in Google search results. Every competitor with schema gets a visual edge."
        )

    # Vertical play
    if vertical_play and len(angles) < 3:
        angles.append(vertical_play)

    # Platform mismatch
    if platform_mismatch and len(angles) < 3:
        angles.append(
            f"Salesforce shows {sf_platform} but the scanner detected "
            f"{detected_platform} on the live site. Worth a quick check before outreach."
        )

    # Stars on category
    sc_dim = scores.get("stars_on_category", {})
    if sc_dim.get("score", 99) == 0 and len(angles) < 3:
        angles.append(
            f"{brand_name} doesn't show star ratings on collection pages. "
            f"Adding them (like True Religion on their denim collections) can lift CTR ~30%."
        )

    # Bestseller depth fallback
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
    """Full scan pipeline. Saves results to DB, broadcasts progress via WebSocket."""

    async def emit(step: str, status: str, **extra):
        await _broadcast(broadcast, scan_id, {"type": "progress", "step": step, "status": status, **extra})

    base_url = domain_to_url(domain)
    log.info("Starting scan %s for %s (%s)", scan_id, brand_name, base_url)

    # Mark as running
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
        async with make_client() as client:
            await emit("fetch", "running", message=f"Fetching {domain}...")

            # Fetch homepage
            homepage_html = await fetch_html(client, base_url) or ""
            if not homepage_html:
                raise RuntimeError(f"Could not reach {base_url}")

            # Detect platform
            detected_platform = detect_platform(homepage_html)
            await emit("fetch", "complete", message="Homepage fetched.", platform=detected_platform)

            # Fetch brand logo
            try:
                from bs4 import BeautifulSoup
                from .utils import extract_jsonld
                soup = BeautifulSoup(homepage_html, "lxml")
                logo_url = None
                for hdr in soup.find_all(["header", "nav"]):
                    for img in hdr.find_all("img"):
                        attrs = " ".join([
                            (img.get("class") or [""])[0],
                            img.get("id", ""), img.get("alt", ""), img.get("src", ""),
                        ]).lower()
                        if "logo" in attrs and img.get("src"):
                            logo_url = img["src"]
                            break
                    if logo_url:
                        break
                if logo_url:
                    from urllib.parse import urljoin
                    raw = await fetch_bytes(client, urljoin(base_url, logo_url))
                    if raw and len(raw) > 200:
                        ext = "png" if logo_url.lower().endswith(".png") else "jpeg"
                        brand_logo_b64 = f"data:image/{ext};base64,{base64.b64encode(raw).decode()}"
            except Exception:
                pass

            # Fetch PDPs
            page_pairs = await find_bestseller_urls(client, base_url)
            pdp_urls: List[str] = []
            for _, html in page_pairs:
                pdp_urls.extend(await find_pdp_urls(client, base_url, html))
            pdp_urls = list(dict.fromkeys(pdp_urls))[:5]

            pdp_htmls: List[str] = []
            for u in pdp_urls:
                h = await fetch_html(client, u)
                if h:
                    pdp_htmls.append(h)
            if not pdp_htmls and homepage_html:
                pdp_htmls = [homepage_html]

            # ── Dimension 1: LLM Crawlability ─────────────────────────────
            await emit("llm_crawlability", "running", message="Probing LLM crawlability...")
            llm_result = await llm_crawlability.score(base_url, client, skip_llm)
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
            vis = await visibility.score(base_url, client, homepage_html, pdp_htmls)
            all_scores["visibility"] = vis
            await emit("visibility", "complete", **vis)

            # ── Dimension 5: Rich Snippets ────────────────────────────────
            await emit("rich_snippets", "running", message="Checking schema markup...")
            rs = rich_snippets.score(pdp_htmls, homepage_html)
            all_scores["rich_snippets"] = rs
            await emit("rich_snippets", "complete", **rs)

            # ── Dimension 6: Page Speed ───────────────────────────────────
            await emit("page_speed", "running", message="Running PageSpeed Insights...")
            ps = await page_speed.score(base_url, client, detected_platform)
            all_scores["page_speed"] = {
                "score": ps["score"], "max_score": ps["max_score"], "finding": ps["finding"],
            }
            page_speed_score = ps.get("perf_score")
            page_speed_lcp   = ps.get("lcp", "")
            await emit("page_speed", "complete",
                       score=ps["score"], max_score=ps["max_score"],
                       perf_score=page_speed_score, lcp=page_speed_lcp)

            # ── Dimension 7: Bestseller Depth ─────────────────────────────
            await emit("bestseller_depth", "running", message="Checking bestseller review depth...")
            bd = await bestseller_depth.score(base_url, client)
            all_scores["bestseller_depth"] = bd
            await emit("bestseller_depth", "complete", **bd)

            # ── Dimension 8: Stars on Category ────────────────────────────
            await emit("stars_on_category", "running", message="Checking category page stars...")
            sc = await stars_on_category.score(base_url, client)
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

        # ── Compute totals ────────────────────────────────────────────────
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
            for k, v in sorted(all_scores.items(), key=lambda x: x[1].get("score", 0) / max(x[1].get("max_score", 1), 1))[:5]
        ]

        # ── Screenshots ───────────────────────────────────────────────────
        if not skip_screenshots:
            await emit("screenshots", "running", message="Taking screenshots...")
            screenshots = await take_screenshots(scan_id, base_url)
            await emit("screenshots", "complete",
                       message=f"{len(screenshots)} screenshots captured.", count=len(screenshots))
        else:
            await emit("screenshots", "complete", message="Screenshots skipped.", count=0)

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

        # Normalize screenshot paths → [{label, path}] so the frontend can
        # construct /api/scans/{id}/screenshot/{label} URLs directly
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
