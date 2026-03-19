"""On-demand headless Chromium lifecycle manager."""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright, Browser, Page


class PlaywrightPool:
    """Manages a single shared browser instance with idle timeout."""

    def __init__(self, idle_timeout: float = 60.0):
        self._idle_timeout = idle_timeout
        self._browser: Browser | None = None
        self._playwright_context = None
        self._pw_instance = None
        self._last_used: float = 0
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None

    async def get_page(self, width: int = 1280, height: int = 720) -> Page:
        """Get a new page from the shared browser. Launches browser if needed."""
        import time
        async with self._lock:
            if self._browser is None:
                await self._launch()
            self._last_used = time.monotonic()
            page = await self._browser.new_page(viewport={"width": width, "height": height})

        self._schedule_idle_check()
        return page

    async def _launch(self) -> None:
        try:
            self._playwright_context = async_playwright()
            self._pw_instance = await self._playwright_context.__aenter__()
            launch_kwargs = {"headless": True}
            if sys.platform == "win32":
                launch_kwargs["args"] = ["--disable-gpu"]
            self._browser = await self._pw_instance.chromium.launch(**launch_kwargs)
        except Exception as exc:
            self._browser = None
            if "Executable doesn't exist" in str(exc) or "executable" in str(exc).lower():
                raise RuntimeError(
                    "Playwright Chromium not installed. Run: playwright install chromium"
                ) from exc
            raise

    def _schedule_idle_check(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        try:
            loop = asyncio.get_running_loop()
            self._idle_task = loop.create_task(self._idle_check())
        except RuntimeError:
            pass

    async def _idle_check(self) -> None:
        import time
        await asyncio.sleep(self._idle_timeout)
        if time.monotonic() - self._last_used >= self._idle_timeout:
            await self.close()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright_context:
            await self._playwright_context.__aexit__(None, None, None)
            self._playwright_context = None
            self._pw_instance = None
