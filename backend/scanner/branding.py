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
# The official Yotpo wordmark (the "yotpo" lockup in Yotpo blue #0042E4), taken
# verbatim from yotpo.com/wp-content/themes/yotpo/images/general/yotpo-logo-v3.svg.
# Override via env (YOTPO_LOGO_URL / YOTPO_LOGO_DATA_URI) if the brand mark changes.
_YOTPO_WORDMARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="113" height="32" viewBox="0 0 113 32">'
    '<g fill="none" fill-rule="evenodd"><g fill="#0042E4"><g><g>'
    '<path d="M6.68 4.38l4.122 11.365L15.121 4.38h6.131L10.768 30.698H4.704l3.101-8.155L.352 4.38H6.68z'
    'm64.757-.403c5.536 0 9.573 4.296 9.573 10.176S76.973 24.33 71.437 24.33c-2.043 0-3.763-.541-5.076-1.584'
    'l-.085-.069-.073-.06v8.075h-5.908V4.38h5.224v1.967l.03-.034c1.287-1.468 3.234-2.28 5.64-2.333l.127-.002h.121z'
    'm-39.424 0c6.096 0 10.417 4.212 10.417 10.176 0 5.939-4.335 10.177-10.417 10.177-6.116 0-10.458-4.232-10.458-10.177 0-5.97 4.327-10.176 10.458-10.176z'
    'M52.273.05v4.33h4.86v5.103h-4.86v7.044c0 1.576.765 2.443 2.159 2.496l.068.001.069.001c.945 0 1.661-.248 2.302-.864'
    'l.06-.059.159-.163h.044v5.629l-.181.087c-.973.465-1.572.675-3.23.675-4.684 0-7.256-2.55-7.356-7.312l-.002-.145v-.145'
    'l-.001-7.245h-2.138V4.38h2.299V.05h5.747z'
    'M93.92 3.977c6.096 0 10.417 4.212 10.417 10.176 0 5.939-4.335 10.177-10.417 10.177-6.116 0-10.458-4.232-10.458-10.177 0-5.97 4.328-10.176 10.458-10.176z'
    'm15.233 13.878c1.788 0 3.237 1.45 3.237 3.237 0 1.788-1.45 3.238-3.237 3.238-1.788 0-3.237-1.45-3.237-3.238s1.45-3.237 3.237-3.237z'
    'M70.552 9.282c-2.662 0-4.47 1.97-4.47 4.871 0 2.902 1.808 4.872 4.47 4.872 2.696 0 4.51-1.964 4.51-4.872 0-2.907-1.814-4.871-4.51-4.871z'
    'm-38.54 0c-2.67 0-4.509 1.98-4.509 4.871 0 2.892 1.839 4.872 4.51 4.872 2.636 0 4.47-1.986 4.47-4.872 0-2.885-1.834-4.871-4.47-4.871z'
    'm61.908 0c-2.67 0-4.51 1.98-4.51 4.871 0 2.892 1.84 4.872 4.51 4.872 2.636 0 4.47-1.986 4.47-4.872 0-2.885-1.834-4.871-4.47-4.871z" '
    'transform="translate(-40 -20) translate(-3 -2) translate(43 22.5)"/>'
    '</g></g></g></g></svg>'
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
