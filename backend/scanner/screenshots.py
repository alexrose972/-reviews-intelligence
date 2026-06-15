"""Playwright screenshot capture."""

import asyncio
import base64
import os
import re
from pathlib import Path
from typing import List
from urllib.parse import urljoin

SS_BASE = Path(os.environ.get("SCREENSHOTS_DIR", "/screenshots"))

try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

HEADERS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def capture(scan_id: str, base_url: str) -> List[str]:
    if not HAS_PLAYWRIGHT:
        return []

    safe = re.sub(r"[^\w]", "_", scan_id)
    out_dir = SS_BASE / safe
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [
        (urljoin(base_url, "/collections/all"), "category_stars"),
        (base_url, "homepage"),
        (urljoin(base_url, "/collections/best-sellers"), "bestsellers"),
    ]

    saved: List[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=HEADERS_UA,
            )
            page = await ctx.new_page()
            for url, label in targets[:3]:
                path = out_dir / f"{label}.png"
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(1.5)
                    await page.screenshot(path=str(path), full_page=False)
                    saved.append(str(path))
                except Exception:
                    pass
            await browser.close()
    except Exception:
        pass

    return saved


def load_as_b64(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""
