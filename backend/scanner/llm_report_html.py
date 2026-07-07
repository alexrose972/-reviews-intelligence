"""Render the LLM-crawlability report to a standalone HTML file.

Mirrors the YotpoLtd/llm-report-generator layout (tabs: Report / Metrics; company
-> model tabs; per-PDP question tables; metrics tiles + PDP leaderboard) using the
bundled CSS/JS so it looks identical. Consumes the `report` dict from
llm_report.run_llm_report().
"""
from __future__ import annotations

import html as _html
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"


def _asset(name: str) -> str:
    try:
        return (_ASSETS / name).read_text(encoding="utf-8")
    except Exception:
        return ""


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _score_color(score) -> str:
    if score is None:
        return "var(--c-muted)"
    return "var(--c-green)" if score >= 4 else ("var(--c-yellow)" if score >= 3 else "var(--c-red)")


def _found_tag(q: dict) -> str:
    if q.get("found_in_page"):
        tag = '<span class="found-tag found-yes">Found</span>'
    else:
        tag = '<span class="found-tag found-no">Not found</span>'
    if q.get("refusal"):
        tag += '<span class="refusal-tag">Refusal</span>'
    return tag


def _score_cell(score) -> str:
    if score is None:
        return '<span class="score-na">—/5</span>'
    color = _score_color(score)
    width = max(0, min(100, score / 5 * 100))
    return (f'<span style="color:{color};font-weight:700">{score}/5</span>'
            f'<div class="score-bar-bg"><div class="score-bar-fill" '
            f'style="color:{color}" data-bar-width="{width:.0f}"></div></div>')


def _pdp_block(pdp: dict) -> str:
    avg = pdp.get("avg_score")
    avg_html = (f'<span class="pdp-score" style="color:{_score_color(avg)}">{avg}/5</span>'
                if avg is not None else '<span class="pdp-score score-na">—/5</span>')
    rows = ""
    for q in pdp.get("questions", []):
        rows += (
            "<tr>"
            f'<td class="q">{_esc(q.get("question"))}</td>'
            f'<td class="ans">{_esc(q.get("answer"))}</td>'
            f'<td class="explain">{_esc(q.get("explanation"))}</td>'
            f'<td class="num">{_found_tag(q)}</td>'
            f'<td class="num">{_score_cell(q.get("score"))}</td>'
            "</tr>"
        )
    url = _esc(pdp.get("url"))
    return (
        '<details class="pdp-block">'
        '<summary class="pdp-summary">'
        f'<span class="pdp-label">{_esc(pdp.get("label"))}</span>'
        f'{avg_html}'
        f'<span class="pdp-url"><a href="{url}" rel="noopener noreferrer" target="_blank" '
        f'onclick="event.stopPropagation()">{url}</a></span>'
        '</summary>'
        '<table class="pdp-table"><thead><tr>'
        '<th>Question</th><th>LLM answer</th><th class="col-explain">Judge explanation</th>'
        '<th class="num">Found</th><th class="num">Score</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
        '</details>'
    )


_TILE_ORDER = [
    ("pdps", "PDPs"),
    ("questions_judged", "Questions judged"),
    ("found", "Evaluable (Found)"),
    ("found_pct", "Found % (all questions)"),
    ("refusals", "LLM Refusals"),
    ("mean_score", "Mean score (Found only)"),
]


def _tiles(metrics: dict) -> str:
    tiles = ""
    for key, label in _TILE_ORDER:
        val = metrics.get(key, "—")
        if key == "found_pct":
            val = f"{val}%"
        if key == "mean_score":
            val = f"{val}/5"
        tiles += f'<div class="metric-tile"><div class="label">{label}</div><div class="value">{_esc(val)}</div></div>'
    return f'<div class="metrics-grid">{tiles}</div>'


def _leaderboard(rows: list) -> str:
    body = ""
    for i, r in enumerate(rows, 1):
        avg = r.get("avg_score")
        avg_html = (f'<span style="color:{_score_color(avg)};font-weight:700">{avg}/5</span>'
                    if avg is not None else '—/5')
        body += (f'<tr><td class="num">{i}</td><td>{_esc(r.get("label"))}</td>'
                 f'<td class="num">{avg_html}</td>'
                 f'<td><a href="{_esc(r.get("url"))}" target="_blank" rel="noopener noreferrer">'
                 f'{_esc(r.get("url"))}</a></td></tr>')
    return ('<table class="metrics-table pdp-leaderboard"><thead><tr>'
            '<th class="num">#</th><th>Product</th><th class="num">Avg score</th><th>URL</th>'
            f'</tr></thead><tbody>{body}</tbody></table>')


def render(report: dict) -> str:
    brand = _esc(report.get("brand"))
    generated = _esc(report.get("generated_at"))
    companies = report.get("companies", [])

    # ── Report tab: company tabs -> model toggle -> per-PDP blocks ──
    co_tabs, co_panels = "", ""
    for ci, co in enumerate(companies):
        sel = "true" if ci == 0 else "false"
        co_tabs += (f'<button role="tab" id="tab-co-{ci}" aria-selected="{sel}" '
                    f'aria-controls="panel-co-{ci}" data-company-tab="{ci}">{_esc(co["name"])}</button>')
        models = co.get("models", {})
        model_toggle, model_panels = "", ""
        for mi, (mkey, m) in enumerate(models.items()):
            msel = "true" if mi == 0 else "false"
            model_toggle += (f'<button role="tab" data-company-idx="{ci}" data-model-tab="{mkey}" '
                             f'aria-selected="{msel}">{_esc(m["label"])}</button>')
            blocks = "".join(_pdp_block(p) for p in m.get("pdps", []))
            active = "is-active" if mi == 0 else ""
            model_panels += (f'<div class="model-panel {active}" data-model-panel="{mkey}">'
                             f'<div class="metrics-by-model-company">Average score by category</div>'
                             f'{_tiles(m.get("metrics", {}))}'
                             f'<h3 style="margin:1rem 0 .5rem">PDP details</h3>{blocks}</div>')
        panel_active = "is-active" if ci == 0 else ""
        hidden = "" if ci == 0 else "hidden"
        co_panels += (f'<section class="company-panel {panel_active}" id="panel-co-{ci}" '
                      f'data-default-model="{co.get("default_model","")}" {hidden}>'
                      f'<div class="model-toggle">{model_toggle}</div>{model_panels}</section>')

    # ── Metrics tab: overall tiles + leaderboard per company ──
    metrics_body = f'<div class="metrics-section"><h2>Run overview</h2>{_tiles(report.get("overall_metrics", {}))}</div>'
    for co in companies:
        for mkey, m in co.get("models", {}).items():
            metrics_body += (f'<div class="metrics-section"><h2>{_esc(co["name"])} — {_esc(m["label"])} — '
                             f'PDP leaderboard (by average score)</h2>{_leaderboard(m.get("leaderboard", []))}</div>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Crawlability Report — {brand}</title>
<style>{_asset("llm_report.css")}</style></head>
<body><div class="container">
<h1>LLM Crawlability Report</h1>
<div class="subtitle">{brand} · what AI assistants can actually read about your reviews · generated {generated}</div>
<div class="tab-strip" role="tablist">
  <button role="tab" id="tab-main-report" aria-selected="true" aria-controls="panel-main-report" data-main-tab="report">Report</button>
  <button role="tab" id="tab-main-metrics" aria-selected="false" aria-controls="panel-main-metrics" data-main-tab="metrics">Metrics</button>
</div>
<div class="tab-panel is-active" id="panel-main-report" role="tabpanel">
  <div class="tab-strip" role="tablist">{co_tabs}</div>
  {co_panels}
</div>
<div class="tab-panel" id="panel-main-metrics" role="tabpanel" hidden>{metrics_body}</div>
<footer>Prepared by Yotpo · reviews experience audit</footer>
</div>
<script>{_asset("llm_report.js")}</script>
</body></html>"""
