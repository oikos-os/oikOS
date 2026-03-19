"""Playwright-based element extractor — CSS and XPath selectors."""

from __future__ import annotations

from core.agency.browser.playwright_pool import PlaywrightPool


class WebExtractor:
    """Extract elements from pages using CSS or XPath selectors."""

    def __init__(self, pool: PlaywrightPool):
        self._pool = pool

    async def extract(self, url: str, selector: str, selector_type: str = "css") -> dict:
        page = await self._pool.get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)

            if selector_type == "xpath":
                selector = f"xpath={selector}"

            elements = await page.query_selector_all(selector)
            matches = []
            for el in elements:
                matches.append({
                    "text": await el.inner_text(),
                    "html": await el.inner_html(),
                    "tag": await el.evaluate("el => el.tagName"),
                })
            return {"url": url, "selector": selector, "matches": matches, "count": len(matches)}
        finally:
            await page.close()
