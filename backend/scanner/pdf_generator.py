"""Client-facing Reviews Experience Audit (PDF) — a courtesy audit a Yotpo rep
can send straight to the brand.

This is the SHAREABLE artifact, so it is consultative and brand-safe: no internal
sales strategy (displacement angles, "the pitch", "where Yotpo wins"), no tool
diagnostics ("could not extract", API-key notes), no negging. The internal sales
intelligence stays in the web app, which only the Yotpo team can see.

Rendered to PDF via headless Chromium (browser.generate_pdf_bytes).
"""

import base64
import html as _html
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Dict

from .branding import yotpo_logo_data_uri

logger = logging.getLogger(__name__)

PDF_BASE = Path(os.environ.get("PDF_DIR", "/pdfs"))

DIMENSION_ORDER = [
    "llm_crawlability", "review_richness", "review_recency", "visibility",
    "rich_snippets", "page_speed", "bestseller_depth", "stars_on_category", "vertical_signals",
]

DIMENSION_LABELS = {
    "llm_crawlability":  "AI & LLM Readability",
    "review_richness":   "Review Depth",
    "review_recency":    "Review Freshness",
    "visibility":        "On-site Visibility",
    "rich_snippets":     "Google Rich Snippets",
    "page_speed":        "Page Speed",
    "bestseller_depth":  "Bestseller Coverage",
    "stars_on_category": "Stars on Collections",
    "vertical_signals":  "Category Signals",
}

WHY_IT_MATTERS = {
    "llm_crawlability":  "Whether AI assistants and search engines can read your reviews.",
    "review_richness":   "Detailed reviews (40+ words) are what shoppers trust.",
    "review_recency":    "Fresh reviews reassure shoppers; stale ones cost sales.",
    "visibility":        "Stars above the fold reduce bounce and lift add-to-cart.",
    "rich_snippets":     "Star ratings in Google results lift organic click-through.",
    "page_speed":        "A fast reviews experience protects mobile conversion.",
    "bestseller_depth":  "Top products need depth to rank and convert.",
    "stars_on_category": "Stars on collection pages lift click-through to PDPs.",
    "vertical_signals":  "Surfacing the themes shoppers search for drives conversion.",
}

# Consultative opportunity copy per dimension — benefit-first, brand-safe.
OPPORTUNITY = {
    "llm_crawlability":  ("Make your reviews readable by AI search",
        "Structured review data lets ChatGPT, Perplexity, and Google read and quote your reviews — increasingly where product discovery starts."),
    "review_richness":   ("Capture richer, more detailed reviews",
        "Prompting customers for specifics at review time produces the 40+ word reviews shoppers rely on to buy with confidence."),
    "review_recency":    ("Keep a steady stream of fresh reviews",
        "Automated post-purchase requests keep recent reviews flowing on every product page — 60% of shoppers hesitate when the newest review is months old."),
    "visibility":        ("Put social proof above the fold",
        "Surfacing star ratings and review highlights where shoppers decide reduces bounce and lifts add-to-cart."),
    "rich_snippets":     ("Win star ratings in Google results",
        "AggregateRating markup places star ratings directly in search results and lifts organic click-through."),
    "page_speed":        ("Keep the reviews experience fast on mobile",
        "A lightweight review experience protects mobile load time — every 100ms of delay costs roughly 1% of conversions."),
    "bestseller_depth":  ("Build review depth on your top products",
        "Getting bestsellers to 50+ reviews helps them rank in search and convert at full strength."),
    "stars_on_category": ("Show star ratings on collection pages",
        "Stars on category pages lift click-through to product pages by up to 30%."),
    "vertical_signals":  ("Surface the language shoppers search for",
        "Highlighting the themes buyers look for — taste, ingredients, results — drawn from your own reviews helps shoppers self-qualify."),
}

GRADE_VERDICT = {
    "A": "An excellent reviews experience.",
    "B": "A strong reviews experience with a few opportunities.",
    "C": "A solid foundation with clear opportunities to grow.",
    "D": "Several high-impact opportunities to strengthen your reviews experience.",
    "F": "Several high-impact opportunities to strengthen your reviews experience.",
}

# Screenshot stem → honest caption (no claims the image can't back up).
SCREENSHOT_LABELS = {
    "pdp_reviews":    "Product page",
    "category_stars": "Collection page",
    "pdp_above_fold": "Product page",
    "homepage":       "Homepage",
    "bestsellers":    "Best-sellers page",
}


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _client_finding(key: str, finding: str, has_reviews: bool) -> str:
    """Rewrite internal/diagnostic findings into brand-safe language."""
    f = finding or ""
    low = f.lower()
    # Never expose tool diagnostics or config notes
    if "google_pagespeed_api_key" in low or "not measured" in low:
        return "Not assessed in this audit."
    if "could not extract review dates" in low:
        return ("Review dates aren't exposed in the page's HTML, so freshness isn't "
                "visible to search engines or AI assistants.") if has_reviews else "Not assessed in this audit."
    if "no review text found" in low:
        return ("Review content is served by your on-site widget and isn't embedded in the "
                "page HTML, so AI assistants and search engines can't read it.")
    if "scoring error" in low or "check failed" in low:
        return "Not assessed in this audit."
    return f


def render_html(
    brand_name: str,
    domain: str,
    account_owner: str,
    overall_score: int,
    grade: str,
    scores: Dict[str, dict],
    pitch_angles: List[str],
    detected_platform: Optional[str],
    sf_platform: Optional[str],
    platform_mismatch: bool,
    vertical: Optional[str],
    page_speed_score: Optional[float],
    page_speed_lcp: str,
    screenshot_paths: List[str],
    brand_logo_b64: str,
    scan_ts: str,
) -> str:

    yotpo_logo = yotpo_logo_data_uri()
    grade_color = {"A": "#16a34a", "B": "#16a34a", "C": "#f59e0b",
                   "D": "#ef4444", "F": "#ef4444"}.get(grade, "#f59e0b")
    verdict = GRADE_VERDICT.get(grade, "")
    has_reviews = scores.get("rich_snippets", {}).get("score", 0) > 0  # aggregateRating ⇒ reviews exist

    # ── Top opportunities: the 3 weakest dimensions, consultatively framed ────
    ranked = sorted(
        [k for k in DIMENSION_ORDER if k in scores and scores[k].get("measured", True)],
        key=lambda k: scores[k].get("score", 0) / max(scores[k].get("max_score", 1), 1),
    )
    opp_html = ""
    for n, k in enumerate(ranked[:3], 1):
        title, blurb = OPPORTUNITY.get(k, (DIMENSION_LABELS.get(k, k), ""))
        opp_html += f"""
        <div class="opp">
          <div class="opp-n">{n}</div>
          <div><div class="opp-t">{_esc(title)}</div><div class="opp-b">{_esc(blurb)}</div></div>
        </div>"""

    # ── Detailed findings (sanitized) ─────────────────────────────────────────
    # Client-facing: only show dimensions we actually measured. Anything we
    # couldn't assess is omitted entirely (it stays in the internal web report).
    dim_rows = ""
    measured_keys = [k for k in DIMENSION_ORDER
                     if k in scores and scores[k].get("measured", True)]
    for i, key in enumerate(measured_keys):
        dim = scores.get(key, {})
        s = dim.get("score", 0)
        m = dim.get("max_score", 0) or 1
        row_bg = "#F6F6F7" if i % 2 == 1 else "#FFFFFF"
        finding = _client_finding(key, dim.get("finding", ""), has_reviews)
        pct = min(s / m * 100, 100)
        bar = "#16a34a" if pct >= 70 else ("#f59e0b" if pct >= 40 else "#ef4444")
        score_cell = (f'<div class="bw"><div class="b" style="width:{pct:.0f}%;background:{bar}"></div></div>'
                      f'<span class="sn">{s:.0f}/{m}</span>')
        dim_rows += f"""
        <tr style="background:{row_bg}">
          <td class="dn"><strong>{_esc(DIMENSION_LABELS.get(key, key))}</strong><span class="why">{_esc(WHY_IT_MATTERS.get(key, ''))}</span></td>
          <td class="ds">{score_cell}</td>
          <td class="df">{_esc(finding)}</td>
        </tr>"""

    # ── Evidence screenshots — each proves a finding (captioned accordingly) ───
    ss_html = ""
    for sp in (screenshot_paths or [])[:3]:
        # Each item is either a {path, caption} dict (evidence) or a bare path.
        if isinstance(sp, dict):
            path, caption = sp.get("path"), sp.get("caption", "")
        else:
            path, caption = sp, SCREENSHOT_LABELS.get(Path(sp).stem, "")
        try:
            b64 = base64.b64encode(Path(path).read_bytes()).decode()
        except Exception:
            continue
        ss_html += f"""
        <div class="ss-item"><img class="ss" src="data:image/png;base64,{b64}" />
          <div class="ss-cap">{_esc(caption)}</div></div>"""
    screenshots_section = (
        f'<div class="sec-h">Evidence — what we found on the page</div>'
        f'<div class="ssg">{ss_html}</div>' if ss_html else ""
    )

    chips = []
    if detected_platform:
        chips.append(("Current reviews platform", detected_platform))
    if vertical:
        chips.append(("Category", vertical.title()))
    chips_html = "".join(
        f'<div class="chip"><span class="chip-l">{_esc(l)}</span><span class="chip-v">{_esc(v)}</span></div>'
        for l, v in chips
    )

    brand_mark = (
        f'<img class="bl" src="{brand_logo_b64}" />'
        if brand_logo_b64 else f'<span class="brand-name-hdr">{_esc(brand_name)}</span>'
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
@page {{ size: letter; margin: 0.5in; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 8.5pt; color: #111; background: #fff;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.hdr {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 8pt; border-bottom: 1.5pt solid #111; margin-bottom: 10pt; }}
.hdr-left {{ display: flex; align-items: center; gap: 9pt; }}
.yl {{ height: 20pt; }}
.hdr-tag {{ font-size: 7pt; color: #666; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }}
.bl {{ max-height: 26pt; max-width: 110pt; object-fit: contain; }}
.brand-name-hdr {{ font-size: 14pt; font-weight: 800; color: #111; }}
.hero {{ display: flex; align-items: center; gap: 14pt; padding: 12pt 14pt; background: #0B0B0B; border-radius: 6pt; color: #fff; margin-bottom: 8pt; }}
.ring {{ width: 70pt; height: 70pt; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; border: 4pt solid {grade_color}; }}
.ring .g {{ font-size: 30pt; font-weight: 900; line-height: 1; color: {grade_color}; }}
.ring .s {{ font-size: 8pt; color: #ccc; margin-top: 1pt; }}
.hero-brand {{ font-size: 15pt; font-weight: 800; }}
.hero-domain {{ font-size: 8pt; color: #aaa; margin-bottom: 5pt; }}
.hero-verdict {{ font-size: 10pt; font-weight: 600; }}
.hero-sub {{ font-size: 7.5pt; color: #bbb; margin-top: 3pt; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 5pt; margin-bottom: 10pt; }}
.chip {{ background: #F0F0F2; border-radius: 4pt; padding: 3pt 7pt; }}
.chip-l {{ font-size: 6pt; color: #888; text-transform: uppercase; letter-spacing: 0.05em; display: block; }}
.chip-v {{ font-size: 8pt; font-weight: 700; color: #111; }}
.sec-h {{ font-size: 8pt; font-weight: 800; color: #111; text-transform: uppercase; letter-spacing: 0.08em; margin: 10pt 0 6pt; padding-bottom: 3pt; border-bottom: 0.75pt solid #ddd; }}
.opp {{ display: flex; gap: 8pt; align-items: flex-start; padding: 7pt 0; border-bottom: 0.5pt solid #eee; }}
.opp:last-child {{ border-bottom: none; }}
.opp-n {{ flex-shrink: 0; width: 16pt; height: 16pt; border-radius: 50%; background: #1F6FFF; color: #fff; font-size: 9pt; font-weight: 800; display: flex; align-items: center; justify-content: center; }}
.opp-t {{ font-size: 9.5pt; font-weight: 700; color: #111; }}
.opp-b {{ font-size: 8pt; color: #444; line-height: 1.45; margin-top: 1pt; }}
table.dt {{ width: 100%; border-collapse: collapse; }}
table.dt th {{ text-align: left; font-size: 6.5pt; font-weight: 800; color: #fff; background: #111; padding: 4pt 7pt; text-transform: uppercase; letter-spacing: 0.05em; }}
table.dt td {{ padding: 4pt 7pt; vertical-align: top; }}
.dn {{ width: 26%; }} .dn strong {{ font-size: 8pt; font-weight: 700; color: #111; display: block; }}
.why {{ font-weight: 400; color: #888; font-size: 6.5pt; display: block; margin-top: 1pt; line-height: 1.3; }}
.ds {{ width: 17%; }} .bw {{ height: 6pt; background: #e5e5e7; border-radius: 3pt; margin: 3pt 0 2pt; }} .b {{ height: 6pt; border-radius: 3pt; }} .sn {{ font-size: 6.5pt; color: #666; }} .na {{ font-size: 7pt; color: #999; font-style: italic; }}
.df {{ width: 57%; font-size: 7pt; color: #333; line-height: 1.4; }}
.ssg {{ display: flex; gap: 7pt; }}
.ss-item {{ flex: 1; }} .ss {{ width: 100%; height: 64pt; object-fit: cover; object-position: top; border: 0.75pt solid #ddd; border-radius: 3pt; }}
.ss-cap {{ font-size: 6.5pt; color: #555; margin-top: 2pt; }}
.ft {{ margin-top: 10pt; padding-top: 5pt; border-top: 0.75pt solid #eee; font-size: 6.5pt; color: #999; display: flex; justify-content: space-between; }}
</style></head><body>

<div class="hdr">
  <div class="hdr-left"><img class="yl" src="{yotpo_logo}" /><span class="hdr-tag">Reviews Experience Audit</span></div>
  {brand_mark}
</div>

<div class="hero">
  <div class="ring"><div class="g">{_esc(grade)}</div><div class="s">{int(overall_score or 0)}/100</div></div>
  <div>
    <div class="hero-brand">{_esc(brand_name)}</div>
    <div class="hero-domain">{_esc(domain)}</div>
    <div class="hero-verdict">{_esc(verdict)}</div>
    <div class="hero-sub">An independent look at your on-site reviews experience and where it can drive more revenue.</div>
  </div>
</div>

<div class="chips">{chips_html}</div>

<div class="sec-h">Top opportunities</div>
{opp_html}

<div class="sec-h">Detailed findings</div>
<table class="dt">
  <tr><th>Area</th><th>Score</th><th>What we found</th></tr>
  {dim_rows}
</table>

{screenshots_section}

<div class="ft">
  <span>Prepared for {_esc(brand_name)} by Yotpo · {_esc(scan_ts[:10])}</span>
  <span>Yotpo · yotpo.com</span>
</div>
</body></html>"""


async def generate(scan_id: str, **kwargs) -> Optional[str]:
    """Render HTML → PDF via Playwright Chromium. Falls back to .html on error."""
    from .browser import generate_pdf_bytes

    PDF_BASE.mkdir(parents=True, exist_ok=True)
    html_content = render_html(**kwargs)
    out_path = PDF_BASE / f"{scan_id}.pdf"
    try:
        logger.info("Playwright PDF: starting for scan %s", scan_id)
        pdf_bytes = await generate_pdf_bytes(html_content)
        out_path.write_bytes(pdf_bytes)
        logger.info("Playwright PDF: written to %s (%d bytes)", out_path, len(pdf_bytes))
        return str(out_path)
    except Exception as exc:
        logger.error("Playwright PDF FAILED for scan %s — %s: %s", scan_id, type(exc).__name__, exc, exc_info=True)
    html_path = PDF_BASE / f"{scan_id}.html"
    html_path.write_text(html_content, encoding="utf-8")
    logger.warning("Fell back to HTML for scan %s — saved %s", scan_id, html_path)
    return str(html_path)
