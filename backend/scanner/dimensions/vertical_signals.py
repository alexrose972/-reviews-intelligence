"""Dimension 9: Vertical Signals — 3pts."""

from typing import List, Optional, Tuple
from ..utils import SCORE_WEIGHTS, VERTICAL_SIGNALS_MAP, VERTICAL_PLAYS, detect_vertical

MAX_PTS = SCORE_WEIGHTS["vertical_signals"]


def score(pdp_htmls: List[str], homepage_html: str) -> dict:
    all_text = (homepage_html or "") + "".join(pdp_htmls)
    vertical = detect_vertical(all_text)
    play = VERTICAL_PLAYS.get(vertical, "") if vertical else ""

    if vertical:
        return {
            "score": MAX_PTS,
            "max_score": MAX_PTS,
            "finding": f"Detected vertical: {vertical}. {play}",
            "vertical": vertical,
            "play": play,
        }
    return {
        "score": round(MAX_PTS * 0.3, 1),
        "max_score": MAX_PTS,
        "finding": "Vertical not clearly detected from page content.",
        "vertical": None,
        "play": "",
    }
