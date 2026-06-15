"""WeasyPrint one-page PDF brief per brand."""

import base64
import os
import re
from pathlib import Path
from typing import List, Optional, Dict

PDF_BASE = Path(os.environ.get("PDF_DIR", "/pdfs"))

YOTPO_PURPLE = "#3C1053"

YOTPO_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 32" height="24">'
    '<rect width="120" height="32" rx="4" fill="#3C1053"/>'
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


def _grade_color(grade: str) -> str:
    return {"A": "#27ae60", "B": "#e67e22", "C": "#f39c12", "D": "#e74c3c"}.get(grade, "#999")


def _score_bar_color(pct: float) -> str:
    if pct >= 70: return "#27ae60"
    if pct >= 40: return "#e67e22"
    return "#e74c3c"


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
    score_color = _grade_color(grade)

    # Dimension rows
    dim_rows = ""
    for key in DIMENSION_ORDER:
        dim = scores.get(key, {})
        s = dim.get("score", 0)
        m = dim.get("max_score", 0) or 1
        pct = s / m * 100
        bar_color = _score_bar_color(pct)
        label = DIMENSION_LABELS.get(key, key)
        why = WHY_IT_MATTERS.get(key, "")
        finding = dim.get("finding", "")
        dim_rows += f"""
        <tr>
          <td class="dn">{label}<br><span class="why">{why}</span></td>
          <td class="ds">
            <div class="bw"><div class="b" style="width:{pct:.0f}%;background:{bar_color}"></div></div>
            <span class="sn">{s:.0f}/{m}</span>
          </td>
          <td class="df">{finding}</td>
        </tr>"""

    # Pitch angles
    pitch_html = ""
    for i, angle in enumerate(pitch_angles[:3], 1):
        pitch_html += f'<div class="pitch"><span class="pn">{i}</span>{angle}</div>'

    # Screenshots
    ss_html = ""
    for sp in screenshot_paths[:3]:
        b64 = ""
        try:
            with open(sp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception:
            pass
        if b64:
            ss_html += f'<img class="ss" src="data:image/png;base64,{b64}" />'

    # Brand logo or name
    logo_html = (
        f'<img class="bl" src="{brand_logo_b64}" />'
        if brand_logo_b64
        else f'<span class="bn">{brand_name}</span>'
    )

    mismatch_badge = (
        ' <span class="mb">⚠ MISMATCH</span>' if platform_mismatch else ""
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
@page {{size:A4;margin:13mm 13mm 11mm 13mm}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Helvetica Neue',Arial,sans-serif;font-size:7.5px;color:#1a1a2e;background:#fff}}
.hdr{{display:flex;justify-content:space-between;align-items:center;padding-bottom:5px;border-bottom:2px solid {YOTPO_PURPLE};margin-bottom:6px}}
.yl{{height:20px}}.bl{{max-height:28px;max-width:90px;object-fit:contain}}.bn{{font-size:13px;font-weight:700;color:{YOTPO_PURPLE}}}
.meta{{display:flex;gap:10px;font-size:7px;color:#555;margin-bottom:6px;flex-wrap:wrap}}
.mi strong{{color:#1a1a2e}}
.sb{{display:flex;align-items:center;gap:10px;margin-bottom:6px;padding:5px 9px;background:#fafafa;border-radius:5px;border-left:4px solid {score_color}}}
.sc{{font-size:26px;font-weight:800;color:{score_color};line-height:1}}.ss2{{font-size:7px;color:#888}}
.gb{{width:30px;height:30px;border-radius:50%;background:{score_color};color:#fff;font-size:15px;font-weight:800;display:flex;align-items:center;justify-content:center}}
.mb{{background:#e74c3c;color:#fff;font-size:6px;padding:1px 3px;border-radius:2px}}
table.dt{{width:100%;border-collapse:collapse;margin-bottom:6px}}
table.dt th{{text-align:left;font-size:6.5px;font-weight:600;color:#fff;background:{YOTPO_PURPLE};padding:3px 4px}}
table.dt td{{padding:2px 4px;vertical-align:top;border-bottom:1px solid #f0f0f0}}
.dn{{width:30%;font-size:7px;font-weight:600}}.why{{font-weight:400;color:#999;font-size:6px}}
.ds{{width:18%}}.bw{{height:4px;background:#eee;border-radius:2px;margin-bottom:2px}}.b{{height:4px;border-radius:2px}}
.sn{{font-size:6.5px;color:#666}}.df{{width:52%;font-size:6.5px;color:#444}}
.ssg{{display:flex;gap:4px;margin-bottom:6px}}.ss{{max-height:50px;max-width:32%;border:1px solid #ddd;border-radius:2px}}
.ps{{background:{YOTPO_PURPLE};border-radius:5px;padding:6px 9px}}.pl{{font-size:7px;font-weight:700;color:#dbb8ff;margin-bottom:4px;letter-spacing:.05em;text-transform:uppercase}}
.pitch{{display:flex;gap:5px;margin-bottom:3px;font-size:7px;color:#fff;line-height:1.4}}.pn{{font-weight:800;font-size:9px;color:#dbb8ff;flex-shrink:0;line-height:1.2}}
.ft{{margin-top:4px;font-size:6px;color:#bbb;text-align:right}}
</style></head><body>
<div class="hdr">
  <div style="display:flex;align-items:center;gap:8px">
    <img class="yl" src="{YOTPO_LOGO_B64}" />
    <span style="font-size:7px;color:#888">Reviews Intelligence Brief</span>
  </div>
  {logo_html}
</div>
<div class="meta">
  <div class="mi"><strong>Brand:</strong> {brand_name}</div>
  <div class="mi"><strong>Domain:</strong> {domain}</div>
  <div class="mi"><strong>AE:</strong> {account_owner}</div>
  <div class="mi"><strong>Detected platform:</strong> {detected_platform or 'Unknown'}{mismatch_badge}</div>
  <div class="mi"><strong>SF platform:</strong> {sf_platform or 'Not in SF'}</div>
  {f'<div class="mi"><strong>Vertical:</strong> {vertical}</div>' if vertical else ''}
</div>
<div class="sb">
  <div class="sc">{overall_score}<span style="font-size:12px;color:#aaa">/100</span></div>
  <div><div class="ss2">Overall Score</div>
  {f'<div style="font-size:6.5px;color:#c0392b;margin-top:2px">⚠ PageSpeed: {page_speed_score:.0f}/100 mobile — LCP: {page_speed_lcp}</div>' if page_speed_score and page_speed_score < 50 else ''}
  </div>
  <div class="gb">{grade}</div>
</div>
<table class="dt">
  <tr><th>Dimension</th><th>Score</th><th>Finding for {brand_name}</th></tr>
  {dim_rows}
</table>
{f'<div class="ssg">{ss_html}</div>' if ss_html else ''}
<div class="ps">
  <div class="pl">Top 3 Pitch Angles</div>
  {pitch_html}
</div>
<div class="ft">Generated {scan_ts[:10]} · Yotpo Reviews Intelligence</div>
</body></html>"""


def generate(scan_id: str, **kwargs) -> Optional[str]:
    PDF_BASE.mkdir(parents=True, exist_ok=True)
    html_content = render_html(**kwargs)

    out_path = PDF_BASE / f"{scan_id}.pdf"
    try:
        from weasyprint import HTML as WeasyHTML
        WeasyHTML(string=html_content).write_pdf(str(out_path))
        return str(out_path)
    except Exception:
        pass

    # Fallback: save HTML (user can print to PDF in browser)
    html_path = PDF_BASE / f"{scan_id}.html"
    html_path.write_text(html_content, encoding="utf-8")
    return str(html_path)
