"""Main scan orchestration — Playwright-first, full JS rendering."""

import asyncio
import base64
import logging
import os
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
from .browser import PlaywrightAuditor, detect_block
from .dimensions import (
    llm_crawlability, review_richness, review_recency,
    visibility, rich_snippets, page_speed,
    bestseller_depth, stars_on_category, vertical_signals,
)
from .pdf_generator import generate as generate_pdf
from .slinger import build_context, generate_drafts
from ..chrome_processor import queue_chrome_job

log = logging.getLogger("scanner.engine")

BroadcastFn = Callable[[str, Dict[str, Any]], None]


def _ts() -> str:
    return datetime.utcnow().isoformat()


def compute_grade(score: float) -> str:
    if score >= 80: return "A"
    if score >= 60: return "B"
    if score >= 40: return "C"
    return "D"


# Phrases that mean a model declined / has no web access — NOT a real site
# signal. We never surface these as findings or pitch angles.
_REFUSAL_MARKERS = (
    "i cannot", "i can't", "i don't have", "unable to access", "i'm not able",
    "as an ai", "no access", "cannot browse", "can't browse", "i apologize",
    "i'm unable", "not able to access", "don't have real-time",
    "do not have the ability", "i'm not able to browse", "can't visit",
)


def _is_refusal(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _REFUSAL_MARKERS)


# Human-readable copy for each blocked reason (shown in the UI / stored as
# error_message). A blocked scan produces NO score.
_BLOCK_MESSAGES = {
    "bot_block_detected": (
        "The live site is behind bot protection (Cloudflare / PerimeterX / "
        "DataDome) and blocked the scanner. No score was generated — run a "
        "Browser Scan from a real browser to audit it."
    ),
    "page_render_failed": (
        "The site failed to render (timeout or hard block). No score was "
        "generated — try a Browser Scan."
    ),
    "empty_render": (
        "The site returned an empty page to the scanner, which usually means a "
        "block. No score was generated — try a Browser Scan."
    ),
}


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

    # Only surface the LLM-quote angle when there is a GENUINE quote — never a
    # model refusal ("I'm not able to browse the internet…"), which says nothing
    # about the brand and just makes the brief look broken.
    llm_dim = scores.get("llm_crawlability", {})
    if (llm_failed or llm_dim.get("score", 0) < 10) and llm_quote and not _is_refusal(llm_quote):
        quote_excerpt = llm_quote[:100]
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


def _should_fallback_to_chrome(
    pdp_urls: list,
    pdp_htmls: list,
    scores: dict,
    audit_log: list,
) -> tuple:
    """
    Return (should_fallback: bool, reason: str).
    Called after every Playwright scan to decide if Chrome is needed.
    """
    # No PDPs found at all
    if not pdp_urls:
        return True, "no_pdps_found"

    # PDPs found but zero reviews extracted across all of them
    total_review_texts = sum(
        entry.get("review_texts_found", 0)
        for entry in audit_log
        if entry.get("step", "").startswith("pdp_review_audit_")
    )
    if len(pdp_urls) > 0 and total_review_texts == 0:
        return True, "no_reviews_extracted"

    # Suspiciously low scores across the board (likely bot detection)
    # (LLM crawlability can legitimately be 0 — exclude it)
    non_llm = [
        k for k in scores
        if k != "llm_crawlability" and scores[k].get("score", -1) == 0
    ]
    if len(non_llm) >= 5:
        return True, "bot_detection_suspected"

    return False, ""


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

    audit_log: List[dict] = []
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
    pdp_urls: List[str] = []
    pdp_htmls: List[str] = []

    def _log(step: str, **kwargs):
        audit_log.append({"step": step, "ts": _ts(), **kwargs})

    async def safe_run(step: str, coro, default=None):
        """Await a coroutine; on exception log to audit_log and return default."""
        _log(step, status="started")
        try:
            result = await coro
            audit_log[-1]["status"] = "ok"
            return result
        except Exception as exc:
            audit_log[-1]["status"] = "error"
            audit_log[-1]["error"] = f"{type(exc).__name__}: {exc}"
            log.warning("safe_run[%s] failed: %s", step, exc)
            return default

    def run_dim(step: str, fn, *args, **kwargs):
        """Call a synchronous dimension function; log result to audit_log."""
        _log(step, status="started")
        try:
            result = fn(*args, **kwargs)
            audit_log[-1]["status"] = "ok"
            audit_log[-1]["score"] = result.get("score")
            audit_log[-1]["finding"] = (result.get("finding") or "")[:300]
            return result
        except Exception as exc:
            audit_log[-1]["status"] = "error"
            audit_log[-1]["error"] = f"{type(exc).__name__}: {exc}"
            log.warning("run_dim[%s] failed: %s", step, exc)
            max_s = SCORE_WEIGHTS.get(step, 10)
            return {"score": 0, "max_score": max_s, "finding": f"Scoring error: {exc}"}

    try:
        async with PlaywrightAuditor() as auditor:

            # ── Phase 1: PDP Discovery ────────────────────────────────────────
            await emit("fetch", "running", message=f"Navigating {domain} to find product pages...")
            pdp_urls = await safe_run("pdp_discovery", auditor.find_pdp_urls(base_url)) or []
            _log("pdp_discovery_result", urls_found=len(pdp_urls), urls=pdp_urls)
            log.info("PDP discovery: %d URLs found for %s", len(pdp_urls), base_url)

            # ── Phase 2: Homepage ─────────────────────────────────────────────
            await emit("fetch", "running", message="Rendering homepage...")
            homepage_html = await safe_run("homepage", auditor.get_html(base_url)) or ""

            # ── Bot-block guard ───────────────────────────────────────────────
            # If we hit a WAF / captcha / challenge page (or got an empty render),
            # do NOT score it — a fabricated grade off a block page is worse than
            # no grade. Mark the scan 'blocked' and queue a Browser Scan instead.
            block_reason = detect_block(homepage_html)
            if block_reason:
                msg = _BLOCK_MESSAGES.get(block_reason, "Site could not be reached.")
                log.warning("Scan %s blocked (%s) for %s", scan_id, block_reason, base_url)
                _log("scan_blocked", reason=block_reason,
                     html_len=len(homepage_html) if homepage_html else 0)
                await emit("fetch", "blocked", message=msg)

                async with AsyncSessionLocal() as db:
                    run = await db.get(ScanRun, scan_id)
                    if run:
                        run.status = "blocked"
                        run.overall_score = None
                        run.grade = None
                        run.scores_json = {}
                        run.pitch_angles_json = []
                        run.recommendations_json = []
                        run.error_message = msg
                        run.scan_fallback_reason = block_reason
                        run.audit_log_json = audit_log
                        await db.commit()

                # Hand off to the Browser Scan queue (consumed by the local
                # runner — see PR #2). Honest 'queued' state, no fake score.
                if os.environ.get("CHROME_AUTO_FALLBACK", "true").lower() == "true":
                    await queue_chrome_job(
                        scan_id=scan_id, brand_name=brand_name, domain=domain,
                        base_url=base_url, fallback_reason=block_reason,
                    )

                await _broadcast(broadcast, scan_id, {
                    "type": "blocked", "scan_id": scan_id,
                    "reason": block_reason, "message": msg,
                })
                return

            detected_platform = detect_platform(homepage_html)
            _log("homepage_rendered", html_len=len(homepage_html), platform=detected_platform)
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

            # ── Phase 3: PDPs with deep review extraction ─────────────────────
            await emit("review_richness", "running",
                       message=f"Rendering {len(pdp_urls)} product pages (deep scroll + review extraction)...")
            for i, url in enumerate(pdp_urls[:5]):
                log.info("Rendering PDP %d/%d: %s", i + 1, len(pdp_urls), url)
                html, review_data = await safe_run(
                    f"pdp_render_{i+1}",
                    auditor.get_pdp_with_reviews(url),
                    default=(None, {}),
                )
                if html:
                    pdp_htmls.append(html)
                _log(f"pdp_review_audit_{i+1}",
                     url=url,
                     html_len=len(html) if html else 0,
                     review_count=review_data.get("review_count"),
                     review_texts_found=len(review_data.get("review_texts", [])),
                     star_ratings=review_data.get("star_ratings", [])[:3],
                     has_photos=review_data.get("has_photos"),
                     has_videos=review_data.get("has_videos"),
                     has_ai_summary=review_data.get("has_ai_summary"),
                     sample_dates=review_data.get("dates", [])[:3],
                )

            if not pdp_htmls:
                log.warning("No PDPs rendered — falling back to homepage for PDP dimensions")
                _log("pdp_fallback", reason="no_pdps_rendered")
                pdp_htmls = [homepage_html]

            _log("pdp_phase_complete", pdps_rendered=len(pdp_htmls))

            # ── Phase 4: Category page ────────────────────────────────────────
            await emit("stars_on_category", "running", message="Rendering category page...")
            cat_url, cat_html = await safe_run(
                "category_page", auditor.get_category_html(base_url), default=(None, None)
            )
            _log("category_page_result", url=cat_url, html_len=len(cat_html) if cat_html else 0)

            # ── Phase 5: Reviews/testimonials page ────────────────────────────
            reviews_page_html: Optional[str] = None
            for path in ["/reviews", "/testimonials", "/customer-reviews"]:
                html = await safe_run(
                    f"reviews_page_{path}", auditor.get_html(urljoin(base_url, path))
                )
                if html and len(html) > 2000:
                    reviews_page_html = html
                    _log("reviews_page_found", path=path, html_len=len(html))
                    break

            # ── Dimension 1: LLM Crawlability ─────────────────────────────────
            await emit("llm_crawlability", "running", message="Probing LLM crawlability...")
            llm_result = await safe_run(
                "dim_llm_crawlability",
                llm_crawlability.score(
                    base_url, pdp_htmls[0] if pdp_htmls else homepage_html, skip_llm
                ),
                default={"score": 0, "max_score": SCORE_WEIGHTS["llm_crawlability"],
                         "finding": "LLM check failed.", "failed": True},
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

            # ── Dimension 2: Review Richness ───────────────────────────────────
            await emit("review_richness", "running", message="Analyzing review quality...")
            rr = run_dim("dim_review_richness", review_richness.score, pdp_htmls)
            all_scores["review_richness"] = rr
            await emit("review_richness", "complete", **rr)

            # ── Dimension 3: Review Recency ────────────────────────────────────
            await emit("review_recency", "running", message="Checking review dates...")
            rc = run_dim("dim_review_recency", review_recency.score, pdp_htmls)
            all_scores["review_recency"] = rc
            await emit("review_recency", "complete", **rc)

            # ── Dimension 4: Visibility ────────────────────────────────────────
            await emit("visibility", "running", message="Checking review discoverability...")
            vis = run_dim("dim_visibility", visibility.score,
                          homepage_html, pdp_htmls, reviews_page_html)
            all_scores["visibility"] = vis
            await emit("visibility", "complete", **vis)

            # ── Dimension 5: Rich Snippets ─────────────────────────────────────
            await emit("rich_snippets", "running", message="Checking schema markup...")
            rs = run_dim("dim_rich_snippets", rich_snippets.score, pdp_htmls, homepage_html)
            all_scores["rich_snippets"] = rs
            await emit("rich_snippets", "complete", **rs)

            # ── Dimension 6: Page Speed ────────────────────────────────────────
            await emit("page_speed", "running", message="Running PageSpeed Insights...")
            pdp_for_speed = pdp_urls[0] if pdp_urls else base_url
            _log("dim_page_speed_url", url=pdp_for_speed)
            async with make_client() as client:
                ps = await safe_run(
                    "dim_page_speed",
                    page_speed.score(pdp_for_speed, client, detected_platform),
                    default={"score": 0, "max_score": SCORE_WEIGHTS["page_speed"],
                             "finding": "PageSpeed check failed."},
                )
            all_scores["page_speed"] = {
                "score": ps["score"], "max_score": ps["max_score"], "finding": ps["finding"],
            }
            page_speed_score = ps.get("perf_score")
            page_speed_lcp = ps.get("lcp", "")
            await emit("page_speed", "complete",
                       score=ps["score"], max_score=ps["max_score"],
                       perf_score=page_speed_score, lcp=page_speed_lcp)

            # ── Dimension 7: Bestseller Depth ──────────────────────────────────
            await emit("bestseller_depth", "running", message="Checking bestseller review depth...")
            bd = run_dim("dim_bestseller_depth", bestseller_depth.score, pdp_htmls)
            all_scores["bestseller_depth"] = bd
            await emit("bestseller_depth", "complete", **bd)

            # ── Dimension 8: Stars on Category ─────────────────────────────────
            await emit("stars_on_category", "running", message="Checking category page stars...")
            sc = run_dim("dim_stars_on_category", stars_on_category.score, cat_html, cat_url)
            all_scores["stars_on_category"] = sc
            await emit("stars_on_category", "complete", **sc)

            # ── Dimension 9: Vertical Signals ──────────────────────────────────
            await emit("vertical_signals", "running", message="Detecting vertical...")
            vs = run_dim("dim_vertical_signals", vertical_signals.score, pdp_htmls, homepage_html)
            all_scores["vertical_signals"] = {
                "score": vs["score"], "max_score": vs["max_score"], "finding": vs["finding"],
            }
            vertical = vs.get("vertical")
            vertical_play = vs.get("play", "")
            await emit("vertical_signals", "complete",
                       score=vs["score"], max_score=vs["max_score"],
                       vertical=vertical)

            # ── Score validation ───────────────────────────────────────────────
            # If no real PDPs were found, PDP-dependent scores must not be fabricated
            real_pdp_count = len([u for u in pdp_urls if u])
            if real_pdp_count == 0:
                log.warning("Score validation: no PDPs found — zeroing PDP-dependent scores")
                for key in ["review_richness", "review_recency", "bestseller_depth"]:
                    if all_scores.get(key, {}).get("score", 0) > 0:
                        _log("score_validation", dimension=key, action="zeroed",
                             reason="no_pdps_found",
                             original_score=all_scores[key]["score"])
                        all_scores[key]["score"] = 0
                        all_scores[key]["finding"] = (
                            "Could not access product pages — score zeroed to prevent fabrication."
                        )

            # If review text samples were empty across ALL PDPs, richness must be 0.
            # `review_texts_found` is stored as a count in the audit log.
            total_review_texts = sum(
                entry.get("review_texts_found", 0)
                for entry in audit_log
                if entry.get("step", "").startswith("pdp_review_audit_")
            )
            if total_review_texts == 0 and all_scores.get("review_richness", {}).get("score", 0) > 0:
                _log("score_validation", dimension="review_richness", action="zeroed",
                     reason="no_review_text_extracted",
                     original_score=all_scores["review_richness"]["score"])
                all_scores["review_richness"]["score"] = 0
                all_scores["review_richness"]["finding"] = (
                    "No review text extracted from any PDP — score zeroed to prevent fabrication."
                )

            _log("score_validation_complete",
                 scores_summary={k: v.get("score") for k, v in all_scores.items()})

            # ── Screenshots ────────────────────────────────────────────────────
            if not skip_screenshots:
                await emit("screenshots", "running", message="Taking targeted screenshots...")
                screenshots = await safe_run(
                    "screenshots", auditor.take_screenshots(scan_id, base_url, pdp_urls), default=[]
                ) or []
                _log("screenshots_result", count=len(screenshots), paths=screenshots)
                await emit("screenshots", "complete",
                           message=f"{len(screenshots)} screenshots captured.", count=len(screenshots))
            else:
                await emit("screenshots", "complete", message="Screenshots skipped.", count=0)

        # ── Compute totals (outside Playwright context) ───────────────────────
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

        # ── PDF ───────────────────────────────────────────────────────────────
        await emit("pdf", "running", message="Generating PDF brief...")
        _log("pdf_started")
        try:
            pdf_path = await generate_pdf(
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
            _log("pdf_complete", path=pdf_path)
        except Exception as e:
            log.error("PDF generation failed: %s", e, exc_info=True)
            _log("pdf_failed", error=str(e))
            pdf_path = None
        await emit("pdf", "complete", message="PDF brief generated.")

        # ── Slinger 3000 ──────────────────────────────────────────────────────
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
        _log("slinger_complete", drafts_count=len(slinger_result) if slinger_result else 0)
        await emit("slinger", "complete", message="Slinger 3000 drafts ready.")

        # ── Save to DB ────────────────────────────────────────────────────────
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
                run.audit_log_json = audit_log
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

        # ── Auto Chrome fallback ──────────────────────────────────────────────
        if os.environ.get("CHROME_AUTO_FALLBACK", "true").lower() == "true":
            fallback, reason = _should_fallback_to_chrome(pdp_urls, pdp_htmls, all_scores, audit_log)
            if fallback:
                log.info("Queuing Chrome fallback for %s: %s", brand_name, reason)
                _log("chrome_fallback_queued", reason=reason)
                # Save audit_log with fallback entry before queuing
                async with AsyncSessionLocal() as db:
                    run = await db.get(ScanRun, scan_id)
                    if run:
                        run.audit_log_json = audit_log
                        await db.commit()
                await queue_chrome_job(
                    scan_id=scan_id,
                    brand_name=brand_name,
                    domain=domain,
                    base_url=base_url,
                    fallback_reason=reason,
                )

    except Exception as e:
        log.exception("Scan %s failed: %s", scan_id, e)
        _log("fatal_error", error=str(e))
        async with AsyncSessionLocal() as db:
            run = await db.get(ScanRun, scan_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.audit_log_json = audit_log
                await db.commit()
        await _broadcast(broadcast, scan_id, {"type": "error", "message": str(e)})
