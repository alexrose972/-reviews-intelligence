"""
Pydantic models for ChromeAuditData and converters to/from the signals format
used by all downstream scoring functions.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .scanner.utils import SCORE_WEIGHTS


# ── Pydantic models (exact schema Chrome must POST) ───────────────────────────

class ReviewData(BaseModel):
    text: str = ""
    word_count: int = 0
    date: str = ""
    has_photo: bool = False
    has_video: bool = False
    rating: Optional[float] = None


class PDPData(BaseModel):
    url: str
    product_name: str = ""
    reviews: List[ReviewData] = Field(default_factory=list)
    total_review_count: Optional[int] = None
    avg_rating: Optional[float] = None
    has_ai_summary: bool = False
    ai_summary_text: str = ""
    stars_above_fold: bool = False
    has_review_schema: bool = False
    has_aggregate_rating_schema: bool = False
    review_platform_detected: str = ""
    screenshot_base64: str = ""


class CategoryPageData(BaseModel):
    url: str = ""
    has_stars_on_cards: bool = False
    screenshot_base64: str = ""


class BestsellerData(BaseModel):
    url: str = ""
    product_name: str = ""
    review_count: Optional[int] = None
    has_50_plus: bool = False


class HomepageData(BaseModel):
    detected_platform: str = ""
    has_nav_review_link: bool = False
    screenshot_base64: str = ""


class LLMProbeData(BaseModel):
    quote_question: str = ""
    quote_response: str = ""
    can_quote: bool = False
    complaint_question: str = ""
    complaint_response: str = ""


class PageSpeedData(BaseModel):
    url_tested: str = ""
    score: Optional[float] = None
    lcp_ms: Optional[float] = None
    fcp_ms: Optional[float] = None
    tbt_ms: Optional[float] = None


class VerticalSignalsData(BaseModel):
    detected_vertical: str = ""
    signals_found: List[str] = Field(default_factory=list)
    true_to_size_mentions: int = 0


class RichSnippetsData(BaseModel):
    has_review_schema: bool = False
    has_aggregate_rating: bool = False
    schema_types_found: List[str] = Field(default_factory=list)


class ChromeAuditData(BaseModel):
    scan_id: str
    brand: str
    base_url: str
    audited_at: str = ""
    mode: str = "chrome"
    pdps_visited: List[PDPData] = Field(default_factory=list)
    category_page: CategoryPageData = Field(default_factory=CategoryPageData)
    bestsellers: List[BestsellerData] = Field(default_factory=list)
    homepage: HomepageData = Field(default_factory=HomepageData)
    llm_probe: LLMProbeData = Field(default_factory=LLMProbeData)
    page_speed: PageSpeedData = Field(default_factory=PageSpeedData)
    vertical_signals: VerticalSignalsData = Field(default_factory=VerticalSignalsData)
    rich_snippets: RichSnippetsData = Field(default_factory=RichSnippetsData)
    audit_notes: List[str] = Field(default_factory=list)


# ── Converter: ChromeAuditData → unified signals dict ─────────────────────────

def chrome_data_to_signals(data: ChromeAuditData) -> dict:
    """
    Convert structured Chrome audit data into the flat signals dict that
    all downstream scoring functions can consume.
    """
    all_reviews: List[str] = []
    all_dates: List[str] = []
    total_photos = 0
    total_videos = 0
    has_ai_summary = False
    stars_above_fold = False
    has_review_schema = False
    has_aggregate_rating = False

    for pdp in data.pdps_visited:
        for review in pdp.reviews:
            if review.text:
                all_reviews.append(review.text)
            if review.date:
                all_dates.append(review.date)
            if review.has_photo:
                total_photos += 1
            if review.has_video:
                total_videos += 1
        if pdp.has_ai_summary:
            has_ai_summary = True
        if pdp.stars_above_fold:
            stars_above_fold = True
        if pdp.has_review_schema:
            has_review_schema = True
        if pdp.has_aggregate_rating_schema:
            has_aggregate_rating = True

    # Also pick up rich_snippets flags from the dedicated section
    if data.rich_snippets.has_review_schema:
        has_review_schema = True
    if data.rich_snippets.has_aggregate_rating:
        has_aggregate_rating = True

    word_counts = [len(r.split()) for r in all_reviews]
    avg_word_count = sum(word_counts) / len(word_counts) if word_counts else 0
    pct_short = (
        sum(1 for w in word_counts if w < 5) / len(word_counts) * 100
        if word_counts else 0
    )

    bestsellers_over_50 = sum(1 for b in data.bestsellers if b.has_50_plus)

    return {
        "url": data.base_url,
        "review_texts": all_reviews,
        "avg_word_count": avg_word_count,
        "pct_short_reviews": pct_short,
        "total_reviews_visible": len(all_reviews),
        "reviews_above_fold": stars_above_fold,
        "has_nav_review_link": data.homepage.has_nav_review_link,
        "has_reviews_page": False,
        "media_count_page1": total_photos,
        "has_video_reviews": total_videos > 0,
        "bestseller_review_counts": [
            b.review_count for b in data.bestsellers if b.review_count is not None
        ],
        "bestsellers_over_50": bestsellers_over_50,
        "bestsellers_checked": len(data.bestsellers),
        "has_category_stars": data.category_page.has_stars_on_cards,
        "llm_can_quote_review": data.llm_probe.can_quote,
        "llm_quote_response": data.llm_probe.quote_response,
        "llm_common_complaint": data.llm_probe.complaint_response,
        "performance_score": data.page_speed.score,
        "lcp_ms": data.page_speed.lcp_ms,
        "fcp_ms": data.page_speed.fcp_ms,
        "review_platform": data.homepage.detected_platform,
        "has_review_schema": has_review_schema,
        "has_aggregate_rating_schema": has_aggregate_rating,
        "google_stars_in_serp": has_aggregate_rating,
        "detected_vertical": data.vertical_signals.detected_vertical,
        "vertical_signal_found": ", ".join(data.vertical_signals.signals_found),
        "most_recent_review_date": all_dates[0] if all_dates else "",
        "pdp_urls": [p.url for p in data.pdps_visited],
        "audit_notes": data.audit_notes,
        # Screenshots (base64 strings for direct embedding)
        "screenshots_b64": {
            "pdp_reviews": next(
                (p.screenshot_base64 for p in data.pdps_visited if p.screenshot_base64), ""
            ),
            "category_stars": data.category_page.screenshot_base64,
            "pdp_above_fold": next(
                (p.screenshot_base64 for p in data.pdps_visited if p.stars_above_fold), ""
            ),
            "homepage": data.homepage.screenshot_base64,
        },
    }


# ── Scorer: produce dimension dict from Chrome signals ────────────────────────

def score_from_chrome_data(data: ChromeAuditData, signals: dict) -> Dict[str, dict]:
    """
    Score all 9 dimensions directly from Chrome audit data.
    Mirrors the logic in each dimension/*.py module.
    """
    scores: Dict[str, dict] = {}

    # 1. LLM Crawlability — 20pts
    llm_pts = 0.0
    llm_notes = []
    if signals["llm_can_quote_review"]:
        llm_pts += 10
        llm_notes.append("LLM can quote reviews from site")
    else:
        llm_notes.append("LLM cannot access review content")
    if signals["has_aggregate_rating_schema"]:
        llm_pts += 5
        llm_notes.append("AggregateRating schema present")
    if signals["has_review_schema"]:
        llm_pts += 5
        llm_notes.append("Review schema markup found")
    scores["llm_crawlability"] = {
        "score": round(min(llm_pts, SCORE_WEIGHTS["llm_crawlability"]), 1),
        "max_score": SCORE_WEIGHTS["llm_crawlability"],
        "finding": "; ".join(llm_notes) if llm_notes else "No LLM signal data.",
    }

    # 2. Review Richness — 18pts
    review_texts = signals["review_texts"]
    if not review_texts:
        scores["review_richness"] = {
            "score": 0,
            "max_score": SCORE_WEIGHTS["review_richness"],
            "finding": "No review text found.",
        }
    else:
        wc = [len(r.split()) for r in review_texts]
        avg = sum(wc) / len(wc)
        pct_thin = sum(1 for w in wc if w < 5) / len(wc)
        vol = len(review_texts)
        pts = 0.0
        if avg >= 40:    pts += 8
        elif avg >= 25:  pts += 5
        elif avg >= 15:  pts += 2
        if pct_thin < 0.05:   pts += 5
        elif pct_thin < 0.15: pts += 3
        elif pct_thin < 0.30: pts += 1
        if vol >= 20:    pts += 5
        elif vol >= 10:  pts += 3
        elif vol >= 5:   pts += 1
        scores["review_richness"] = {
            "score": round(pts, 1),
            "max_score": SCORE_WEIGHTS["review_richness"],
            "finding": (
                f"Found {vol} reviews via Chrome. "
                f"Avg length: {avg:.0f} words. "
                f"{pct_thin*100:.0f}% under 5 words."
            ),
        }

    # 3. Review Recency — 15pts
    most_recent = signals.get("most_recent_review_date", "")
    recency_pts, recency_finding = _score_recency(most_recent, SCORE_WEIGHTS["review_recency"])
    scores["review_recency"] = {
        "score": recency_pts,
        "max_score": SCORE_WEIGHTS["review_recency"],
        "finding": recency_finding,
    }

    # 4. Visibility — 12pts
    vis_pts = 0.0
    vis_notes = []
    if signals["reviews_above_fold"]:
        vis_pts += 5
        vis_notes.append("star ratings visible above the fold on PDPs")
    if signals["has_nav_review_link"]:
        vis_pts += 3
        vis_notes.append("nav link to reviews")
    if signals["has_reviews_page"]:
        vis_pts += 4
        vis_notes.append("dedicated reviews page")
    scores["visibility"] = {
        "score": round(min(vis_pts, SCORE_WEIGHTS["visibility"]), 1),
        "max_score": SCORE_WEIGHTS["visibility"],
        "finding": (
            ", ".join(vis_notes) if vis_notes
            else "No review widgets above fold, no nav link, no standalone reviews page."
        ),
    }

    # 5. Rich Snippets — 10pts
    rs_pts = 0.0
    rs_notes = []
    if signals["has_aggregate_rating_schema"]:
        rs_pts += 5
        rs_notes.append("AggregateRating schema found — stars appear in Google results")
    if signals["has_review_schema"]:
        rs_pts += 5
        rs_notes.append("Review schema markup present")
    schemas = data.rich_snippets.schema_types_found
    scores["rich_snippets"] = {
        "score": round(min(rs_pts, SCORE_WEIGHTS["rich_snippets"]), 1),
        "max_score": SCORE_WEIGHTS["rich_snippets"],
        "finding": (
            "; ".join(rs_notes) if rs_notes
            else f"No AggregateRating schema. Schemas found: {', '.join(schemas) or 'none'}."
        ),
    }

    # 6. Page Speed — 10pts
    perf = signals.get("performance_score")
    lcp = signals.get("lcp_ms")
    if perf is None:
        scores["page_speed"] = {
            "score": 0,
            "max_score": SCORE_WEIGHTS["page_speed"],
            "finding": "PageSpeed data not collected.",
        }
    else:
        pts = 0.0
        if perf >= 90:   pts += 10
        elif perf >= 70: pts += 7
        elif perf >= 50: pts += 4
        elif perf >= 30: pts += 2
        lcp_str = f"LCP {lcp/1000:.1f}s" if lcp else ""
        scores["page_speed"] = {
            "score": round(pts, 1),
            "max_score": SCORE_WEIGHTS["page_speed"],
            "finding": f"Mobile performance score: {perf:.0f}/100. {lcp_str}".strip(". ") + ".",
        }

    # 7. Bestseller Depth — 8pts
    bs_checked = signals["bestsellers_checked"]
    bs_over_50 = signals["bestsellers_over_50"]
    if bs_checked == 0:
        scores["bestseller_depth"] = {
            "score": 0,
            "max_score": SCORE_WEIGHTS["bestseller_depth"],
            "finding": "Could not access bestseller products.",
        }
    else:
        ratio = bs_over_50 / bs_checked
        avg_count = (
            sum(c for c in signals["bestseller_review_counts"] if c is not None) //
            max(len([c for c in signals["bestseller_review_counts"] if c is not None]), 1)
        )
        scores["bestseller_depth"] = {
            "score": round(SCORE_WEIGHTS["bestseller_depth"] * ratio, 1),
            "max_score": SCORE_WEIGHTS["bestseller_depth"],
            "finding": (
                f"{bs_over_50}/{bs_checked} top products have 50+ reviews "
                f"(avg {avg_count} reviews). "
                + ("Strong review depth." if ratio >= 0.8
                   else "Most top SKUs need more reviews.")
            ),
        }

    # 8. Stars on Category — 4pts
    if signals["has_category_stars"]:
        scores["stars_on_category"] = {
            "score": SCORE_WEIGHTS["stars_on_category"],
            "max_score": SCORE_WEIGHTS["stars_on_category"],
            "finding": f"Star ratings found on category page ({data.category_page.url}).",
        }
    else:
        scores["stars_on_category"] = {
            "score": 0,
            "max_score": SCORE_WEIGHTS["stars_on_category"],
            "finding": "No star ratings on category pages. Adding them lifts PDP click-through ~30%.",
        }

    # 9. Vertical Signals — 3pts
    vertical = signals.get("detected_vertical", "")
    v_signals = signals.get("vertical_signal_found", "")
    if vertical and v_signals:
        scores["vertical_signals"] = {
            "score": SCORE_WEIGHTS["vertical_signals"],
            "max_score": SCORE_WEIGHTS["vertical_signals"],
            "finding": f"Vertical: {vertical}. Signals: {v_signals}.",
        }
    elif vertical:
        scores["vertical_signals"] = {
            "score": round(SCORE_WEIGHTS["vertical_signals"] * 0.5, 1),
            "max_score": SCORE_WEIGHTS["vertical_signals"],
            "finding": f"Vertical detected: {vertical}. No specific review signals found.",
        }
    else:
        scores["vertical_signals"] = {
            "score": 0,
            "max_score": SCORE_WEIGHTS["vertical_signals"],
            "finding": "No vertical signals detected.",
        }

    return scores


# ── Recency helper ────────────────────────────────────────────────────────────

def _score_recency(date_str: str, max_pts: int) -> tuple:
    """Parse a date string and score based on how recent it is."""
    if not date_str:
        return 0, "No review dates found."

    now = datetime.utcnow()
    parsed = _parse_date(date_str)

    if not parsed:
        return round(max_pts * 0.5, 1), f"Most recent review date: {date_str} (could not parse exactly)."

    days_old = (now - parsed).days
    if days_old <= 30:
        pts = max_pts
        label = "within 30 days"
    elif days_old <= 60:
        pts = round(max_pts * 0.85, 1)
        label = "within 60 days"
    elif days_old <= 90:
        pts = round(max_pts * 0.6, 1)
        label = "within 90 days"
    elif days_old <= 180:
        pts = round(max_pts * 0.3, 1)
        label = "within 6 months"
    else:
        pts = 0
        label = "over 6 months ago"

    return pts, f"Most recent review: {date_str} ({label})."


def _parse_date(date_str: str) -> Optional[datetime]:
    """Best-effort date parsing for review date strings."""
    import re as _re
    s = date_str.strip()
    formats = [
        "%B %d, %Y",   # March 15, 2026
        "%b %d, %Y",   # Mar 15, 2026
        "%m/%d/%Y",    # 03/15/2026
        "%Y-%m-%d",    # 2026-03-15
        "%d %B %Y",    # 15 March 2026
        "%B %Y",       # March 2026
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass

    # Relative: "3 months ago", "2 weeks ago", "yesterday"
    s_low = s.lower()
    m = _re.search(r"(\d+)\s*(day|week|month|year)", s_low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return datetime.utcnow() - timedelta(days=delta)
    if "yesterday" in s_low:
        return datetime.utcnow() - timedelta(days=1)
    if "today" in s_low:
        return datetime.utcnow()

    return None
