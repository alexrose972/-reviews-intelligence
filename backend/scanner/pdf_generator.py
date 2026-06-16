"""WeasyPrint one-page PDF brief per brand — Yotpo black/white/grey palette."""

import base64
import logging
import os
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

PDF_BASE = Path(os.environ.get("PDF_DIR", "/pdfs"))

YOTPO_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 32" height="24">'
    '<rect width="120" height="32" rx="4" fill="#000000"/>'
    '<text x="10" y="22" font-family="Arial,sans-serif" font-size="16" '
    'font-weight="bold" fill="white">Yotpo</text></svg>'
)
YOTPO_LOGO_B64 = "data:image/svg+xml;base64," + base64.b64encode(YOTPO_LOGO_SVG.encode()).decode()

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
    "vertical_signals":  "Fit and ingredient language in reviews drives category-specific lifts.",
}

# Maps screenshot file stem → (dimension key for finding, friendly page title)
SCREENSHOT_META = {
    "homepage":       ("visibility",        "Homepage"),
    "category_stars": ("stars_on_category", "Category Page"),
    "bestsellers":    ("bestseller_depth",  "Best-Sellers Page"),
}


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

    # ── Dimension rows ────────────────────────────────────────────────────────
    dim_rows = ""
    for i, key in enumerate(DIMENSION_ORDER):
        dim = scores.get(key, {})
        s = dim.get("score", 0)
        m = dim.get("max_score", 0) or 1
        pct = min(s / m * 100, 100)
        bar_color = "#27ae60" if pct >= 70 else ("#e67e22" if pct >= 40 else "#e74c3c")
        label = DIMENSION_LABELS.get(key, key)
        why = WHY_IT_MATTERS.get(key, "")
        finding = dim.get("finding", "")
        row_bg = "#E9E9E9" if i % 2 == 1 else "#FFFFFF"
        dim_rows += f"""
        <tr style="background:{row_bg}">
          <td class="dn"><strong>{label}</strong><span class="why">{why}</span></td>
          <td class="ds">
            <div class="bw"><div class="b" style="width:{pct:.0f}%;background:{bar_color}"></div></div>
            <span class="sn">{s:.0f}/{m}</span>
          </td>
          <td class="df">{finding}</td>
        </tr>"""

    # ── Screenshots with auto-captions ───────────────────────────────────────
    ss_html = ""
    for sp in screenshot_paths[:3]:
        b64 = ""
        try:
            with open(sp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception:
            pass
        if not b64:
            continue
        stem = Path(sp).stem
        dim_key, page_title = SCREENSHOT_META.get(stem, (None, stem.replace("_", " ").title()))
        finding_text = ""
        if dim_key and dim_key in scores:
            finding_text = scores[dim_key].get("finding", "")
        caption = f"{brand_name} {page_title}"
        if finding_text:
            caption += f" — {finding_text}"
        ss_html += f"""
        <div class="ss-item">
          <img class="ss" src="data:image/png;base64,{b64}" />
          <div class="ss-cap">{caption}</div>
        </div>"""

    # ── Recommendations ───────────────────────────────────────────────────────
    pitch_html = ""
    for i, angle in enumerate(pitch_angles[:3], 1):
        pitch_html += f'<div class="pitch"><span class="pn">{i}</span><span class="pt">{angle}</span></div>'

    # ── Brand logo or name ────────────────────────────────────────────────────
    logo_html = (
        f'<img class="bl" src="{brand_logo_b64}" />'
        if brand_logo_b64
        else f'<span class="brand-name-hdr">{brand_name}</span>'
    )

    screenshots_section = f'<div class="ssg">{ss_html}</div>' if ss_html else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
@page {{
  size: letter;
  margin: 0.5in;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 8pt;
  color: #000;
  background: #fff;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}

/* ── Header ── */
.hdr {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 6pt;
  border-bottom: 2pt solid #000;
  margin-bottom: 8pt;
}}
.yl {{ height: 18pt; }}
.hdr-left {{ display: flex; align-items: center; gap: 6pt; }}
.hdr-tag {{ font-size: 6.5pt; color: #555; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }}
.bl {{ max-height: 22pt; max-width: 80pt; object-fit: contain; }}
.brand-name-hdr {{ font-size: 12pt; font-weight: 700; color: #000; }}

/* ── Score / Grade block ── */
.sb {{
  display: flex;
  align-items: center;
  gap: 12pt;
  margin-bottom: 8pt;
  padding: 7pt 10pt;
  background: #E9E9E9;
  border-radius: 4pt;
}}
.gb {{
  width: 58pt;
  height: 58pt;
  border-radius: 50%;
  background: #000;
  color: #fff;
  font-size: 36pt;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 1;
}}
.score-num {{ font-size: 28pt; font-weight: 800; color: #000; line-height: 1; }}
.score-denom {{ font-size: 11pt; color: #888; font-weight: 400; }}
.score-lbl {{ font-size: 6pt; color: #555; text-transform: uppercase; letter-spacing: 0.07em; margin-top: 2pt; }}
.sb-meta {{ flex: 1; padding-left: 4pt; }}
.sb-meta-lbl {{ font-size: 6pt; color: #777; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }}
.sb-meta-val {{ font-size: 9pt; font-weight: 700; color: #000; margin-bottom: 4pt; }}
.sb-meta-val-sm {{ font-size: 7.5pt; font-weight: 400; color: #000; margin-bottom: 0; }}

/* ── Breakdown table ── */
table.dt {{
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 8pt;
}}
table.dt th {{
  text-align: left;
  font-size: 6pt;
  font-weight: 700;
  color: #fff;
  background: #000;
  padding: 3.5pt 6pt;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
table.dt td {{ padding: 3.5pt 6pt; vertical-align: top; }}
.dn {{ width: 28%; }}
.dn strong {{ font-size: 7.5pt; font-weight: 700; color: #000; display: block; }}
.why {{ font-weight: 400; color: #777; font-size: 6pt; display: block; margin-top: 1pt; line-height: 1.35; }}
.ds {{ width: 18%; }}
.bw {{ height: 6pt; background: #ccc; border-radius: 3pt; margin-bottom: 2pt; margin-top: 3pt; }}
.b {{ height: 6pt; border-radius: 3pt; }}
.sn {{ font-size: 6pt; color: #666; }}
.df {{ width: 54%; font-size: 6.5pt; color: #333; line-height: 1.4; }}

/* ── Screenshots ── */
.ssg {{ display: flex; gap: 6pt; margin-bottom: 8pt; }}
.ss-item {{ flex: 1; display: flex; flex-direction: column; }}
.ss {{
  width: 100%;
  height: 52pt;
  object-fit: cover;
  object-position: top;
  border: 0.75pt solid #ddd;
  border-radius: 2pt;
  display: block;
}}
.ss-cap {{ font-size: 5.5pt; color: #555; margin-top: 2pt; line-height: 1.35; }}

/* ── Recommendations ── */
.recs {{ background: #000; border-radius: 3pt; padding: 7pt 10pt; }}
.recs-lbl {{
  font-size: 6.5pt;
  font-weight: 700;
  color: #E9E9E9;
  margin-bottom: 5pt;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}}
.pitch {{ display: flex; gap: 6pt; margin-bottom: 4pt; align-items: flex-start; }}
.pitch:last-child {{ margin-bottom: 0; }}
.pn {{ font-weight: 800; font-size: 10pt; color: #E9E9E9; flex-shrink: 0; line-height: 1.2; width: 11pt; text-align: right; }}
.pt {{ font-size: 7pt; color: #fff; line-height: 1.45; }}

/* ── Footer ── */
.ft {{ margin-top: 5pt; font-size: 5.5pt; color: #aaa; text-align: right; }}
</style></head><body>

<div class="hdr">
  <div class="hdr-left">
    <img class="yl" src="{YOTPO_LOGO_B64}" />
    <span class="hdr-tag">Reviews Intelligence Brief</span>
  </div>
  {logo_html}
</div>

<div class="sb">
  <div class="gb">{grade}</div>
  <div>
    <div class="score-num">{overall_score}<span class="score-denom">/100</span></div>
    <div class="score-lbl">Overall Score</div>
  </div>
  <div class="sb-meta">
    <div class="sb-meta-lbl">Brand</div>
    <div class="sb-meta-val">{brand_name}</div>
    <div class="sb-meta-lbl">Domain</div>
    <div class="sb-meta-val-sm">{domain}</div>
  </div>
</div>

<table class="dt">
  <tr>
    <th>Reviews Audit Breakdown</th>
    <th>Score</th>
    <th>Finding for {brand_name}</th>
  </tr>
  {dim_rows}
</table>

{screenshots_section}

<div class="recs">
  <div class="recs-lbl">Top 3 Recommendations</div>
  {pitch_html}
</div>

<div class="ft">Generated {scan_ts[:10]} · Yotpo Reviews Intelligence</div>
</body></html>"""


def generate(scan_id: str, **kwargs) -> Optional[str]:
    """Render HTML → PDF via WeasyPrint. Falls back to .html if WeasyPrint fails."""
    PDF_BASE.mkdir(parents=True, exist_ok=True)
    html_content = render_html(**kwargs)
    out_path = PDF_BASE / f"{scan_id}.pdf"

    try:
        from weasyprint import HTML as WeasyHTML
        logger.info("WeasyPrint: starting PDF generation for scan %s", scan_id)
        WeasyHTML(string=html_content).write_pdf(str(out_path))
        logger.info("WeasyPrint: PDF written to %s (%d bytes)", out_path, out_path.stat().st_size)
        return str(out_path)
    except Exception as exc:
        logger.error(
            "WeasyPrint FAILED for scan %s — %s: %s",
            scan_id, type(exc).__name__, exc, exc_info=True,
        )

    # Fallback: persist the HTML so the endpoint can retry WeasyPrint on-demand
    html_path = PDF_BASE / f"{scan_id}.html"
    html_path.write_text(html_content, encoding="utf-8")
    logger.warning("Fell back to HTML for scan %s — saved %s", scan_id, html_path)
    return str(html_path)
