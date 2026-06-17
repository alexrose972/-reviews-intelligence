"""
Visual UGC curation check — does the review gallery lead with *flattering* photos?

Yotpo curates Visual UGC so the best customer media shows first; many sites just
dump photos newest-first, which can put a damaged/off-brand/blurry image on row
one. We can't tell that from HTML, so we send the first few gallery images to
Claude vision and ask it to flag any that would hurt conversion if featured.

Gated: runs only when ANTHROPIC_API_KEY is set, a UGC gallery exists, and
UGC_VISION_CHECK != 'false'. Fully defensive — any failure → no flag, no crash.
"""

import base64
import json
import logging
import os
import re
from typing import List

import anthropic

from .utils import make_client, fetch_bytes

log = logging.getLogger("scanner.vision_ugc")

MODEL = os.environ.get("UGC_VISION_MODEL", "claude-sonnet-4-6")


def _media_type(url: str, raw: bytes) -> str:
    low = url.lower()
    if raw[:8].startswith(b"\x89PNG") or low.endswith(".png"):
        return "image/png"
    if low.endswith(".webp") or raw[:4] == b"RIFF":
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


async def check_ugc_quality(image_urls: List[str], brand: str, max_images: int = 4) -> dict:
    """Return {any_problem, problems:[{index,issue}], checked}. Never raises."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not image_urls:
        return {"any_problem": False, "problems": [], "checked": 0}

    blocks = []
    async with make_client() as client:
        for u in image_urls[:max_images]:
            raw = await fetch_bytes(client, u)
            if not raw or len(raw) < 500:
                continue
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _media_type(u, raw),
                    "data": base64.b64encode(raw).decode(),
                },
            })
    if not blocks:
        return {"any_problem": False, "problems": [], "checked": 0}

    prompt = (
        f"These are the first customer photos shown in {brand}'s on-site review "
        f"gallery, in display order (image 1 = first/top-left). For each, decide "
        f"if it would HURT conversion if featured up front: a damaged or defective "
        f"product, an off-brand or unrelated subject, very blurry / low quality, or "
        f"otherwise unflattering. Be conservative — only flag clear problems. "
        f'Respond ONLY with JSON: {{"problems":[{{"index":<1-based int>,'
        f'"issue":"<short reason>"}}],"any_problem":<bool>}}.'
    )

    try:
        aclient = anthropic.AsyncAnthropic(api_key=key)
        msg = await aclient.messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": blocks + [{"type": "text", "text": prompt}]}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content).strip()
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as exc:
        log.warning("UGC vision check failed: %s", exc)
        return {"any_problem": False, "problems": [], "checked": len(blocks)}

    problems = data.get("problems") or []
    return {
        "any_problem": bool(data.get("any_problem") and problems),
        "problems": problems,
        "checked": len(blocks),
    }
