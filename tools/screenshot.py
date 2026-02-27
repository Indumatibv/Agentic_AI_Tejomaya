"""
Screenshot tool — captures full-page screenshots for Vision LLM fallback.

Used when DOM-based semantic extraction fails. The screenshot is encoded
as base64 and sent to a Vision-capable LLM for extraction.
"""

import base64
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from config import HEADLESS, PAGE_TIMEOUT_MS, OUTPUT_DIR

logger = logging.getLogger(__name__)


async def capture_screenshot(
    url: str,
    *,
    save_path: Optional[Path] = None,
    full_page: bool = True,
) -> str:
    """
    Capture a screenshot of the given URL and return it as a base64-encoded string.

    Args:
        url: The URL to screenshot.
        save_path: Optional file path to also save the screenshot to disk.
        full_page: Whether to capture the full scrollable page.

    Returns:
        Base64-encoded PNG screenshot string.
    """
    pw = None
    browser = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        logger.info("Capturing screenshot of: %s", url)
        await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(2000)

        screenshot_bytes: bytes = await page.screenshot(full_page=full_page)

        # Optionally save to disk
        if save_path is None:
            save_path = OUTPUT_DIR / "screenshot.png"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(screenshot_bytes)
        logger.info("Screenshot saved to: %s", save_path)

        # Encode as base64 for Vision LLM
        b64_string = base64.b64encode(screenshot_bytes).decode("utf-8")
        logger.info(
            "Screenshot encoded (base64 length: %d)", len(b64_string)
        )
        return b64_string

    except Exception as exc:
        logger.error("Screenshot capture failed: %s", exc)
        raise RuntimeError(f"Failed to capture screenshot: {exc}") from exc
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass
