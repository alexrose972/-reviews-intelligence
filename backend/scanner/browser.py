"""
Playwright-based page renderer for the Reviews Intelligence scanner.

One PlaywrightAuditor instance per scan — use as an async context manager.
It manages a single Chromium browser + context, navigates pages with full
JS rendering, dismisses cookie banners, and takes targeted screenshots.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

log = logging.getLogger("scanner.browser")

SS_BASE = Path(os.environ.get("SCREENSHOTS_DIR", "/screenshots"))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Common cookie-accept button selectors (ordered by specificity)
COOKIE_SELECTORS = [
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
]

# Selectors for the reviews widget / reviews section
REVIEW_SECTION_SELECTORS = [
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

# Pattern matching shop/collection pages (not PDPs)
SHOP_PATH_RE = re.compile(
    r"/(collections?|shop|catalog|category|categories|store|all-products|products/?$)",
    re.I,
)

# Pattern matching individual product pages
PDP_PATH_RE = re.compile(
    r"/(products?|item|items?|p|pd|detail|buy)/[^/?#\s\"']+",
    re.I,
)

# Keywords that indicate a good collection page to audit
BESTELLER_KEYWORDS = ["best-seller", "bestseller", "best_seller", "top-rated", "top_rated", "featured"]


class PlaywrightAuditor:
    """Manages a single Playwright Chromium browser for a full scan."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._ctx = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=UA,
        )
        self._ctx.set_default_timeout(25_000)
        return self

    async def __aexit__(self, *_):
        for obj, method in [
            (self._ctx, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ]:
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
        for sel in COOKIE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(400)
                    break
            except Exception:
                pass
        # Escape any remaining modal
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _wait_idle(self, page, timeout_ms: int = 7000):
        """Best-effort wait for network idle — never raises."""
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass

    async def _scroll_to_reviews(self, page) -> bool:
        """Try to scroll to the review section. Returns True if found."""
        for sel in REVIEW_SECTION_SELECTORS:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=800):
                    await el.scroll_into_view_if_needed()
                    return True
            except Exception:
                pass
        # Fallback: scroll 60% down
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
        except Exception:
            pass
        return False

    # ── Public methods ──────────────────────────────────────────────────────

    async def get_html(self, url: str, wait_for_reviews: bool = False) -> Optional[str]:
        """
        Navigate to URL, wait for JS render, optionally scroll to reviews.
        Returns full DOM HTML (after JS execution).
        """
        page = await self._page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await self._dismiss_popups(page)
            await self._wait_idle(page, 7000)

            if wait_for_reviews:
                found = await self._scroll_to_reviews(page)
                await page.wait_for_timeout(2500)  # let lazy-loaded reviews appear
                if not found:
                    # Try again — some platforms load the widget after networkidle
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

    async def find_pdp_urls(self, base_url: str) -> List[str]:
        """
        Navigate the site like a human to find real product pages.
        Returns up to 5 PDP URLs.
        """
        seen: set = set()
        pdp_urls: List[str] = []
        base_host = urlparse(base_url).netloc

        def _is_same_host(href: str) -> bool:
            parsed = urlparse(href)
            return parsed.netloc == base_host or not parsed.netloc

        def _is_pdp(href: str) -> bool:
            return bool(PDP_PATH_RE.search(href))

        def _is_shop(href: str) -> bool:
            return bool(SHOP_PATH_RE.search(href))

        # Step 1 — load homepage, harvest all links
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
        except Exception as e:
            log.warning("Homepage load failed [%s]: %s", base_url, e)
        finally:
            try:
                await page.close()
            except Exception:
                pass

        # Partition links found on homepage
        shop_candidates: List[Tuple[int, str]] = []
        for link in all_links:
            href = link.get("href", "")
            text = link.get("text", "")
            if not href or not _is_same_host(href):
                continue
            if _is_pdp(href) and href not in seen:
                seen.add(href)
                pdp_urls.append(href)
            elif _is_shop(href) and href not in seen:
                seen.add(href)
                # Prioritise best-sellers / shop-all pages
                priority = 0 if any(kw in href.lower() or kw in text for kw in BESTELLER_KEYWORDS) else 1
                shop_candidates.append((priority, href))

        shop_candidates.sort(key=lambda x: x[0])

        # Step 2 — visit top shop/collection pages to harvest more PDPs
        for _, shop_url in shop_candidates[:4]:
            if len(pdp_urls) >= 5:
                break
            page = await self._page()
            try:
                await page.goto(shop_url, wait_until="domcontentloaded", timeout=18_000)
                await self._dismiss_popups(page)
                await self._wait_idle(page, 5000)
                # Scroll to load lazy product cards
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(600)
                links = await page.evaluate("""() =>
                    Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
                """)
                for href in links:
                    if _is_pdp(href) and _is_same_host(href) and href not in seen:
                        seen.add(href)
                        pdp_urls.append(href)
                    if len(pdp_urls) >= 5:
                        break
            except Exception as e:
                log.warning("Shop page load failed [%s]: %s", shop_url, e)
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        # Step 3 — Fallback: try well-known collection paths
        if len(pdp_urls) < 3:
            for path in [
                "/collections/best-sellers", "/collections/bestsellers",
                "/collections/all", "/shop", "/products",
            ]:
                if len(pdp_urls) >= 5:
                    break
                fallback_url = urljoin(base_url, path)
                if fallback_url in seen:
                    continue
                page = await self._page()
                try:
                    await page.goto(fallback_url, wait_until="domcontentloaded", timeout=15_000)
                    await self._wait_idle(page, 5000)
                    links = await page.evaluate("""() =>
                        Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
                    """)
                    for href in links:
                        if _is_pdp(href) and _is_same_host(href) and href not in seen:
                            seen.add(href)
                            pdp_urls.append(href)
                        if len(pdp_urls) >= 5:
                            break
                except Exception:
                    pass
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

        log.info("Found %d PDP URLs for %s", len(pdp_urls), base_url)
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
        Take 3 targeted screenshots:
          1. pdp_reviews  — the reviews section on the best PDP
          2. category_stars — a category page (shows/hides stars)
          3. pdp_above_fold — a PDP before any scrolling (above the fold)
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
                path = out_dir / f"{label}.png"
                await page.screenshot(path=str(path), full_page=False)
                log.info("Screenshot saved: %s", path)
                return str(path)
            except Exception as e:
                log.warning("Screenshot '%s' failed: %s", label, e)
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

        # 2. Category page (checking for stars on product cards)
        cat_url = await self.find_category_url(base_url) or urljoin(base_url, "/collections/all")

        async def _prep_cat(page):
            await page.wait_for_timeout(1200)

        p = await _shot("category_stars", cat_url, _prep_cat)
        if p:
            saved.append(p)

        # 3. PDP above the fold (no scrolling)
        atf_pdp = pdp_urls[1] if len(pdp_urls) > 1 else best_pdp

        async def _prep_atf(page):
            await page.wait_for_timeout(800)

        p = await _shot("pdp_above_fold", atf_pdp, _prep_atf)
        if p:
            saved.append(p)

        return saved
