"""
Vision fallback for review extraction.

Some review widgets (BazaarVoice, PowerReviews, Okendo, Yotpo, Stamped) load via
delayed JS / iframes, so neither DOM selectors nor JSON-LD always expose the
reviews. A screenshot captures whatever actually rendered. We send it to Claude
vision and ask, in strict JSON, what the review section looks like.

This is a FALLBACK: it fires only when DOM + JSON-LD extraction found no review
text AND a review platform was detected on the page (so we're spending a vision
call on a genuine gap, not on every PDP). Fully defensive — any failure returns
None and the caller keeps the structured-data result.

Important scoring rule: we always use the STATED review count the page displays,
never a count of how many cards happen to be visible on screen.
"""

import base64
import io
import json
import logging
import os
import re
from typing import Optional

import anthropic

log = logging.getLogger("scanner.vision_reviews")

MODEL = os.environ.get("REVIEW_VISION_MODEL", "claude-sonnet-4-6")

_PROMPT = """This is a screenshot of a product page's review section for {brand}. Look only at what is actually rendered. Answer each question, then respond with ONLY a JSON object (no prose).

- Are reviews visible? (yes/no)
- What is the STATED review/rating count the page itself displays (e.g. "847 reviews")? Do NOT count the reviews visible on screen — only report the number the page states. Null if not shown.
- Is there a visible sort control (dropdown/tabs)? What is the selected label — "Most Recent", "Most Helpful", "Smart Sort", "Highest Rating", etc.? Use "not visible" if there's no sort control.
- Are the reviews detailed or thin? Quote one example if visible.
- Are stars visible? Are photos/video visible? Is any date text visible?
- Does the section look fully loaded, or broken/empty?

Respond with ONLY this JSON:
{{"reviews_visible": <bool>, "stated_review_count": <int or null>, "sort_order_visible": <bool>, "sort_order_label": "<string or 'not visible'>", "review_quality": "<'detailed' | 'thin' | 'none'>", "example_text": "<string or ''>", "stars_visible": <bool>, "photos_or_video_visible": <bool>, "date_text_found": <bool>, "appears_broken_or_empty": <bool>}}"""


def _media_type(raw: bytes) -> str:
    if raw[:8].startswith(b"\x89PNG"):
        return "image/png"
    if raw[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"


def _prep_review_image(raw: bytes) -> tuple:
    """Crop a full-page capture to the review band and downscale to a readable size.

    Claude resizes an image's long edge to ~1568px; a 1920x7600 full-page shot
    therefore shrinks the width to ~400px and the review text becomes illegible.
    Reviews sit in the lower part of a PDP, so for very tall pages we crop the
    lower band (capped to ~1.5x width so the resize keeps width readable) and
    downscale. Returns (jpeg_bytes, media_type). Falls back to the raw bytes if
    Pillow isn't available or anything fails.
    """
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = im.size
        if h > 2 * w:  # very tall page → crop the lower review band
            top = int(h * 0.42)
            band = min(h - top, int(w * 1.5))
            im = im.crop((0, top, w, top + band))
        cw, ch = im.size
        longest = max(cw, ch)
        if longest > 1540:
            f = 1540 / longest
            im = im.resize((max(1, int(cw * f)), max(1, int(ch * f))))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
        return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        log.warning("Review image prep failed, sending raw: %s", exc)
        return raw, _media_type(raw)


def _parse_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.search(r"([\d,]+)", v)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


async def analyze_review_screenshot(image_bytes: bytes, brand: str) -> Optional[dict]:
    """Return the strict-JSON vision read of a review screenshot, or None on failure."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not image_bytes or len(image_bytes) < 800:
        return None
    try:
        img_bytes, media_type = _prep_review_image(image_bytes)
        aclient = anthropic.AsyncAnthropic(api_key=key)
        msg = await aclient.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type,
                    "data": base64.b64encode(img_bytes).decode(),
                }},
                {"type": "text", "text": _PROMPT.format(brand=brand or "this brand")},
            ]}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content).strip()
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        # Normalize the count to an int (never a visual tally).
        data["stated_review_count"] = _parse_int(data.get("stated_review_count"))
        return data
    except Exception as exc:
        log.warning("Review vision analysis failed: %s", exc)
        return None


def apply_vision_review(all_scores: dict, vision: dict, brand: str) -> dict:
    """Merge a vision-fallback read into the scores. Returns a summary for logging.

    Only called when DOM + JSON-LD found no review text, so vision never overrides
    real structured data ("DOM wins"). Always uses the STATED count, never a tally
    of visible cards. Touched dimensions are tagged data_source='vision_fallback'.
    """
    notes = []
    stated = vision.get("stated_review_count")
    visible = bool(vision.get("reviews_visible"))
    broken = bool(vision.get("appears_broken_or_empty"))
    quality = (vision.get("review_quality") or "").lower()
    rr = all_scores.get("review_richness")
    cnt = f"{stated:,}" if isinstance(stated, int) else None

    if visible and not broken and quality in ("detailed", "thin"):
        # Reviews render visually but aren't in the HTML/JSON-LD — score from vision.
        max_pts = (rr or {}).get("max_score", 18)
        if quality == "detailed" and (stated or 0) >= 20:
            pts = round(max_pts * 0.55, 1)
        elif quality == "detailed":
            pts = round(max_pts * 0.40, 1)
        else:  # thin
            pts = round(max_pts * 0.20, 1)
        finding = (
            f"Visual inspection found {cnt + ' reviews' if cnt else 'reviews'} rendered "
            f"on the page ({'detailed' if quality == 'detailed' else 'mostly short/thin'}), "
            f"but they aren't embedded in the page's HTML — so AI assistants and search "
            f"engines can't read them."
        )
        if rr is not None:
            rr.update({"score": pts, "finding": finding,
                       "measured": True, "data_source": "vision_fallback"})
        notes.append(f"richness_from_vision:{quality}:{pts}")
    elif visible or stated:
        # Reviews are stated to exist but didn't render for an automated visitor and
        # aren't in the HTML — the strongest version of the crawlability finding.
        crawl = all_scores.get("llm_crawlability")
        if crawl is not None:
            extra = (f"Visual inspection: the page states {cnt} reviews" if cnt
                     else "Visual inspection: reviews are present") + \
                    (", but they load via a widget and aren't in the page HTML — "
                     "AI assistants and search engines can't read them.")
            crawl["finding"] = ((crawl.get("finding", "") + " ").strip() + " " + extra).strip()
            crawl["data_source"] = "vision_fallback"
        notes.append("crawlability_reinforced")

    # Sort order is a UI-only signal — fold into richness/visibility as a note.
    label = vision.get("sort_order_label")
    if vision.get("sort_order_visible") and label and label.lower() != "not visible":
        sort_note = f" Reviews default to '{label}' sort" + (
            " — shoppers see the newest reviews first, not the most helpful."
            if "recent" in label.lower() else ".")
        tgt = rr if (rr and rr.get("measured", True)) else all_scores.get("visibility")
        if tgt and tgt.get("measured", True):
            tgt["finding"] = (tgt.get("finding", "") + sort_note).strip()
        notes.append(f"sort:{label}")

    return {"notes": notes, "stated_count": stated, "reviews_visible": visible,
            "appears_broken_or_empty": broken, "review_quality": quality}
