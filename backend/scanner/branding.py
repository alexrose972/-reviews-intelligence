"""Branding helpers — Yotpo wordmark + real brand-logo fetching for the brief.

The PDF brief is a sales artifact, so it has to look like Yotpo and carry the
prospect's real logo. This module provides:

* ``yotpo_logo_data_uri()`` — the Yotpo wordmark as a data URI. Uses an authored
  wordmark by default; set ``YOTPO_LOGO_URL`` (or drop a base64 data URI in
  ``YOTPO_LOGO_DATA_URI``) to use the official asset instead.
* ``fetch_brand_logo(domain, homepage_html)`` — the prospect's real logo, tried
  from several free sources in order, returned as a data URI (or "" if none).
"""

import base64
import logging
import os
from typing import Optional
from urllib.parse import urljoin, urlparse

from .utils import make_client, fetch_bytes, clean_domain

log = logging.getLogger("scanner.branding")

# ── Yotpo wordmark ──────────────────────────────────────────────────────────────
# Authored lowercase "yotpo" wordmark in Yotpo near-black. Swap for the official
# asset via env without touching code.
_YOTPO_WORDMARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 132 40" height="28">'
    '<text x="0" y="30" font-family="Helvetica,Arial,sans-serif" font-size="34" '
    'font-weight="800" letter-spacing="-1.5" fill="#0B0B0B">yotpo</text>'
    '<circle cx="124" cy="11" r="4.5" fill="#1F6FFF"/></svg>'
)


def yotpo_logo_data_uri() -> str:
    override = os.environ.get("YOTPO_LOGO_DATA_URI", "").strip()
    if override.startswith("data:"):
        return override
    url = os.environ.get("YOTPO_LOGO_URL", "").strip()
    if url:
        # Best-effort fetch; fall back to the authored wordmark on any failure.
        try:
            import httpx
            with httpx.Client(timeout=10, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                ctype = r.headers.get("content-type", "image/png").split(";")[0]
                b64 = base64.b64encode(r.content).decode()
                return f"data:{ctype};base64,{b64}"
        except Exception as exc:
            log.warning("YOTPO_LOGO_URL fetch failed (%s); using authored wordmark", exc)
    return "data:image/svg+xml;base64," + base64.b64encode(_YOTPO_WORDMARK_SVG.encode()).decode()


# ── Brand logo ──────────────────────────────────────────────────────────────────

def _logo_from_homepage(homepage_html: str, base_url: str) -> Optional[str]:
    """Return the first header/nav <img> whose attributes look like a logo."""
    if not homepage_html:
        return None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(homepage_html, "lxml")
    except Exception:
        return None
    for hdr in soup.find_all(["header", "nav"]):
        for img in hdr.find_all("img"):
            attrs = " ".join([
                (img.get("class") or [""])[0],
                img.get("id", ""), img.get("alt", ""), img.get("src", ""),
            ]).lower()
            src = img.get("src") or img.get("data-src")
            if "logo" in attrs and src:
                return urljoin(base_url, src)
    return None


async def fetch_brand_logo(domain: str, homepage_html: str = "") -> str:
    """Best-effort real brand logo as a data URI. Tries, in order:
        1. a logo <img> on the rendered homepage,
        2. the Clearbit logo API,
        3. Google's favicon service (256px),
    and returns "" if everything fails (the PDF then shows the brand name).
    """
    host = clean_domain(domain) if "://" in domain else domain.replace("www.", "")
    host = host.replace("www.", "")
    base_url = domain if domain.startswith("http") else f"https://{host}"

    candidates = []
    hp = _logo_from_homepage(homepage_html, base_url)
    if hp:
        candidates.append(hp)
    candidates.append(f"https://logo.clearbit.com/{host}?size=256")
    candidates.append(f"https://www.google.com/s2/favicons?domain={host}&sz=256")

    async with make_client() as client:
        for url in candidates:
            raw = await fetch_bytes(client, url)
            if raw and len(raw) > 400:  # skip 1x1 / empty trackers
                ext = "png"
                low = url.lower()
                if low.endswith(".svg") or b"<svg" in raw[:200].lower():
                    ext = "svg+xml"
                elif low.endswith((".jpg", ".jpeg")):
                    ext = "jpeg"
                elif low.endswith(".webp"):
                    ext = "webp"
                return f"data:image/{ext};base64,{base64.b64encode(raw).decode()}"
    return ""
