"""
Playwright-based page renderer for the Reviews Intelligence scanner.

One PlaywrightAuditor instance per scan — use as an async context manager.
It manages a single Chromium browser + context, navigates pages with full
JS rendering, dismisses popups, takes targeted screenshots, and extracts
structured review data from PDPs.

Module-level ``generate_pdf_bytes()`` is a standalone coroutine that opens
its own short-lived browser to convert HTML → PDF bytes (replaces WeasyPrint).
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

log = logging.getLogger("scanner.browser")

SS_BASE = Path(os.environ.get("SCREENSHOTS_DIR", "/screenshots"))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Browser launch args — anti-detection + sandbox bypass for containers
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-infobars",
]

# JS snippet injected into every page context to mask Playwright fingerprints
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
"""

# Cookie / GDPR accept selectors (ordered by specificity)
_COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "button[id*='accept'][id*='cookie' i]",
    "button[class*='accept-all' i]",
    "button[class*='cookie-accept' i]",
    ".cc-accept",
    "[data-testid='cookie-accept']",
    "button[aria-label*='accept all' i]",
    "button[aria-label*='agree' i]",
    "[class*='cookie'] button[class*='accept' i]",
    "button[class*='consent-accept' i]",
    "[class*='gdpr'] button[class*='accept' i]",
    "button[id*='consent-accept' i]",
    "[aria-label*='close' i][class*='modal' i]",
]

# Review-section element selectors
_REVIEW_SELECTORS = [
    ".yotpo-main-widget",
    ".bv-content-list",
    ".bv-section-summary",
    ".pr-review-display",
    "[class*='okendo-reviews' i]",
    "[class*='stamped-reviews' i]",
    "[class*='powerreviews' i]",
    "#reviews",
    "#product-reviews",
    "[id*='review' i]",
    "[class*='review-list' i]",
    "[class*='reviews-container' i]",
    "[class*='review-widget' i]",
    "[data-widget='reviews']",
    "[class*='judge-reviews' i]",
    "[class*='loox-reviews' i]",
]

# "Load more" button selectors for reviews
_LOAD_MORE_SELECTORS = [
    "button[class*='load-more' i]",
    "button[class*='show-more' i]",
    "a[class*='load-more' i]",
    "[data-testid*='load-more' i]",
    "[class*='see-all-reviews' i]",
    "button[class*='more-reviews' i]",
    "[class*='reviews-load-more' i]",
]

SHOP_PATH_RE = re.compile(
    r"/(collections?|shop|catalog|category|categories|store|all-products|products/?$)",
    re.I,
)

PDP_PATH_RE = re.compile(
    r"/(products?|item|items?|p|pd|detail|buy)/[^/?#\s\"']+",
    re.I,
)

BESTSELLER_KEYWORDS = [
    "best-seller", "bestseller", "best_seller",
    "top-rated", "top_rated", "featured",
]

# ── Bot-block / challenge detection ─────────────────────────────────────────────
# Signatures that mean we hit a WAF / captcha / challenge page instead of the
# real site (Cloudflare, PerimeterX, DataDome, Akamai, Incapsula). If any of
# these match, we must NOT score the page — we never actually reached the site.
_BLOCK_SIGNATURES = [
    "just a moment...",
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-challenge",
    "challenge-platform",
    "_cf_chl_",
    "attention required! | cloudflare",
    "/cdn-cgi/challenge",
    "access denied",
    "access to this page has been denied",
    "you have been blocked",
    "please verify you are a human",
    "verify you are human",
    "px-captcha",
    "perimeterx",
    "datadome",
    "captcha-delivery.com",
    "request unsuccessful. incapsula",
    "are you a robot",
    "unusual traffic from your",
]

_BLOCK_TITLE_HINTS = [
    "just a moment", "access denied", "attention required",
    "blocked", "forbidden", "robot", "captcha", "security check",
]

# Marketing / email-capture modal close selectors (Klaviyo, Privy, Justuno,
# Attentive, etc.). These popups usually fire on a timer AFTER networkidle, so
# they slip past the cookie-banner pass and end up in screenshots.
_MODAL_CLOSE_SELECTORS = [
    ".klaviyo-close-form",
    "[class*='klaviyo'] [aria-label*='close' i]",
    ".privy-close, .privy-popup-close",
    "[class*='privy'] [class*='close' i]",
    "button[class*='justuno' i][class*='close' i]",
    "[id*='attentive'] [aria-label*='close' i]",
    "[class*='popup' i] button[aria-label*='close' i]",
    "[class*='modal' i] button[aria-label*='close' i]",
    "[class*='newsletter' i] [aria-label*='close' i]",
    "[class*='email-signup' i] [class*='close' i]",
    "[class*='overlay' i] button[class*='close' i]",
    "[class*='dialog' i] button[class*='close' i]",
    "button[aria-label='Close dialog']",
    "button[aria-label='Close']",
    "[data-testid*='close' i]",
]


def detect_block(html: Optional[str]) -> Optional[str]:
    """
    Return a short reason string if ``html`` looks like a bot-block / challenge /
    captcha page (or an empty render), else None.

    Used by the engine to avoid scoring a site we never actually reached — a
    blocked scan must produce a 'blocked' status, NOT a fabricated grade.
    """
    if not html:
        return "page_render_failed"

    lowered = html.lower()
    for sig in _BLOCK_SIGNATURES:
        if sig in lowered:
            return "bot_block_detected"

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string or "").strip().lower() if soup.title else ""
        body_text = soup.get_text(" ", strip=True)
    except Exception:
        title = ""
        body_text = lowered

    # Block title on a suspiciously thin page = challenge interstitial
    if title and any(h in title for h in _BLOCK_TITLE_HINTS) and len(body_text) < 1500:
        return "bot_block_detected"

    # Near-empty render — JS never executed or a hard block returned a stub
    if len(body_text) < 200:
        return "empty_render"

    return None

# ── JS snippet for structured review extraction ────────────────────────────────

_REVIEW_EXTRACT_JS = """
() => {
    const data = {
        review_count: null,
        review_texts: [],
        star_ratings: [],
        dates: [],
        has_photos: false,
        has_videos: false,
        has_ai_summary: false,
    };

    // --- Review count ---
    const countSels = [
        '[class*="review-count" i]', '[class*="reviewCount" i]',
        '[itemprop="reviewCount"]', '[class*="total-reviews" i]',
        '[class*="rating-count" i]', '[class*="bv-rating-count" i]',
        '[class*="reviews-total" i]', '[class*="numReviews" i]',
    ];
    for (const sel of countSels) {
        const el = document.querySelector(sel);
        if (el) {
            const m = (el.textContent || '').match(/([\\d,]+)/);
            if (m) { data.review_count = parseInt(m[1].replace(/,/g, '')); break; }
        }
    }
    // Fallback: first "NNN reviews/ratings" in visible text
    if (data.review_count === null) {
        const m = (document.body.innerText || '').match(/(\\d[\\d,]*)\\s*(?:reviews?|ratings?)/i);
        if (m) data.review_count = parseInt(m[1].replace(/,/g, ''));
    }

    // --- Review text snippets ---
    const textSels = [
        '[itemprop="reviewBody"]', '[class*="review-content" i]',
        '[class*="review-text" i]', '[class*="review-body" i]',
        '.bv-content-summary-body-text', '.pr-rd-description-text',
        '[class*="yotpo-review-content" i]', '[class*="review-description" i]',
    ];
    for (const sel of textSels) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
            const text = (el.textContent || '').trim();
            if (text.length > 20) data.review_texts.push(text.slice(0, 300));
            if (data.review_texts.length >= 5) break;
        }
        if (data.review_texts.length >= 5) break;
    }

    // --- Star / rating values ---
    const starSels = [
        '[itemprop="ratingValue"]', '[class*="avg-score" i]',
        '[class*="average-rating" i]', '[class*="star-rating" i]',
    ];
    for (const sel of starSels) {
        const el = document.querySelector(sel);
        if (el) {
            const v = el.getAttribute('content') || (el.textContent || '').trim();
            if (v) { data.star_ratings.push(v.slice(0, 10)); }
        }
    }

    // --- Dates ---
    const dateEls = document.querySelectorAll('[itemprop="datePublished"], [class*="review-date" i], [class*="review-time" i]');
    for (const el of dateEls) {
        const v = el.getAttribute('content') || (el.textContent || '').trim();
        if (v) data.dates.push(v.slice(0, 30));
        if (data.dates.length >= 5) break;
    }

    // --- Media flags ---
    data.has_photos = !!(document.querySelector(
        '[class*="review-photo" i], [class*="review-image" i], [class*="ugc-photo" i], [class*="review-media" i]'
    ));
    data.has_videos = !!(document.querySelector('[class*="review-video" i]'));
    data.has_ai_summary = !!(document.querySelector(
        '[class*="ai-summary" i], [class*="review-summary" i], [class*="ai-insights" i]'
    ));

    return data;
}
"""


def _parse_proxy(proxy_url):
    """Parse a PROXY_URL (e.g. ``http://user:pass@host:port``) into Playwright's
    proxy dict, or None. Credentials are split out, as Playwright requires the
    server and username/password separately. Provider-agnostic.
    """
    if not proxy_url:
        return None
    from urllib.parse import urlparse
    p = urlparse(proxy_url if "://" in proxy_url else "http://" + proxy_url)
    if not p.hostname:
        return None
    server = f"{p.scheme}://{p.hostname}"
    if p.port:
        server += f":{p.port}"
    proxy = {"server": server}
    if p.username:
        proxy["username"] = p.username
    if p.password:
        proxy["password"] = p.password
    return proxy


class PlaywrightAuditor:
    """Manages a single Playwright Chromium browser for a full scan.

    Three drive modes:

    * default (server)   — headless Chromium. Fast, but datacenter IP + headless
      fingerprint gets blocked by WAFs on premium DTC sites.
    * ``real_chrome``    — launches the user's installed Chrome (channel="chrome")
      non-headless. Real browser binary on a residential IP beats most blocks.
    * ``cdp_url``        — attaches to an already-running Chrome over the DevTools
      protocol (the user's actual logged-in profile). Effectively undetectable.

    The last two power the Browser Scan fallback (``chrome_runner.py``) — the same
    extraction code, just executed from a real, non-blocked browser.
    """

    def __init__(self, cdp_url: Optional[str] = None, real_chrome: bool = False,
                 proxy_url: Optional[str] = None):
        self._pw = None
        self._browser = None
        self._ctx = None
        self._cdp_url = cdp_url
        self._real_chrome = real_chrome
        self._proxy = _parse_proxy(proxy_url)  # residential proxy (retry-on-block)
        self._owns_browser = True  # don't close a browser we merely attached to

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()

        if self._cdp_url:
            # Attach to the user's real, already-running Chrome. Reuse its
            # existing context so we inherit the real profile / cookies / IP.
            self._browser = await self._pw.chromium.connect_over_cdp(self._cdp_url)
            self._owns_browser = False
            self._ctx = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
            self._ctx.set_default_timeout(30_000)
            return self

        launch_kwargs = {"args": _LAUNCH_ARGS}
        if self._proxy:
            launch_kwargs["proxy"] = self._proxy
            log.info("Launching Chromium through proxy %s", self._proxy.get("server"))

        if self._real_chrome:
            # Launch the user's installed Chrome (real binary, residential IP),
            # visible so the user can see / solve any challenge that appears.
            self._browser = await self._pw.chromium.launch(
                headless=False, channel="chrome", **launch_kwargs,
            )
        else:
            self._browser = await self._pw.chromium.launch(
                headless=True, **launch_kwargs,
            )

        self._ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
            bypass_csp=True,
            locale="en-US",
            timezone_id="America/New_York",
        )
        # Mask Playwright fingerprints on every page before any JS runs
        await self._ctx.add_init_script(_STEALTH_SCRIPT)
        self._ctx.set_default_timeout(25_000)
        return self

    async def __aexit__(self, *_):
        # When attached over CDP we don't own the browser/context — leave the
        # user's Chrome open; only stop our Playwright driver.
        teardown = [(self._pw, "stop")]
        if self._owns_browser:
            teardown = [
                (self._ctx, "close"),
                (self._browser, "close"),
                (self._pw, "stop"),
            ]
        for obj, method in teardown:
            try:
                if obj:
                    await getattr(obj, method)()
            except Exception:
                pass

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _page(self):
        return await self._ctx.new_page()

    async def _dismiss_popups(self, page):
        """Click cookie/GDPR accept buttons if present."""
        for sel in _COOKIE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                pass
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _dismiss_marketing_modals(self, page):
        """Close email-capture / promo modals (Klaviyo, Privy, Attentive, etc.).

        These commonly appear on a timer after the page settles, so they evade
        the cookie-banner pass and pollute screenshots ('UNLOCK FREE SHIPPING').
        """
        for sel in _MODAL_CLOSE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=400):
                    await btn.click(timeout=1200)
                    await page.wait_for_timeout(250)
            except Exception:
                pass
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _wait_idle(self, page, timeout_ms: int = 7000):
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass

    async def _deep_scroll(self, page):
        """
        Incrementally scroll the full page in 300px steps to trigger lazy loaders,
        wait for review widgets to appear, then try clicking 'Load More'.
        """
        try:
            total_h = await page.evaluate("() => document.body.scrollHeight")
            y = 0
            while y < total_h:
                await page.evaluate(f"() => window.scrollTo(0, {y})")
                await page.wait_for_timeout(120)
                y += 300
                # Re-measure in case new content was injected
                if y > total_h:
                    total_h = await page.evaluate("() => document.body.scrollHeight")
        except Exception as e:
            log.debug("_deep_scroll scroll error: %s", e)

        # Wait for lazy-loaded review widgets to fully render
        await page.wait_for_timeout(4000)

        # Attempt "Load More Reviews" click
        for sel in _LOAD_MORE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=600):
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(2000)
                    log.debug("Clicked load-more: %s", sel)
                    break
            except Exception:
                pass

    async def _scroll_to_reviews(self, page) -> bool:
        """Scroll to review section element if visible. Returns True if found."""
        for sel in _REVIEW_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=700):
                    await el.scroll_into_view_if_needed()
                    return True
            except Exception:
                pass
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
        except Exception:
            pass
        return False

    async def _extract_reviews(self, page) -> dict:
        """Run JS extraction of review data from the current page DOM."""
        try:
            return await page.evaluate(_REVIEW_EXTRACT_JS)
        except Exception as e:
            log.debug("_extract_reviews failed: %s", e)
            return {"review_count": None, "review_texts": [], "star_ratings": [],
                    "dates": [], "has_photos": False, "has_videos": False,
                    "has_ai_summary": False}

    # ── Public methods ──────────────────────────────────────────────────────

    async def get_html(self, url: str, wait_for_reviews: bool = False) -> Optional[str]:
        """Navigate → JS render → optionally scroll to reviews. Returns full DOM HTML."""
        page = await self._page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await self._dismiss_popups(page)
            await self._wait_idle(page, 7000)

            if wait_for_reviews:
                found = await self._scroll_to_reviews(page)
                await page.wait_for_timeout(2500)
                if not found:
                    await self._scroll_to_reviews(page)
                    await page.wait_for_timeout(1500)
            else:
                await page.evaluate("window.scrollBy(0, 600)")
                await page.wait_for_timeout(800)

            return await page.content()
        except Exception as e:
            log.warning("get_html failed [%s]: %s", url, e)
            return None
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def get_pdp_with_reviews(self, url: str) -> Tuple[Optional[str], dict]:
        """
        Navigate to a PDP, do a full deep scroll to trigger review lazy-loaders,
        extract structured review data via JS, and return (html, review_audit).

        review_audit keys: review_count, review_texts, star_ratings, dates,
                           has_photos, has_videos, has_ai_summary
        """
        page = await self._page()
        review_data: dict = {}
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=28_000)
            await self._dismiss_popups(page)
            await self._wait_idle(page, 7000)

            # Deep scroll to load all lazy review widgets
            await self._deep_scroll(page)

            html = await page.content()
            review_data = await self._extract_reviews(page)
            log.info(
                "PDP reviews extracted [%s]: count=%s texts=%d",
                url, review_data.get("review_count"), len(review_data.get("review_texts", [])),
            )
            return html, review_data
        except Exception as e:
            log.warning("get_pdp_with_reviews failed [%s]: %s", url, e)
            return None, review_data
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def find_pdp_urls(self, base_url: str) -> List[str]:
        """
        Discover up to 5 real product-detail-page URLs using three strategies:
          1. Harvest PDP links directly from the homepage
          2. Visit top-priority collection / shop pages found on homepage
          3. Fallback: probe well-known collection paths (/collections/best-sellers, etc.)
        Returns a list of absolute PDP URLs.
        """
        seen: set = set()
        pdp_urls: List[str] = []
        base_host = urlparse(base_url).netloc

        def _same_host(href: str) -> bool:
            p = urlparse(href)
            return p.netloc == base_host or not p.netloc

        def _is_pdp(href: str) -> bool:
            return bool(PDP_PATH_RE.search(href))

        def _is_shop(href: str) -> bool:
            return bool(SHOP_PATH_RE.search(href))

        # ── Strategy 1: harvest from homepage ──────────────────────────────
        page = await self._page()
        all_links: List[dict] = []
        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=20_000)
            await self._dismiss_popups(page)
            await self._wait_idle(page, 5000)
            all_links = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: (a.innerText || a.textContent || '').trim().toLowerCase()
                }))
            """)
            log.info("Homepage [%s]: harvested %d links", base_url, len(all_links))
        except Exception as e:
            log.warning("Homepage load failed [%s]: %s", base_url, e)
        finally:
            try:
                await page.close()
            except Exception:
                pass

        shop_candidates: List[Tuple[int, str]] = []
        for link in all_links:
            href = link.get("href", "")
            text = link.get("text", "")
            if not href or not _same_host(href):
                continue
            if _is_pdp(href) and href not in seen:
                seen.add(href)
                pdp_urls.append(href)
            elif _is_shop(href) and href not in seen:
                seen.add(href)
                priority = 0 if any(
                    kw in href.lower() or kw in text for kw in BESTSELLER_KEYWORDS
                ) else 1
                shop_candidates.append((priority, href))

        shop_candidates.sort(key=lambda x: x[0])

        # ── Strategy 2: visit top collection pages ─────────────────────────
        for _, shop_url in shop_candidates[:4]:
            if len(pdp_urls) >= 5:
                break
            page = await self._page()
            try:
                await page.goto(shop_url, wait_until="domcontentloaded", timeout=18_000)
                await self._dismiss_popups(page)
                await self._wait_idle(page, 5000)
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(600)
                links = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
                )
                for href in links:
                    if _is_pdp(href) and _same_host(href) and href not in seen:
                        seen.add(href)
                        pdp_urls.append(href)
                    if len(pdp_urls) >= 5:
                        break
            except Exception as e:
                log.warning("Collection page failed [%s]: %s", shop_url, e)
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        # ── Strategy 3: probe well-known paths ─────────────────────────────
        if len(pdp_urls) < 3:
            fallback_paths = [
                "/collections/best-sellers", "/collections/bestsellers",
                "/collections/all", "/shop", "/products",
            ]
            for path in fallback_paths:
                if len(pdp_urls) >= 5:
                    break
                fallback_url = urljoin(base_url, path)
                if fallback_url in seen:
                    continue
                page = await self._page()
                try:
                    await page.goto(fallback_url, wait_until="domcontentloaded", timeout=15_000)
                    await self._wait_idle(page, 5000)
                    links = await page.evaluate(
                        "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
                    )
                    for href in links:
                        if _is_pdp(href) and _same_host(href) and href not in seen:
                            seen.add(href)
                            pdp_urls.append(href)
                        if len(pdp_urls) >= 5:
                            break
                    log.info("Fallback path [%s]: found %d PDPs total", path, len(pdp_urls))
                except Exception:
                    pass
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

        log.info("PDP discovery for %s: found %d URLs → %s", base_url, len(pdp_urls), pdp_urls[:5])
        return pdp_urls[:5]

    async def find_category_url(self, base_url: str) -> Optional[str]:
        """Return the URL of the first reachable category/collection page."""
        for path in [
            "/collections/all", "/collections/best-sellers", "/collections",
            "/shop", "/products", "/categories",
        ]:
            url = urljoin(base_url, path)
            page = await self._page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=12_000)
                if resp and resp.ok:
                    return url
            except Exception:
                pass
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
        return None

    async def get_category_html(self, base_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Returns (category_url, rendered_html) or (None, None)."""
        cat_url = await self.find_category_url(base_url)
        if not cat_url:
            return None, None
        html = await self.get_html(cat_url)
        return cat_url, html

    async def take_screenshots(
        self,
        scan_id: str,
        base_url: str,
        pdp_urls: List[str],
    ) -> List[str]:
        """
        Take 3 targeted screenshots and return list of saved file paths:
          1. pdp_reviews       — reviews section on the best PDP
          2. category_stars    — a category/collection page
          3. pdp_above_fold    — a PDP before any scrolling (above the fold)
        """
        safe = re.sub(r"[^\w]", "_", scan_id)
        out_dir = SS_BASE / safe
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: List[str] = []

        async def _shot(label: str, url: str, prep=None) -> Optional[str]:
            page = await self._page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                await self._dismiss_popups(page)
                await self._wait_idle(page, 6000)
                if prep:
                    await prep(page)
                # Late-firing email/promo modals appear after networkidle —
                # clear them right before the shot so they don't get captured.
                await self._dismiss_marketing_modals(page)
                path = out_dir / f"{label}.png"
                await page.screenshot(path=str(path), full_page=False)
                log.info("Screenshot saved: %s", path)
                return str(path)
            except Exception as e:
                log.warning("Screenshot '%s' failed [%s]: %s", label, url, e)
                return None
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        # 1. PDP reviews section
        best_pdp = pdp_urls[0] if pdp_urls else base_url

        async def _prep_reviews(page):
            await self._scroll_to_reviews(page)
            await page.wait_for_timeout(2500)

        p = await _shot("pdp_reviews", best_pdp, _prep_reviews)
        if p:
            saved.append(p)

        # 2. Category page
        cat_url = await self.find_category_url(base_url) or urljoin(base_url, "/collections/all")

        async def _prep_cat(page):
            await page.wait_for_timeout(1200)

        p = await _shot("category_stars", cat_url, _prep_cat)
        if p:
            saved.append(p)

        # 3. PDP above the fold (second PDP if available)
        atf_pdp = pdp_urls[1] if len(pdp_urls) > 1 else best_pdp

        async def _prep_atf(page):
            await page.wait_for_timeout(800)

        p = await _shot("pdp_above_fold", atf_pdp, _prep_atf)
        if p:
            saved.append(p)

        return saved


# ── Standalone PDF helper (no WeasyPrint) ─────────────────────────────────────

async def generate_pdf_bytes(html_content: str) -> bytes:
    """
    Render HTML → PDF bytes using a fresh Playwright Chromium instance.
    CSS ``@page`` rules (size, margins) are respected by the browser engine.
    """
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            pdf_bytes = await page.pdf(
                format="Letter",
                print_background=True,
            )
            return pdf_bytes
        finally:
            await browser.close()
