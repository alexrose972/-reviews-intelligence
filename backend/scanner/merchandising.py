"""
Review-merchandising audit — conversion-focused signals beyond raw review data.

These flag where a brand's reviews are present but NOT merchandised to convert,
which is exactly what Yotpo's Smart Sort / Smart Topics / curated Visual UGC fix:

  * default_sort_recency  — reviews default to "Most Recent" (newest, not most
    persuasive). No conversion-optimized sorting.
  * low_star_up_top       — a 1-2 star review sits on the first screen of reviews.
  * has_ugc_gallery       — a customer photo/video gallery exists (visual UGC).

All detected from the rendered HTML, so it works for both the Scrapfly and
Playwright paths. Returns flags as ready-to-use pitch lines.
"""

import re
from typing import List, Optional

from bs4 import BeautifulSoup

_RECENCY_RE = re.compile(r"sort\s*by[^.]{0,20}?(most recent|newest|recent)", re.I)
_RECENCY_OPTION_RE = re.compile(r"(most recent|newest)", re.I)
_OUT_OF_5_RE = re.compile(r"(\d(?:\.\d)?)\s*(?:out of|/)\s*5", re.I)


def _detect_default_sort(soup: BeautifulSoup) -> Optional[str]:
    """Return 'recency' if reviews default to most-recent/newest sort, else None."""
    # 1) A selected <option> in a sort control
    for sel in soup.select("select option[selected], select option[aria-selected='true']"):
        if _RECENCY_OPTION_RE.search(sel.get_text(" ", strip=True)):
            return "recency"
    # 2) Visible "Sort by: Most Recent" text near a sort control
    for el in soup.select("[class*='sort' i], [class*='Sort' i], label, button"):
        txt = el.get_text(" ", strip=True)
        if txt and _RECENCY_RE.search(txt):
            return "recency"
    # 3) Whole-page fallback (BazaarVoice renders "SORT BY MOST RECENT")
    if _RECENCY_RE.search(soup.get_text(" ", strip=True)[:20000]):
        return "recency"
    return None


def _first_page_low_star(soup: BeautifulSoup, top_n: int = 6) -> bool:
    """True if any of the first `top_n` reviews (DOM order) is rated <= 2 stars."""
    ratings: List[float] = []

    # itemprop ratingValue carried per-review
    for el in soup.select('[itemprop="reviewRating"] [itemprop="ratingValue"], [itemprop="ratingValue"]'):
        v = el.get("content") or el.get_text(strip=True)
        try:
            ratings.append(float(re.findall(r"\d(?:\.\d)?", v)[0]))
        except Exception:
            pass
        if len(ratings) >= top_n:
            break

    # aria-label "Rated 1 out of 5" style (BazaarVoice / many widgets)
    if len(ratings) < top_n:
        for el in soup.select("[aria-label]"):
            m = _OUT_OF_5_RE.search(el.get("aria-label", ""))
            if m:
                try:
                    ratings.append(float(m.group(1)))
                except Exception:
                    pass
            if len(ratings) >= top_n:
                break

    ratings = ratings[:top_n]
    return any(r <= 2 for r in ratings) if ratings else False


def _has_ugc_gallery(soup: BeautifulSoup) -> bool:
    if soup.select_one(
        "[class*='ugc' i], [class*='media-gallery' i], [class*='customer-image' i], "
        "[class*='customer-photo' i], [class*='review-gallery' i], [class*='photo-grid' i]"
    ):
        return True
    txt = soup.get_text(" ", strip=True).lower()
    return ("customer images" in txt) or ("customer photos" in txt) or ("customer images and videos" in txt)


def analyze(pdp_htmls: List[str], reviews_page_html: Optional[str] = None) -> dict:
    """Run the merchandising checks over the best available review HTML."""
    htmls = [h for h in (pdp_htmls or []) if h]
    if reviews_page_html:
        htmls.append(reviews_page_html)
    if not htmls:
        return {"flags": [], "default_sort": None, "low_star_up_top": False, "has_ugc_gallery": False}

    default_sort = None
    low_star = False
    ugc = False
    for h in htmls:
        soup = BeautifulSoup(h, "lxml")
        default_sort = default_sort or _detect_default_sort(soup)
        low_star = low_star or _first_page_low_star(soup)
        ugc = ugc or _has_ugc_gallery(soup)

    flags: List[str] = []
    if default_sort == "recency":
        flags.append(
            "Reviews default to 'Most Recent' sort, so shoppers see the newest "
            "reviews, not the most persuasive. Yotpo Smart Sort surfaces the "
            "reviews most likely to convert first."
        )
    if low_star:
        flags.append(
            "A 1-2 star review is sitting on the first screen of reviews. With no "
            "conversion-aware merchandising, the least flattering reviews lead. "
            "Yotpo surfaces credible, conversion-driving reviews up top."
        )

    return {
        "flags": flags,
        "default_sort": default_sort,
        "low_star_up_top": low_star,
        "has_ugc_gallery": ugc,
    }
