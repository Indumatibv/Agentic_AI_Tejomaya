"""
Network Inspector tool — intercepts XHR / fetch requests during page load.

Monitors network traffic to detect if the SEBI website exposes a JSON API
endpoint. If found, returns the API URL and parsed response so the
scraper can bypass DOM parsing entirely.
"""

import json
import logging
from typing import Optional

from playwright.async_api import async_playwright, Response

from config import HEADLESS, PAGE_TIMEOUT_MS

logger = logging.getLogger(__name__)


class NetworkInspectionResult:
    """Holds the results of the network inspection."""

    def __init__(self) -> None:
        self.api_url: Optional[str] = None
        self.api_response_body: Optional[list | dict] = None
        self.xhr_urls: list[str] = []
        self.found_json_api: bool = False


async def inspect_network(url: str) -> NetworkInspectionResult:
    """
    Open the target URL while capturing all XHR / fetch responses.

    Looks for JSON responses that contain announcement-like data
    (lists of objects with title-like keys).

    Args:
        url: The page URL to inspect.

    Returns:
        NetworkInspectionResult with any discovered API endpoints.
    """
    result = NetworkInspectionResult()
    captured_responses: list[tuple[str, str]] = []

    async def _on_response(response: Response) -> None:
        """Callback for each network response."""
        try:
            resource_type = response.request.resource_type
            content_type = response.headers.get("content-type", "")

            if resource_type in ("xhr", "fetch") or "application/json" in content_type:
                resp_url = response.url
                result.xhr_urls.append(resp_url)

                if "application/json" in content_type:
                    body = await response.text()
                    captured_responses.append((resp_url, body))
                    logger.debug("Captured JSON response from: %s", resp_url)
        except Exception as exc:
            logger.debug("Error capturing response: %s", exc)

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
        )
        page = await context.new_page()
        page.on("response", _on_response)

        logger.info("Inspecting network traffic for: %s", url)
        await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(3000)  # Wait for any late XHR calls

        # Analyse captured JSON responses for announcement-like data
        for resp_url, body in captured_responses:
            try:
                data = json.loads(body)
                if _looks_like_announcement_api(data):
                    result.api_url = resp_url
                    result.api_response_body = data
                    result.found_json_api = True
                    logger.info("Found announcement API: %s", resp_url)
                    break
            except json.JSONDecodeError:
                continue

        logger.info(
            "Network inspection complete. XHR URLs captured: %d, API found: %s",
            len(result.xhr_urls),
            result.found_json_api,
        )

    except Exception as exc:
        logger.error("Network inspection failed: %s", exc)
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

    return result


def _looks_like_announcement_api(data: list | dict) -> bool:
    """
    Heuristic: check whether the JSON payload looks like a list of
    announcements (i.e., list of dicts with title/date-like keys).
    """
    items: list = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Some APIs wrap results: {"data": [...], ...}
        for key in ("data", "results", "items", "records", "list"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    if not items or not isinstance(items[0], dict):
        return False

    # Check if items have title-like and date-like keys
    sample = items[0]
    keys_lower = {k.lower() for k in sample.keys()}
    has_title = bool(
        keys_lower & {"title", "name", "subject", "heading", "circular_name"}
    )
    has_date = bool(
        keys_lower & {"date", "issue_date", "issuedate", "publish_date", "circular_date"}
    )

    return has_title and has_date and len(items) >= 3
