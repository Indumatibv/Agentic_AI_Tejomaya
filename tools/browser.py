"""
Browser tool — async Playwright page loader.

Loads a given URL in a headless Chromium browser, waits for network idle,
and returns the full page HTML. Handles timeouts and retries gracefully.
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser

from config import (
    HEADLESS,
    PAGE_TIMEOUT_MS,
    NETWORK_IDLE_TIMEOUT_MS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)


async def load_page(
    url: str,
    *,
    headless: bool = HEADLESS,
    timeout_ms: int = PAGE_TIMEOUT_MS,
    wait_until: str = "networkidle",
    retries: int = MAX_RETRIES,
) -> str:
    """
    Load a URL with Playwright and return the full page HTML.

    Args:
        url: The target URL to load.
        headless: Whether to run in headless mode.
        timeout_ms: Maximum time to wait for page load (ms).
        wait_until: Playwright wait condition ('networkidle', 'load', 'domcontentloaded').
        retries: Number of retry attempts on failure.

    Returns:
        The full HTML content of the rendered page.

    Raises:
        RuntimeError: If the page cannot be loaded after all retries.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        browser: Optional[Browser] = None
        try:
            logger.info(
                "Loading page (attempt %d/%d): %s", attempt, retries, url
            )
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=headless)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page: Page = await context.new_page()
            page.set_default_timeout(timeout_ms)

            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            # Give dynamic JS a moment to render any remaining content
            await page.wait_for_timeout(2000)

            html = await page.content()
            logger.info(
                "Page loaded successfully (%d characters)", len(html)
            )
            return html

        except Exception as exc:
            last_error = exc
            logger.warning(
                "Page load attempt %d failed: %s", attempt, exc
            )
            if attempt < retries:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            try:
                await pw.stop()  # type: ignore[possibly-undefined]
            except Exception:
                pass

    raise RuntimeError(
        f"Failed to load page after {retries} attempts: {last_error}"
    )


async def get_page_and_browser(
    url: str,
    *,
    headless: bool = HEADLESS,
    timeout_ms: int = PAGE_TIMEOUT_MS,
) -> tuple:
    """
    Return a (playwright, browser, page) tuple for advanced use-cases
    (e.g., network inspection, screenshots). Caller is responsible for cleanup.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
    )
    page = await context.new_page()
    page.set_default_timeout(timeout_ms)
    return pw, browser, page
