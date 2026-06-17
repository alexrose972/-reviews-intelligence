"""Shared web-scraping utilities for the scanner."""

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REVIEW_PLATFORMS: Dict[str, List[str]] = {
    "BazaarVoice":      ["bazaarvoice", "bvseo", "bv.js", "bv-scripts"],
    "PowerReviews":     ["powerreviews", "pr-snippet", "pr_api", "powerreviews.com"],
    "Okendo":           ["okendo", "okendowidgets", "cdn.okendo"],
    "Stamped.io":       ["stamped.io", "staticw2.stamped", "stampedhq"],
    "Yotpo":            ["staticw2.yotpo.com", "yotpo.com/staticw2", "yotpoWidgetInstance"],
    "Trustpilot":       ["trustpilot", "widget.trustpilot"],
    "Judge.me":         ["judge.me", "judgeme"],
    "Loox":             ["loox.io", "loox-theme"],
    "Reviews.io":       ["reviews.io", "widget.reviews.io", "reviewsio"],
    "Feefo":            ["feefo.com", "feefowidget"],
    "Shopper Approved": ["shopperapproved.com", "sa.min.js"],
}

HEAVY_PLATFORMS = {"BazaarVoice", "PowerReviews"}

SCORE_WEIGHTS = {
    "llm_crawlability":  20,
    "review_richness":   18,
    "review_recency":    15,
    "visibility":        12,
    "rich_snippets":     10,
    "page_speed":        10,
    "bestseller_depth":   8,
    "stars_on_category":  4,
    "vertical_signals":   3,
}

DIMENSION_LABELS = {
    "llm_crawlability":  "LLM Crawlability",
    "review_richness":   "Review Richness",
    "review_recency":    "Review Recency",
    "visibility":        "Visibility / Discoverability",
    "rich_snippets":     "Rich Snippets",
    "page_speed":        "Page Speed",
    "bestseller_depth":  "Bestseller Depth",
    "stars_on_category": "Stars on Category Pages",
    "vertical_signals":  "Vertical Signals",
}

WHY_IT_MATTERS = {
    "llm_crawlability":  "AI assistants can't recommend products they can't read. Poor crawlability = invisible to ChatGPT, Perplexity, and Gemini.",
    "review_richness":   "Thin reviews don't convert. Shoppers need 40+ words to trust a purchase decision.",
    "review_recency":    "Stale reviews kill conversion. 60% of shoppers won't buy if the most recent review is 3+ months old.",
    "visibility":        "Stars above the fold reduce bounce rate. Hidden reviews are wasted social proof.",
    "rich_snippets":     "AggregateRating schema = star ratings in Google search results. Missing it costs organic CTR.",
    "page_speed":        "Every 100ms of mobile delay costs ~1% in conversions. Heavy review widgets are often the culprit.",
    "bestseller_depth":  "Top products need 50+ reviews to rank in search and convert at full rate.",
    "stars_on_category": "Star ratings on collection pages lift PDP click-through by up to 30%.",
    "vertical_signals":  "Fit, sizing, and ingredient language in reviews drives category-specific conversion lifts.",
}

VERTICAL_SIGNALS_MAP = {
    "footwear":  ["true to size", "runs small", "runs large", "half size", "wide foot",
                  "shoe", "boot", "sneaker", "footwear", "toe box", "arch support"],
    "beauty":    ["skin type", "ingredient", "serum", "moisturizer", "foundation",
                  "concealer", "complexion", "pore", "spf", "retinol", "hyaluronic"],
    "apparel":   ["fits true", "fabric", "inseam", "sleeve", "waist", "hem",
                  "sizing chart", "runs big", "stretchy", "wrinkle"],
    "wellness":  ["supplement", "vitamin", "protein powder", "probiotic", "collagen",
                  "dosage", "energy level", "digestion", "immune"],
    "home":      ["furniture", "room decor", "bedroom", "kitchen", "cushion",
                  "upholstery", "assembly", "sturdy", "living room"],
    "outdoor":   ["hiking", "camping", "waterproof", "trail", "mountain", "backpack",
                  "tent", "wilderness", "weather", "durable"],
    "pet":       ["dog", "cat", "puppy", "kitten", "paw", "kibble", "leash",
                  "crate", "veterinary", "breed"],
}

VERTICAL_PLAYS = {
    "footwear":  "Flag the returns/sizing play: 'true to size' language in reviews = fit guidance Yotpo can surface on PDPs to cut returns.",
    "beauty":    "Flag the personalization play: ingredient and skin-type language = perfect training data for AI product matching.",
    "apparel":   "Flag the sizing play: fit language in reviews drives returns reduction when surfaced at purchase.",
    "wellness":  "Flag the trust play: supplement reviews with dosage and results language = highest-trust category in UGC.",
    "home":      "Flag the assembly/quality play: reviews that mention sturdiness and ease of assembly are top purchase drivers.",
    "outdoor":   "Flag the durability play: weather and trail language = proof points for performance marketing.",
    "pet":       "Flag the pet-parent trust play: breed and vet-adjacent language in reviews drives high-LTV repeat purchases.",
}


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


async def fetch_html(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


async def fetch_bytes(client: httpx.AsyncClient, url: str) -> Optional[bytes]:
    try:
        r = await client.get(url, timeout=15.0)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def domain_to_url(domain: str) -> str:
    d = domain.strip()
    if not d.startswith("http"):
        return f"https://{d}"
    return d


def clean_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url


def detect_platform(html: str) -> Optional[str]:
    lower = html.lower()
    for platform, signals in REVIEW_PLATFORMS.items():
        if any(s in lower for s in signals):
            return platform
    return None


def detect_vertical(text: str) -> Optional[str]:
    lower = text.lower()
    scores = {}
    for vertical, signals in VERTICAL_SIGNALS_MAP.items():
        hit = sum(1 for s in signals if s in lower)
        if hit:
            scores[vertical] = hit
    return max(scores, key=scores.get) if scores else None


def extract_jsonld(html: str) -> List[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            if isinstance(obj, list):
                results.extend(obj)
            else:
                results.append(obj)
        except Exception:
            pass
    return results


def _find_aggregate_rating(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    t = obj.get("@type", "")
    if t == "AggregateRating":
        return True
    if isinstance(t, list) and "AggregateRating" in t:
        return True
    if "aggregateRating" in obj:
        return True
    for v in obj.values():
        if isinstance(v, (dict, list)):
            for item in (v if isinstance(v, list) else [v]):
                if _find_aggregate_rating(item):
                    return True
    return False


def has_aggregate_rating(jsonld: List[dict]) -> bool:
    return any(_find_aggregate_rating(o) for o in jsonld)


def has_review_schema(jsonld: List[dict]) -> bool:
    for o in jsonld:
        t = o.get("@type", "")
        if t in ("Review", "UserReview"):
            return True
        if isinstance(t, list) and any(x in ("Review", "UserReview") for x in t):
            return True
    return False


def has_microdata_rating(soup: BeautifulSoup) -> bool:
    return bool(soup.find(attrs={"itemprop": "aggregateRating"}))


def extract_review_texts(soup: BeautifulSoup) -> List[str]:
    selectors = [
        "[itemprop='reviewBody']", "[class*='review-body']", "[class*='review-text']",
        "[class*='review-content']", "[class*='reviewBody']",
        "[class*='bv-content-summary-body']", "[class*='pr-rd-description']",
        "[class*='yotpo-main']",
    ]
    seen, texts = set(), []
    for sel in selectors:
        for tag in soup.select(sel):
            t = tag.get_text(strip=True)
            if len(t) > 10 and t not in seen:
                seen.add(t)
                texts.append(t)
    return texts


def extract_review_dates(soup: BeautifulSoup) -> List[str]:
    dates = []
    for tag in soup.find_all(attrs={"itemprop": "datePublished"}):
        d = tag.get("content") or tag.get_text(strip=True)
        if d:
            dates.append(d)
    for tag in soup.find_all(class_=re.compile(r"review.?date|date.?review|bv-content-datetime", re.I)):
        d = tag.get_text(strip=True)
        if d:
            dates.append(d)
    return dates


_REL_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def parse_date(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    # Absolute formats
    for fmt in ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d/%m/%Y",
                "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            return datetime.strptime(s[:20], fmt)
        except Exception:
            pass
    # Relative formats (review widgets: Junip/Yotpo/Okendo show "2 hours ago", etc.)
    low = s.lower()
    now = datetime.utcnow()
    if "just now" in low or "moments ago" in low or "today" in low:
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\s*(second|minute|hour)s?\s*ago", low)
    if m:
        return now  # same-day → treat as today (fresh)
    m = re.search(r"(\d+)\s*(day|week|month|year)s?\s*ago", low)
    if m:
        return now - timedelta(days=int(m.group(1)) * _REL_UNIT_DAYS[m.group(2)])
    m = re.search(r"\b(?:a|an|one)\s*(day|week|month|year)\s*ago", low)
    if m:
        return now - timedelta(days=_REL_UNIT_DAYS[m.group(1)])
    return None


async def find_bestseller_urls(client: httpx.AsyncClient, base_url: str) -> List[tuple]:
    candidates = ["/collections/best-sellers", "/collections/bestsellers",
                  "/collections/top-rated", "/best-sellers", "/bestsellers", "/"]
    found = []
    for path in candidates:
        url = urljoin(base_url, path)
        html = await fetch_html(client, url)
        if html and len(html) > 500:
            found.append((url, html))
        if len(found) >= 2:
            break
    return found


async def find_pdp_urls(client: httpx.AsyncClient, base_url: str, page_html: str) -> List[str]:
    soup = BeautifulSoup(page_html, "lxml")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/products?/|/item/|/p/", href, re.I):
            full = urljoin(base_url, href)
            if full not in seen:
                seen.add(full)
                links.append(full)
        if len(links) >= 5:
            break
    return links
