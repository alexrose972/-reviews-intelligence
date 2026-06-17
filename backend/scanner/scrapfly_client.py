"""
Scrapfly-backed auditor — fetch rendered, un-blocked HTML via the Scrapfly API
instead of driving Playwright.

Scrapfly handles the proxy, JS rendering, and anti-bot (ASP) server-side, so the
app makes a plain HTTPS call and gets finished HTML (+ optional screenshots)
back. No browser, no proxy management, works on Cloudflare/PerimeterX/DataDome.

Activated when ``SCRAPFLY_KEY`` is set; the engine falls back to Playwright
otherwise. Implements the same method surface the engine calls on the auditor:
    find_pdp_urls, get_html, get_pdp_with_reviews, get_category_html, take_screenshots
"""

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .browser import PDP_PATH_RE, SHOP_PATH_RE, BESTSELLER_KEYWORDS, SS_BASE, detect_block

log = logging.getLogger("scanner.scrapfly")

API = "https://api.scrapfly.io/scrape"

# JS run before screenshots: close/remove cookie banners, email-capture modals,
# and full-screen fixed overlays so the shot shows the real page, not a popup.
_POPUP_KILL_JS = (
    '(function(){try{'
    'document.querySelectorAll(\'[aria-label*="close" i],button[class*="close" i],'
    '[class*="popup"] [class*="close" i],[class*="modal"] [class*="close" i]\')'
    '.forEach(function(b){try{b.click()}catch(e){}});'
    '[\'[class*="popup" i]\',\'[class*="modal" i]\',\'[class*="overlay" i]\',\'[class*="newsletter" i]\','
    '\'[class*="klaviyo" i]\',\'[class*="privy" i]\',\'[class*="attentive" i]\',\'[id*="popup" i]\','
    '\'[role="dialog"]\',\'[aria-modal="true"]\',\'dialog\']'
    '.forEach(function(s){document.querySelectorAll(s).forEach(function(e){try{e.remove()}catch(_){}})});'
    'Array.prototype.slice.call(document.querySelectorAll("body *")).forEach(function(e){try{'
    'var st=getComputedStyle(e);if(st.position==="fixed"&&parseInt(st.zIndex||0)>=40){'
    'var r=e.getBoundingClientRect();if(r.width>window.innerWidth*0.55&&r.height>window.innerHeight*0.45)e.remove();}}catch(_){}});'
    'document.documentElement.style.overflow="auto";document.body.style.overflow="auto";'
    '}catch(e){}})();'
)


# Force lazy-loaded images (data-src / loading="lazy") to paint so screenshots
# don't show blank product-image placeholders.
_LAZY_IMG_JS = (
    '(function(){try{document.querySelectorAll("img").forEach(function(im){try{'
    'if(im.getAttribute("loading")==="lazy")im.setAttribute("loading","eager");'
    'var ds=im.getAttribute("data-src")||im.getAttribute("data-original")||im.getAttribute("data-lazy-src");'
    'if(ds&&(!im.getAttribute("src")||im.getAttribute("src").indexOf("data:")===0))im.setAttribute("src",ds);'
    'var dss=im.getAttribute("data-srcset")||im.getAttribute("data-lazy-srcset");'
    'if(dss&&!im.getAttribute("srcset"))im.setAttribute("srcset",dss);'
    'im.style.opacity="1";im.style.visibility="visible";'  # defeat fade-in-on-load
    '}catch(e){}});'
    'document.querySelectorAll("source[data-srcset],source[data-src]").forEach(function(s){try{'
    'var v=s.getAttribute("data-srcset")||s.getAttribute("data-src");if(v)s.setAttribute("srcset",v);}catch(e){}});'
    'document.querySelectorAll("[data-bg],[data-background],[data-bg-src]").forEach(function(el){try{'
    'var b=el.getAttribute("data-bg")||el.getAttribute("data-background")||el.getAttribute("data-bg-src");'
    'if(b)el.style.backgroundImage="url("+b+")";}catch(e){}});}catch(e){}})();'
)


def _screenshot_scenario() -> str:
    """Base64 js_scenario for screenshots: clear popups, force lazy images to
    load, scroll through to trigger any remaining lazy loaders, then settle."""
    steps = [
        {"wait": 4000},
        {"execute": {"script": _POPUP_KILL_JS}},
        {"execute": {"script": _LAZY_IMG_JS}},
        {"scroll": {"x": 0, "y": 9999}},
        {"wait": 3500},
        {"execute": {"script": _LAZY_IMG_JS}},
        {"scroll": {"x": 0, "y": 0}},
        {"wait": 4000},
    ]
    return base64.b64encode(json.dumps(steps).encode()).decode()


def _key() -> str:
    return os.environ.get("SCRAPFLY_KEY", "").strip()


async def scrapfly_scrape(
    client: httpx.AsyncClient,
    url: str,
    *,
    render: bool = True,
    asp: bool = True,
    auto_scroll: bool = False,
    screenshot: bool = False,
    wait_ms: int = 2500,
) -> dict:
    """One Scrapfly call → {html, status, screenshot}. Defensive: never raises."""
    params = {"key": _key(), "url": url, "country": "us"}
    if render:
        params["render_js"] = "true"
    if asp:
        params["asp"] = "true"
    if auto_scroll:
        params["auto_scroll"] = "true"
    if wait_ms:
        params["rendering_wait"] = str(wait_ms)
    if screenshot:
        params["screenshots[main]"] = "fullpage"
        params["auto_scroll"] = "true"  # trigger intersection-observer lazy loaders
        params["rendering_wait"] = "5000"  # let the page settle before capture
        params["js_scenario"] = _screenshot_scenario()  # popups gone + images loaded

    try:
        r = await client.get(API, params=params, timeout=150)
        data = r.json()
    except Exception as exc:
        log.warning("Scrapfly request failed [%s]: %s", url, exc)
        return {"html": "", "status": None, "screenshot": None}

    result = data.get("result", {}) if isinstance(data, dict) else {}
    html = result.get("content") or ""
    status = result.get("status_code")

    shot = None
    if screenshot:
        shots = result.get("screenshots") or {}
        entry = shots.get("main") or (next(iter(shots.values()), None) if shots else None)
        su = (entry or {}).get("url") if isinstance(entry, dict) else None
        if su:
            try:
                sep = "&" if "?" in su else "?"
                sr = await client.get(f"{su}{sep}key={_key()}", timeout=60)
                if sr.status_code == 200 and len(sr.content) > 400:
                    shot = sr.content
            except Exception as exc:
                log.debug("Scrapfly screenshot fetch failed [%s]: %s", url, exc)

    return {"html": html, "status": status, "screenshot": shot}


def extract_reviews_from_html(html: str) -> dict:
    """HTML-parse equivalent of the in-browser review extractor."""
    data = {
        "review_count": None, "review_texts": [], "star_ratings": [], "dates": [],
        "has_photos": False, "has_videos": False, "has_ai_summary": False,
    }
    if not html:
        return data
    soup = BeautifulSoup(html, "lxml")

    count_sels = [
        '[class*="review-count" i]', '[class*="reviewCount" i]', '[itemprop="reviewCount"]',
        '[class*="total-reviews" i]', '[class*="rating-count" i]', '[class*="reviews-total" i]',
    ]
    for sel in count_sels:
        el = soup.select_one(sel)
        if el:
            m = re.search(r"([\d,]+)", el.get_text(" ", strip=True))
            if m:
                data["review_count"] = int(m.group(1).replace(",", ""))
                break
    if data["review_count"] is None:
        m = re.search(r"(\d[\d,]*)\s*(?:reviews?|ratings?)", soup.get_text(" ", strip=True), re.I)
        if m:
            data["review_count"] = int(m.group(1).replace(",", ""))

    text_sels = [
        '[itemprop="reviewBody"]', '[class*="review-content" i]', '[class*="review-text" i]',
        '[class*="review-body" i]', '[class*="yotpo-review-content" i]', '[class*="review-description" i]',
    ]
    _seen_texts = set()
    for sel in text_sels:
        for el in soup.select(sel):
            t = el.get_text(" ", strip=True)
            if len(t) > 20 and t not in _seen_texts:
                _seen_texts.add(t)
                data["review_texts"].append(t[:300])
            if len(data["review_texts"]) >= 5:
                break
        if len(data["review_texts"]) >= 5:
            break

    for sel in ['[itemprop="ratingValue"]', '[class*="average-rating" i]', '[class*="avg-score" i]']:
        el = soup.select_one(sel)
        if el:
            v = el.get("content") or el.get_text(" ", strip=True) or ""
            mm = re.search(r"\b([0-5](?:\.\d)?)\b", v)  # numeric ratings only, no widget text
            if mm:
                data["star_ratings"].append(mm.group(1))
                break

    for el in soup.select('[itemprop="datePublished"], [class*="review-date" i], [class*="review-time" i]'):
        v = el.get("content") or el.get_text(strip=True)
        if v:
            data["dates"].append(v[:30])
        if len(data["dates"]) >= 5:
            break

    data["has_photos"] = bool(soup.select_one(
        '[class*="review-photo" i], [class*="review-image" i], [class*="ugc-photo" i], [class*="review-media" i]'))
    data["has_videos"] = bool(soup.select_one('[class*="review-video" i]'))
    data["has_ai_summary"] = bool(soup.select_one(
        '[class*="ai-summary" i], [class*="review-summary" i], [class*="ai-insights" i]'))
    return data


class ScrapflyAuditor:
    """Drop-in for PlaywrightAuditor, backed by the Scrapfly API."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cat_cache: Optional[Tuple[Optional[str], Optional[str]]] = None  # save API calls

    async def __aenter__(self):
        self._client = httpx.AsyncClient(follow_redirects=True)
        return self

    async def __aexit__(self, *_):
        try:
            if self._client:
                await self._client.aclose()
        except Exception:
            pass

    # ── Public surface (mirrors PlaywrightAuditor) ──────────────────────────

    async def get_html(self, url: str, wait_for_reviews: bool = False) -> Optional[str]:
        res = await scrapfly_scrape(self._client, url, render=True, auto_scroll=wait_for_reviews)
        html = res["html"] or None
        # Scrapfly's anti-bot bypass is probabilistic — if a fetch trips a
        # challenge, one retry (fresh IP) almost always clears it. Avoids a
        # false 'blocked' on a site Scrapfly can actually reach.
        if html and detect_block(html):
            log.info("Scrapfly result for %s looked blocked — retrying once", url)
            res2 = await scrapfly_scrape(self._client, url, render=True,
                                         auto_scroll=wait_for_reviews, wait_ms=5000)
            if res2["html"] and not detect_block(res2["html"]):
                return res2["html"]
            return res2["html"] or html
        return html

    async def get_pdp_with_reviews(self, url: str) -> Tuple[Optional[str], dict]:
        res = await scrapfly_scrape(self._client, url, render=True, auto_scroll=True, wait_ms=4000)
        html = res["html"]
        if not html:
            return None, {}
        review_data = extract_reviews_from_html(html)
        log.info("Scrapfly PDP [%s]: count=%s texts=%d", url,
                 review_data.get("review_count"), len(review_data.get("review_texts", [])))
        return html, review_data

    async def find_pdp_urls(self, base_url: str) -> List[str]:
        host = urlparse(base_url).netloc
        seen: set = set()
        pdps: List[str] = []

        def harvest(html: str):
            if not html:
                return
            soup = BeautifulSoup(html, "lxml")
            shop: List[Tuple[int, str]] = []
            for a in soup.find_all("a", href=True):
                href = urljoin(base_url, a["href"])
                p = urlparse(href)
                if p.netloc and p.netloc != host:
                    continue
                if PDP_PATH_RE.search(href) and href not in seen:
                    seen.add(href)
                    pdps.append(href)
                elif SHOP_PATH_RE.search(href) and href not in seen:
                    seen.add(href)
                    text = (a.get_text() or "").lower()
                    prio = 0 if any(k in href.lower() or k in text for k in BESTSELLER_KEYWORDS) else 1
                    shop.append((prio, href))
            shop.sort(key=lambda x: x[0])
            return shop

        home = await scrapfly_scrape(self._client, base_url, render=True)
        shop = harvest(home["html"]) or []

        for _, shop_url in shop[:2]:
            if len(pdps) >= 5:
                break
            res = await scrapfly_scrape(self._client, shop_url, render=True)
            harvest(res["html"])

        if len(pdps) < 3:
            for path in ["/collections/best-sellers", "/collections/all"]:
                if len(pdps) >= 5:
                    break
                res = await scrapfly_scrape(self._client, urljoin(base_url, path), render=True)
                harvest(res["html"])

        log.info("Scrapfly PDP discovery for %s: %d URLs", base_url, len(pdps))
        return pdps[:5]

    async def find_category_url(self, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        if self._cat_cache is not None:
            return self._cat_cache
        result: Tuple[Optional[str], Optional[str]] = (None, None)
        for path in ["/collections/all", "/collections/best-sellers", "/shop"]:
            url = urljoin(base_url, path)
            res = await scrapfly_scrape(self._client, url, render=True)
            st = res["status"]
            if res["html"] and len(res["html"]) > 2000 and (st is None or 200 <= st < 400):
                result = (url, res["html"])
                break
        self._cat_cache = result
        return result

    async def get_category_html(self, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        return await self.find_category_url(base_url)

    async def take_screenshots(self, scan_id: str, base_url: str, pdp_urls: List[str]) -> List[str]:
        safe = re.sub(r"[^\w]", "_", scan_id)
        out_dir = SS_BASE / safe
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: List[str] = []

        cat_url, _ = await self.find_category_url(base_url)
        targets = [
            ("pdp_reviews", pdp_urls[0] if pdp_urls else base_url, True),
            ("category_stars", cat_url, False),
            ("pdp_above_fold", pdp_urls[1] if len(pdp_urls) > 1 else (pdp_urls[0] if pdp_urls else base_url), False),
        ]
        for label, url, scroll in targets:
            if not url:
                continue
            res = await scrapfly_scrape(self._client, url, render=True, screenshot=True, auto_scroll=scroll)
            if res["screenshot"]:
                path = out_dir / f"{label}.png"
                try:
                    path.write_bytes(res["screenshot"])
                    saved.append(str(path))
                except Exception as exc:
                    log.warning("Scrapfly screenshot save failed [%s]: %s", label, exc)
        return saved
