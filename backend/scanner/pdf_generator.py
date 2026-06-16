"""Exec-ready PDF brief per brand — Yotpo-branded, real logos, product-mapped.

Rendered to PDF via headless Chromium (see browser.generate_pdf_bytes). The brief
leads with the grade and the displacement/pitch angle, maps the weakest dimensions
to specific Yotpo Reviews capabilities, then backs it with the full breakdown and
real screenshots.
"""

import base64
import html as _html
import logging
import os
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
    "llm_crawlability":  "LLM Crawlability",
    "review_richness":   "Review Richness",
    "review_recency":    "Review Recency",
    "visibility":        "Visibility / Discoverability",
    "rich_snippets":     "Rich Snippets",
    "page_speed":        "Page Speed",
    "bestseller_depth":  "Bestseller Depth",
    "stars_on_category": "Stars on Category Pages",
    "vertical_signals":  "Vertical Signals",
}

WHY_IT_MATTERS = {
    "llm_crawlability":  "AI assistants can't recommend products they can't read.",
    "review_richness":   "Shoppers need 40+ words to trust a purchase decision.",
    "review_recency":    "60% of shoppers won't buy if the newest review is 3+ months old.",
    "visibility":        "Stars above the fold reduce bounce rate.",
    "rich_snippets":     "AggregateRating schema = star ratings in Google search results.",
    "page_speed":        "Every 100ms of delay costs ~1% in mobile conversions.",
    "bestseller_depth":  "Top products need 50+ reviews to rank and convert.",
    "stars_on_category": "Star ratings on collections lift PDP click-through ~30%.",
    "vertical_signals":  "Fit/ingredient language in reviews drives category-specific lifts.",
}

# Each gap → the specific Yotpo Reviews capability that closes it.
PRODUCT_PLAYS = {
    "llm_crawlability":  ("Yotpo Reviews — AI TLDR & Review SEO",
                          "Machine-readable review content + AI TLDR summaries so ChatGPT, Perplexity and Google can quote the brand."),
    "review_richness":   ("Yotpo Reviews — Smart Prompts",
                          "Smart Prompts ask the right question at request time, so reviews come back detailed instead of one-liners."),
    "review_recency":    ("Yotpo Reviews — Automated Requests",
                          "Post-purchase review requests keep a steady stream of fresh, recent reviews on every PDP."),
    "visibility":        ("Yotpo Reviews — On-site Widgets",
                          "Star widgets above the fold plus AI review highlights put social proof where it converts."),
    "rich_snippets":     ("Yotpo Reviews — Rich Snippets",
                          "AggregateRating schema out of the box = star ratings in Google results and higher organic CTR."),
    "page_speed":        ("Yotpo Reviews — Lightweight Widget",
                          "A fast widget replaces a heavy incumbent script, recovering the mobile speed that drives conversion."),
    "bestseller_depth":  ("Yotpo Reviews — Review Generation",
                          "Generation campaigns build 50+ reviews on top SKUs so they rank in search and convert at full rate."),
    "stars_on_category": ("Yotpo Reviews — Category Stars",
                          "Star ratings on collection pages lift PDP click-through by up to 30%."),
    "vertical_signals":  ("Yotpo Reviews — Smart Topics",
                          "Smart topic filters surface the fit / ingredient / durability language buyers actually search for."),
}

# Incumbent review vendors worth a displacement angle.
COMPETITORS = {
    "BazaarVoice":  "an expensive enterprise contract — the classic Yotpo displacement: faster widget, lower cost, modern AI features.",
    "PowerReviews": "a legacy enterprise platform — Yotpo wins on AI features, speed, and a cleaner merchant experience.",
    "Okendo":       "a Shopify-native competitor — Yotpo differentiates on AI (TLDR, Smart Topics), loyalty tie-in, and scale.",
    "Stamped.io":   "a lighter-weight tool — Yotpo wins on depth, AI, and the full retention suite.",
    "Trustpilot":   "off-site reviews only — Yotpo adds on-site UGC, schema, and PDP conversion that Trustpilot can't.",
    "Reviews.io":   "a mid-market tool — Yotpo wins on AI features and the integrated retention platform.",
    "Loox":         "photo-review focused — Yotpo offers richer UGC, AI, and the full Reviews + Loyalty stack.",
    "Judge.me":     "an entry-level app — a clear upgrade path to Yotpo as the brand scales.",
}

# Score most healthy Yotpo customers clear — used for the benchmark line.
BENCHMARK_TARGET = 70

SCREENSHOT_META = {
    "pdp_reviews":    ("review_richness",   "PDP — Reviews Section"),
    "category_stars": ("stars_on_category", "Category Page — Stars"),
    "pdp_above_fold": ("visibility",        "PDP — Above the Fold"),
    "homepage":       ("visibility",        "Homepage"),
    "bestsellers":    ("bestseller_depth",  "Best-Sellers Page"),
}

GRADE_VERDICT = {
    "A": "Excellent reviews experience — lead with expansion, not fixes.",
    "B": "Good foundation with clear gaps to close.",
    "C": "Average — clear, winnable opportunities.",
    "D": "Below average — strong case for Yotpo.",
    "F": "Poor — urgent case for Yotpo.",
}


def _esc(s) -> str:
    return _html.escape(str(s or ""))


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
    grade_color = {
        "A": "#16a34a", "B": "#16a34a", "C": "#f59e0b", "D": "#ef4444", "F": "#ef4444",
    }.get(grade, "#ef4444")
    verdict = GRADE_VERDICT.get(grade, "")

    # ── Weakest dimensions → Yotpo plays ──────────────────────────────────────
    ranked = sorted(
        DIMENSION_ORDER,
        key=lambda k: (scores.get(k, {}).get("score", 0) / max(scores.get(k, {}).get("max_score", 1), 1)),
    )
    weakest = [k for k in ranked if k in scores][:3]
    plays_html = ""
    for k in weakest:
        title, blurb = PRODUCT_PLAYS.get(k, ("Yotpo Reviews", ""))
        plays_html += f"""
        <div class="play">
          <div class="play-gap">{_esc(DIMENSION_LABELS.get(k, k))}</div>
          <div class="play-prod">{_esc(title)}</div>
          <div class="play-blurb">{_esc(blurb)}</div>
        </div>"""

    # ── Displacement callout ──────────────────────────────────────────────────
    displacement_html = ""
    incumbent = detected_platform if detected_platform in COMPETITORS else None
    if incumbent:
        displacement_html = f"""
        <div class="disp">
          <span class="disp-tag">Displacement angle</span>
          <span class="disp-txt"><strong>{_esc(brand_name)}</strong> is on <strong>{_esc(incumbent)}</strong> — {_esc(COMPETITORS[incumbent])}</span>
        </div>"""

    # ── Pitch angles ──────────────────────────────────────────────────────────
    pitch_html = ""
    for i, angle in enumerate(pitch_angles[:3], 1):
        pitch_html += f'<div class="pitch"><span class="pn">{i}</span><span class="pt">{_esc(angle)}</span></div>'
    if not pitch_html:
        pitch_html = '<div class="pitch"><span class="pt">No pitch angles generated for this scan.</span></div>'

    # ── Dimension rows ────────────────────────────────────────────────────────
    dim_rows = ""
    for i, key in enumerate(DIMENSION_ORDER):
        dim = scores.get(key, {})
        s = dim.get("score", 0)
        m = dim.get("max_score", 0) or 1
        pct = min(s / m * 100, 100)
        bar = "#16a34a" if pct >= 70 else ("#f59e0b" if pct >= 40 else "#ef4444")
        row_bg = "#F6F6F7" if i % 2 == 1 else "#FFFFFF"
        dim_rows += f"""
        <tr style="background:{row_bg}">
          <td class="dn"><strong>{_esc(DIMENSION_LABELS.get(key, key))}</strong><span class="why">{_esc(WHY_IT_MATTERS.get(key, ''))}</span></td>
          <td class="ds">
            <div class="bw"><div class="b" style="width:{pct:.0f}%;background:{bar}"></div></div>
            <span class="sn">{s:.0f}/{m}</span>
          </td>
          <td class="df">{_esc(dim.get('finding', ''))}</td>
        </tr>"""

    # ── Screenshots ───────────────────────────────────────────────────────────
    ss_html = ""
    for sp in (screenshot_paths or [])[:3]:
        try:
            b64 = base64.b64encode(Path(sp).read_bytes()).decode()
        except Exception:
            continue
        stem = Path(sp).stem
        _, page_title = SCREENSHOT_META.get(stem, (None, stem.replace("_", " ").title()))
        ss_html += f"""
        <div class="ss-item">
          <img class="ss" src="data:image/png;base64,{b64}" />
          <div class="ss-cap">{_esc(brand_name)} — {_esc(page_title)}</div>
        </div>"""
    screenshots_section = (
        f'<div class="sec-h">What the scanner saw</div><div class="ssg">{ss_html}</div>'
        if ss_html else ""
    )

    # ── Meta chips ────────────────────────────────────────────────────────────
    chips = []
    if detected_platform:
        chips.append(("Detected platform", detected_platform))
    if sf_platform:
        chips.append(("Salesforce platform", sf_platform))
    if platform_mismatch:
        chips.append(("⚠ Mismatch", "Live ≠ Salesforce"))
    if vertical:
        chips.append(("Vertical", vertical.title()))
    chips_html = "".join(
        f'<div class="chip"><span class="chip-l">{_esc(l)}</span><span class="chip-v">{_esc(v)}</span></div>'
        for l, v in chips
    )

    brand_mark = (
        f'<img class="bl" src="{brand_logo_b64}" />'
        if brand_logo_b64 else f'<span class="brand-name-hdr">{_esc(brand_name)}</span>'
    )

    gap = max(BENCHMARK_TARGET - int(overall_score or 0), 0)
    benchmark_line = (
        f"Healthy Yotpo customers clear {BENCHMARK_TARGET}/100. "
        + (f"{_esc(brand_name)} is {gap} points short." if gap else f"{_esc(brand_name)} is already there.")
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
@page {{ size: letter; margin: 0.5in; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: Helvetica, Arial, sans-serif; font-size: 8.5pt; color: #111; background: #fff;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}}

/* Header */
.hdr {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 8pt; border-bottom: 1.5pt solid #111; margin-bottom: 10pt; }}
.hdr-left {{ display: flex; align-items: center; gap: 9pt; }}
.yl {{ height: 20pt; }}
.hdr-tag {{ font-size: 7pt; color: #666; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }}
.bl {{ max-height: 26pt; max-width: 110pt; object-fit: contain; }}
.brand-name-hdr {{ font-size: 14pt; font-weight: 800; color: #111; }}

/* Hero */
.hero {{ display: flex; align-items: center; gap: 14pt; padding: 12pt 14pt; background: #0B0B0B; border-radius: 6pt; color: #fff; margin-bottom: 6pt; }}
.ring {{ width: 70pt; height: 70pt; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; border: 4pt solid {grade_color}; }}
.ring .g {{ font-size: 30pt; font-weight: 900; line-height: 1; color: {grade_color}; }}
.ring .s {{ font-size: 8pt; color: #ccc; margin-top: 1pt; }}
.hero-main {{ flex: 1; }}
.hero-brand {{ font-size: 15pt; font-weight: 800; }}
.hero-domain {{ font-size: 8pt; color: #aaa; margin-bottom: 5pt; }}
.hero-verdict {{ font-size: 9.5pt; font-weight: 600; color: #fff; }}
.hero-bench {{ font-size: 7.5pt; color: #bbb; margin-top: 3pt; }}

/* Chips */
.chips {{ display: flex; flex-wrap: wrap; gap: 5pt; margin-bottom: 9pt; }}
.chip {{ background: #F0F0F2; border-radius: 4pt; padding: 3pt 7pt; }}
.chip-l {{ font-size: 6pt; color: #888; text-transform: uppercase; letter-spacing: 0.05em; display: block; }}
.chip-v {{ font-size: 8pt; font-weight: 700; color: #111; }}

/* Displacement */
.disp {{ background: #FEF3C7; border-left: 3pt solid #F59E0B; border-radius: 4pt; padding: 6pt 9pt; margin-bottom: 9pt; }}
.disp-tag {{ font-size: 6.5pt; font-weight: 800; color: #92400E; text-transform: uppercase; letter-spacing: 0.06em; margin-right: 6pt; }}
.disp-txt {{ font-size: 8pt; color: #5b3d09; }}

/* Section headers */
.sec-h {{ font-size: 8pt; font-weight: 800; color: #111; text-transform: uppercase; letter-spacing: 0.08em; margin: 9pt 0 5pt; padding-bottom: 3pt; border-bottom: 0.75pt solid #ddd; }}

/* Pitch */
.recs {{ background: #0B0B0B; border-radius: 5pt; padding: 9pt 12pt; margin-bottom: 4pt; }}
.recs-lbl {{ font-size: 7pt; font-weight: 800; color: #fff; margin-bottom: 6pt; letter-spacing: 0.09em; text-transform: uppercase; }}
.pitch {{ display: flex; gap: 7pt; margin-bottom: 5pt; align-items: flex-start; }}
.pitch:last-child {{ margin-bottom: 0; }}
.pn {{ font-weight: 900; font-size: 11pt; color: {grade_color}; flex-shrink: 0; width: 12pt; text-align: right; }}
.pt {{ font-size: 8pt; color: #fff; line-height: 1.45; }}

/* Plays */
.plays {{ display: flex; gap: 7pt; margin-bottom: 4pt; }}
.play {{ flex: 1; background: #F6F6F7; border-radius: 5pt; padding: 8pt 9pt; border-top: 2.5pt solid #1F6FFF; }}
.play-gap {{ font-size: 6.5pt; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
.play-prod {{ font-size: 8.5pt; font-weight: 800; color: #111; margin: 2pt 0 3pt; }}
.play-blurb {{ font-size: 7.5pt; color: #444; line-height: 1.4; }}

/* Breakdown table */
table.dt {{ width: 100%; border-collapse: collapse; }}
table.dt th {{ text-align: left; font-size: 6.5pt; font-weight: 800; color: #fff; background: #111; padding: 4pt 7pt; text-transform: uppercase; letter-spacing: 0.05em; }}
table.dt td {{ padding: 4pt 7pt; vertical-align: top; }}
.dn {{ width: 27%; }}
.dn strong {{ font-size: 8pt; font-weight: 700; color: #111; display: block; }}
.why {{ font-weight: 400; color: #888; font-size: 6.5pt; display: block; margin-top: 1pt; line-height: 1.35; }}
.ds {{ width: 17%; }}
.bw {{ height: 6pt; background: #e5e5e7; border-radius: 3pt; margin: 3pt 0 2pt; }}
.b {{ height: 6pt; border-radius: 3pt; }}
.sn {{ font-size: 6.5pt; color: #666; }}
.df {{ width: 56%; font-size: 7pt; color: #333; line-height: 1.4; }}

/* Screenshots */
.ssg {{ display: flex; gap: 7pt; }}
.ss-item {{ flex: 1; display: flex; flex-direction: column; }}
.ss {{ width: 100%; height: 64pt; object-fit: cover; object-position: top; border: 0.75pt solid #ddd; border-radius: 3pt; }}
.ss-cap {{ font-size: 6pt; color: #666; margin-top: 2pt; line-height: 1.3; }}

.ft {{ margin-top: 9pt; padding-top: 5pt; border-top: 0.75pt solid #eee; font-size: 6.5pt; color: #999; display: flex; justify-content: space-between; }}
</style></head><body>

<div class="hdr">
  <div class="hdr-left">
    <img class="yl" src="{yotpo_logo}" />
    <span class="hdr-tag">Reviews Intelligence Brief</span>
  </div>
  {brand_mark}
</div>

<div class="hero">
  <div class="ring"><div class="g">{_esc(grade)}</div><div class="s">{int(overall_score or 0)}/100</div></div>
  <div class="hero-main">
    <div class="hero-brand">{_esc(brand_name)}</div>
    <div class="hero-domain">{_esc(domain)}</div>
    <div class="hero-verdict">{_esc(verdict)}</div>
    <div class="hero-bench">{benchmark_line}</div>
  </div>
</div>

<div class="chips">{chips_html}</div>

{displacement_html}

<div class="recs">
  <div class="recs-lbl">The pitch — top 3 angles</div>
  {pitch_html}
</div>

<div class="sec-h">Where Yotpo wins</div>
<div class="plays">{plays_html}</div>

<div class="sec-h">Full breakdown</div>
<table class="dt">
  <tr><th>Dimension</th><th>Score</th><th>Finding for {_esc(brand_name)}</th></tr>
  {dim_rows}
</table>

{screenshots_section}

<div class="ft">
  <span>Prepared for {_esc(account_owner or 'Yotpo')} · Generated {_esc(scan_ts[:10])}</span>
  <span>Yotpo Reviews Intelligence</span>
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
        logger.error(
            "Playwright PDF FAILED for scan %s — %s: %s",
            scan_id, type(exc).__name__, exc, exc_info=True,
        )

    html_path = PDF_BASE / f"{scan_id}.html"
    html_path.write_text(html_content, encoding="utf-8")
    logger.warning("Fell back to HTML for scan %s — saved %s", scan_id, html_path)
    return str(html_path)
