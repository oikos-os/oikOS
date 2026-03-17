"""Multi-step browser automation via Playwright."""

from __future__ import annotations

from pathlib import Path

from core.agency.browser.playwright_pool import PlaywrightPool


class WebNavigator:
    """Execute sequences of browser actions on a page."""

    def __init__(self, pool: PlaywrightPool):
        self._pool = pool

    async def navigate(self, url: str, actions: list[dict]) -> dict:
        page = await self._pool.get_page()
        results = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            for action in actions:
                result = await self._execute_action(page, action)
                results.append(result)
            return {"url": url, "steps_completed": len(results), "results": results}
        finally:
            await page.close()

    async def _execute_action(self, page, action: dict) -> dict:
        action_type = action.get("type", "")
        try:
            if action_type == "click":
                await page.click(action["selector"], button=action.get("button", "left"))
            elif action_type == "fill":
                await page.fill(action["selector"], action["value"])
            elif action_type == "wait":
                if "selector" in action:
                    await page.wait_for_selector(action["selector"], timeout=action.get("timeout_ms", 5000))
                else:
                    import asyncio
                    await asyncio.sleep(action.get("timeout_ms", 5000) / 1000)
            elif action_type == "scroll":
                direction = action.get("direction", "down")
                try:
                    pixels = int(action.get("pixels", 500))
                except (TypeError, ValueError):
                    pixels = 500
                delta = pixels if direction == "down" else -pixels
                await page.evaluate(f"window.scrollBy(0, {delta})")
            elif action_type == "screenshot":
                staging = Path("staging/screenshots")
                staging.mkdir(parents=True, exist_ok=True)
                name = action.get("name", "nav_screenshot")
                path = staging / f"{name}.png"
                await page.screenshot(path=str(path))
                return {"type": action_type, "status": "ok", "detail": str(path.relative_to(Path.cwd()) if path.is_absolute() else path)}
            else:
                return {"type": action_type, "status": "error", "detail": f"Unknown action type: {action_type}"}
            return {"type": action_type, "status": "ok", "detail": None}
        except Exception as exc:
            return {"type": action_type, "status": "error", "detail": str(exc)}
