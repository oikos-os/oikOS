"""Browser MCP tools — web fetch, search, extract, screenshot, navigate, monitor."""

import hashlib
import json
import time
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from core.agency.browser import BrowserManager
        _manager = BrowserManager()
    return _manager


def _validate_url(url: str) -> None:
    """Reject non-HTTP schemes and private/internal IP ranges."""
    from urllib.parse import urlparse
    import ipaddress

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed — only http/https")

    host = parsed.hostname or ""
    # Reject obvious private hostnames
    if host in ("localhost", "::1") or host.endswith(".local"):
        raise ValueError(f"URL blocked: private/internal addresses not allowed ({host})")

    # Reject private IP ranges
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"URL blocked: private/internal addresses not allowed ({host})")
    except ValueError as exc:
        # Not an IP address (it's a hostname) — only re-raise if it's our error
        if "URL blocked" in str(exc) or "not allowed" in str(exc):
            raise


@oikos_tool(
    name="oikos_web_fetch",
    description="Fetch a web page and extract readable content as text",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="browser",
)
async def web_fetch(url: str, max_tokens: int = 6000) -> dict:
    try:
        _validate_url(url)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    mgr = _get_manager()
    try:
        await mgr.rate_limiter.acquire(url)
        return await mgr.fetcher.fetch(url, max_tokens=max_tokens)
    except mgr.rate_limiter.RateLimitedError as exc:
        return {"status": "rate_limited", "retry_after": exc.retry_after}
    except Exception:
        return {"status": "error", "message": "Connection failed"}


@oikos_tool(
    name="oikos_web_search",
    description="Search the web via sovereign SearXNG (self-hosted, no telemetry)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="browser",
)
async def web_search(query: str, count: int = 10, engines: str = "") -> dict:
    mgr = _get_manager()
    return await mgr.searcher.search(query, count=count, engines=engines)


@oikos_tool(
    name="oikos_web_extract",
    description="Extract elements from a web page using CSS or XPath selectors (Playwright)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="browser",
)
async def web_extract(url: str, selector: str, selector_type: str = "css") -> dict:
    try:
        _validate_url(url)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    mgr = _get_manager()
    try:
        await mgr.rate_limiter.acquire(url)
        return await mgr.extractor.extract(url, selector, selector_type)
    except mgr.rate_limiter.RateLimitedError as exc:
        return {"status": "rate_limited", "retry_after": exc.retry_after}
    except RuntimeError as exc:
        if "playwright install" in str(exc).lower():
            return {"status": "error", "message": str(exc)}
        return {"status": "error", "message": "Browser operation failed"}


@oikos_tool(
    name="oikos_web_screenshot",
    description="Take a headless screenshot of a web page (Playwright)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="browser",
)
async def web_screenshot(url: str, full_page: bool = False, width: int = 1280, height: int = 720) -> dict:
    try:
        _validate_url(url)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    mgr = _get_manager()
    try:
        await mgr.rate_limiter.acquire(url)
        page = await mgr.pool.get_page(width=width, height=height)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            staging = Path("staging/screenshots")
            staging.mkdir(parents=True, exist_ok=True)
            filename = hashlib.md5(f"{url}{time.time()}".encode()).hexdigest()[:12] + ".png"
            path = staging / filename
            await page.screenshot(path=str(path), full_page=full_page)
            return {"url": url, "path": str(path), "width": width, "height": height}
        except Exception:
            return {"status": "error", "message": "Screenshot failed"}
        finally:
            await page.close()
    except mgr.rate_limiter.RateLimitedError as exc:
        return {"status": "rate_limited", "retry_after": exc.retry_after}
    except RuntimeError as exc:
        if "playwright install" in str(exc).lower():
            return {"status": "error", "message": str(exc)}
        return {"status": "error", "message": "Screenshot failed"}


@oikos_tool(
    name="oikos_web_navigate",
    description="Execute a sequence of browser actions on a web page (click, fill, wait, scroll, screenshot)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="browser",
)
async def web_navigate(url: str, actions: list[dict] | str = "") -> dict:
    try:
        _validate_url(url)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    mgr = _get_manager()
    if isinstance(actions, str):
        actions = json.loads(actions) if actions else []
    try:
        await mgr.rate_limiter.acquire(url)
        return await mgr.navigator.navigate(url, actions)
    except mgr.rate_limiter.RateLimitedError as exc:
        return {"status": "rate_limited", "retry_after": exc.retry_after}
    except RuntimeError as exc:
        if "playwright install" in str(exc).lower():
            return {"status": "error", "message": str(exc)}
        return {"status": "error", "message": "Navigation failed"}


@oikos_tool(
    name="oikos_web_monitor",
    description="Check if a web page's content has changed since last check",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="browser",
)
async def web_monitor(url: str, selector: str = "", interval_minutes: int = 30) -> dict:
    try:
        _validate_url(url)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    mgr = _get_manager()
    try:
        await mgr.rate_limiter.acquire(url)
        return await mgr.monitor.check(url, selector=selector)
    except mgr.rate_limiter.RateLimitedError as exc:
        return {"status": "rate_limited", "retry_after": exc.retry_after}
