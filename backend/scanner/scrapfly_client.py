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
from .utils import extract_jsonld_reviews

log = logging.getLogger("scanner.scrapfly")

API = "https://api.scrapfly.io/scrape"

# Non-product paths to skip when harvesting product URLs from sitemaps.
_NONPRODUCT_PATH = re.compile(
    r"/(collections?|categor(?:y|ies)|pages?|policies|blogs?|account|cart|search|"
    r"about|contact|stores?|gift|faq|help|login|wishlist)(/|$)", re.I)

# JS run before screenshots: close/remove cookie banners, email-capture modals,
# and full-screen fixed overlays so the shot shows the real page, not a popup.
_POPUP_KILL_JS = (
    '(function(){try{'
    # 1. Click obvious close buttons.
    'document.querySelectorAll(\'[aria-label*="close" i],button[class*="close" i],'
    '[class*="popup"] [class*="close" i],[class*="modal"] [class*="close" i],[class*="dismiss" i]\')'
    '.forEach(function(b){try{b.click()}catch(e){}});'
    # 2. Remove known popup/modal/email-capture/game containers by class/role.
    '[\'[class*="popup" i]\',\'[class*="modal" i]\',\'[class*="overlay" i]\',\'[class*="newsletter" i]\','
    '\'[class*="klaviyo" i]\',\'[class*="privy" i]\',\'[class*="attentive" i]\',\'[class*="justuno" i]\','
    '\'[id*="popup" i]\',\'[class*="gamif" i]\',\'[class*="spin" i]\',\'[class*="wheel" i]\','
    '\'[class*="lightbox" i]\',\'[class*="interstitial" i]\',\'[role="dialog"]\',\'[aria-modal="true"]\',\'dialog\']'
    '.forEach(function(s){try{document.querySelectorAll(s).forEach(function(e){try{e.remove()}catch(_){}})}catch(_){}});'
    # 3. Aggressively remove ANY large overlay (fixed/absolute/sticky covering most
    #    of the viewport) plus full-screen iframes — that is what popups/games are.
    'Array.prototype.slice.call(document.querySelectorAll("body *, body iframe")).forEach(function(e){try{'
    'var st=getComputedStyle(e),pos=st.position,z=parseInt(st.zIndex||0)||0,r=e.getBoundingClientRect();'
    'var big=r.width>=window.innerWidth*0.6&&r.height>=window.innerHeight*0.55;'
    'if((pos==="fixed"||pos==="absolute"||pos==="sticky")&&(z>=10||e.tagName==="IFRAME")&&big)e.remove();'
    'else if(z>=1000&&r.width>200&&r.height>150)e.remove();'
    '}catch(_){}});'
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


# JS expression that locates the element proving a given finding, so the
# screenshot focuses on the evidence rather than a generic page shot.
_EVIDENCE_TARGET = {
    "reviews":  "(document.querySelector('[id*=\"yotpo\" i],[class*=\"yotpo\" i],[class*=\"junip\" i],[class*=\"okendo\" i],[class*=\"bv-content\" i],[class*=\"stamped\" i],[class*=\"loox\" i],[class*=\"review-list\" i],[class*=\"reviews-section\" i],[id*=\"reviews\" i]')||Array.prototype.slice.call(document.querySelectorAll('h1,h2,h3')).filter(function(e){return /\\breviews?\\b/i.test(e.textContent||'')}).pop())",
    "sort":     "(Array.prototype.slice.call(document.querySelectorAll('select,button,[class*=\"sort\" i],label,[class*=\"dropdown\" i]')).filter(function(e){return /sort\\s*by|most recent|newest/i.test(e.textContent||'')})[0])",
    "gallery":  "document.querySelector('[class*=\"ugc\" i],[class*=\"media-gallery\" i],[class*=\"customer-image\" i],[class*=\"customer-photo\" i],[class*=\"review-gallery\" i]')",
    "category": "document.querySelector('[class*=\"product\" i][class*=\"grid\" i],[class*=\"collection\" i] [class*=\"product\" i],main')",
    "top":      "document.body",
}


def _evidence_scenario(kind: str) -> str:
    """Base64 js_scenario: kill popups, load images, scroll the evidence element
    into view, then settle — so a viewport screenshot frames the finding."""
    target = _EVIDENCE_TARGET.get(kind, _EVIDENCE_TARGET["top"])
    scroll_js = (
        "(function(){try{var t=" + target + ";"
        "if(t&&t.scrollIntoView){t.scrollIntoView({block:'center',inline:'nearest'});}}catch(e){}})();"
    )
    steps = [
        {"wait": 4000},
        {"execute": {"script": _POPUP_KILL_JS}},
        {"execute": {"script": _LAZY_IMG_JS}},
        {"scroll": {"x": 0, "y": 9999}},          # trigger lazy review widgets
        {"wait": 2500},
        {"execute": {"script": _POPUP_KILL_JS}},   # catch popups that fire on scroll
        {"execute": {"script": _LAZY_IMG_JS}},
        {"execute": {"script": scroll_js}},        # now frame the evidence element
        {"wait": 2000},
    ]
    return base64.urlsafe_b64encode(json.dumps(steps).encode()).decode()


# Scroll to the review widget and dwell so lazy review platforms (BazaarVoice,
# Yotpo, Okendo, Junip, Stamped, PowerReviews) render their schema + content
# into the DOM — they don't load until scrolled into view.
_REVIEW_SCROLL_JS = (
    '(function(){try{var t=document.querySelector('
    '\'#BVRRContainer,[data-bv-show],.bv-content-list,[id*="bazaarvoice" i],[class*="bazaarvoice" i],'
    '[id*="pr-reviewdisplay" i],[class*="pr-review" i],[class*="yotpo" i],[class*="junip" i],'
    '[class*="okendo" i],[class*="stamped" i],[class*="loox" i],[id*="reviews" i],[class*="reviews" i]\');'
    'if(t){t.scrollIntoView({block:"center"});}else{window.scrollTo(0,document.body.scrollHeight*0.7);}'
    '}catch(e){}})();'
)


def _review_render_scenario() -> str:
    """Base64 js_scenario: scroll to the review widget and dwell so lazy review
    platforms render their schema + review content before we read the HTML."""
    steps = [
        {"wait": 3000},
        {"execute": {"script": _REVIEW_SCROLL_JS}},
        {"wait": 7000},
        {"execute": {"script": _REVIEW_SCROLL_JS}},
        {"wait": 4000},
    ]
    return base64.urlsafe_b64encode(json.dumps(steps).encode()).decode()


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
    return base64.urlsafe_b64encode(json.dumps(steps).encode()).decode()


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
    js_scenario: Optional[str] = None,
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
    if js_scenario:
        params["js_scenario"] = js_scenario
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
        '[itemprop="reviewCount"]', '[itemprop="ratingCount"]',  # microdata (BazaarVoice etc.)
        '[class*="review-count" i]', '[class*="reviewCount" i]',
        '[class*="total-reviews" i]', '[class*="rating-count" i]', '[class*="reviews-total" i]',
    ]
    for sel in count_sels:
        el = soup.select_one(sel)
        if el:
            # Microdata puts the value in `content`; widgets put it in the text.
            v = el.get("content") or el.get_text(" ", strip=True)
            m = re.search(r"([\d,]+)", v or "")
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

    # ── JSON-LD reviews (BazaarVoice/Yotpo/Okendo embed real reviews as structured
    # data even when the visible widget loads via JS). Most reliable text source. ──
    jsonld_reviews = extract_jsonld_reviews(soup)
    if jsonld_reviews:
        _seen = set(data["review_texts"])
        for r in jsonld_reviews:
            t = (r.get("text") or "").strip()
            if len(t) > 20 and t not in _seen:
                _seen.add(t)
                data["review_texts"].append(t[:300])
            if r.get("date"):
                data["dates"].append(str(r["date"])[:30])
            rv = r.get("rating")
            if rv is not None:
                data["star_ratings"].append(str(rv))
            if r.get("images"):
                data["has_photos"] = True
            if r.get("videos"):
                data["has_videos"] = True
        data["jsonld_review_count"] = len(jsonld_reviews)
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
        # Scroll to the review widget + dwell so lazy platforms (BazaarVoice etc.)
        # render their schema + review content into the DOM before we read it.
        res = await scrapfly_scrape(self._client, url, render=True, wait_ms=5000,
                                    js_scenario=_review_render_scenario())
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

        # Sitemap fallback — most universal (Shopify always has product sitemaps,
        # and many storefronts list products there even when the homepage doesn't).
        if len(pdps) < 3:
            for u in await self._pdp_urls_from_sitemap(base_url, host):
                if u not in seen:
                    seen.add(u)
                    pdps.append(u)
                if len(pdps) >= 5:
                    break

        log.info("Scrapfly PDP discovery for %s: %d URLs", base_url, len(pdps))
        return pdps[:5]

    async def _fetch_sitemap(self, url: str) -> str:
        """Fetch a sitemap/robots file. Sitemaps are built for crawlers, so a
        cheap direct GET works on most sites; fall back to Scrapfly if blocked."""
        try:
            r = await self._client.get(
                url, timeout=25,
                headers={"User-Agent": "Mozilla/5.0 (compatible; YotpoReviewsBot/1.0)"},
            )
            if r.status_code == 200 and (r.text or "").strip():
                return r.text
        except Exception:
            pass
        res = await scrapfly_scrape(self._client, url, render=False, asp=True)
        return res["html"] or ""

    async def _pdp_urls_from_sitemap(self, base_url: str, host: str) -> List[str]:
        """Find product URLs via robots.txt → sitemap(s). Handles sitemap indexes
        (prioritising product-named children, e.g. Shopify sitemap_products_*)."""
        bare = host.replace("www.", "")
        entries: List[str] = []
        robots = await self._fetch_sitemap(urljoin(base_url, "/robots.txt"))
        for line in robots.splitlines():
            if line.lower().strip().startswith("sitemap:"):
                entries.append(line.split(":", 1)[1].strip())
        entries += [urljoin(base_url, "/sitemap.xml"), urljoin(base_url, "/sitemap_index.xml")]

        queue = list(dict.fromkeys(entries))[:6]
        seen_sm: set = set()
        product_urls: List[str] = []
        fetched = 0
        while queue and fetched < 8 and len(product_urls) < 50:
            sm = queue.pop(0)
            if sm in seen_sm:
                continue
            seen_sm.add(sm)
            fetched += 1
            xml = await self._fetch_sitemap(sm)
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml, re.I)
            if "<sitemapindex" in xml.lower():
                children = [c for c in locs if c not in seen_sm]
                product_children = [c for c in children if re.search(r"product", c, re.I)]
                for c in (product_children or children)[:4]:
                    queue.append(c)
            else:
                is_product_sm = bool(re.search(r"product", sm, re.I))
                for loc in locs:
                    p = urlparse(loc)
                    if p.netloc and not p.netloc.endswith(bare):
                        continue
                    path = p.path or "/"
                    low = loc.lower()
                    # Skip homepage, non-product pages, and static assets.
                    if path in ("", "/") or _NONPRODUCT_PATH.search(path):
                        continue
                    if any(a in low for a in (".css", ".js", ".json", ".xml", "/static",
                                              "demandware.static", "/cdn", "/media/")):
                        continue
                    # Product URL — pattern-agnostic so it works across platforms:
                    #   • product-named sitemap (Shopify sitemap_products_*)
                    #   • /products/, /p/, /item/ … (PDP_PATH_RE)
                    #   • SFCC / Magento .html PDPs (/US/en/name/SKU.html)
                    #   • a SKU-like code in the last path segment
                    looks_product = (
                        is_product_sm
                        or PDP_PATH_RE.search(loc)
                        or path.endswith(".html")
                        or re.search(r"/[a-z0-9]*\d{3,}[a-z0-9]*/?$", path, re.I)
                    )
                    if looks_product:
                        product_urls.append(loc)
                    if len(product_urls) >= 50:
                        break
        # Spread out the picks rather than taking 5 adjacent SKUs.
        uniq = list(dict.fromkeys(product_urls))
        if len(uniq) > 5:
            step = max(1, len(uniq) // 5)
            uniq = uniq[::step][:5]
        log.info("Sitemap discovery for %s: %d product URLs", base_url, len(uniq))
        return uniq[:5]

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

    async def capture_evidence(self, scan_id: str, shots: List[dict]) -> List[dict]:
        """Evidence screenshots: a clean (popup-free, images-loaded) capture of the
        page behind each negative finding. `shots`: [{label, url, caption}].
        Returns [{label, path, caption}] for the ones that captured."""
        safe = re.sub(r"[^\w]", "_", scan_id)
        out_dir = SS_BASE / safe
        out_dir.mkdir(parents=True, exist_ok=True)
        out: List[dict] = []
        for shot in shots:
            url = shot.get("url")
            if not url:
                continue
            # Reuse the proven full-page capture (popup removal + lazy images).
            res = await scrapfly_scrape(self._client, url, render=True, screenshot=True)
            if res["screenshot"]:
                try:
                    path = out_dir / f"{shot['label']}.png"
                    path.write_bytes(res["screenshot"])
                    out.append({"label": shot["label"], "path": str(path),
                                "caption": shot.get("caption", "")})
                except Exception as exc:
                    log.warning("Evidence shot save failed [%s]: %s", shot.get("label"), exc)
        return out
