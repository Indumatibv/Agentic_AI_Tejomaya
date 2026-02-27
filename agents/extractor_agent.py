"""
Extractor Agent — LLM-powered semantic extraction of SEBI announcements.

Three strategies in priority order:
1. API strategy — if network inspector found a JSON API, parse directly.
2. DOM + LLM strategy — send cleaned HTML to LLM for semantic extraction.
3. Vision LLM fallback — send screenshot to a Vision model.

Uses Azure OpenAI endpoints.
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from models.schema import Announcement, AnnouncementList, ExtractionResult
from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_API_VERSION,
    LLM_DEPLOYMENT,
    VISION_DEPLOYMENT,
    LLM_TEMPERATURE,
    MAX_HTML_CHARS_FOR_LLM,
)

logger = logging.getLogger(__name__)

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a data extraction specialist. Your job is to identify
and extract structured data from web page content.

IMPORTANT RULES:
- Do NOT rely on CSS class names or specific HTML attributes.
- Instead, look for SEMANTIC PATTERNS — repeating blocks of content that
  represent individual announcements or circulars.
- Each announcement typically has a TITLE (a descriptive text or link label)
  and an ISSUE DATE (a date in various formats like DD Mon YYYY, YYYY-MM-DD, etc.).
- Extract ALL announcements visible on the page.
- Dates should be normalised to YYYY-MM-DD format.
- Assign a confidence score between 0.0 and 1.0 to each extraction.
- If you are uncertain about any item, lower its confidence score but still include it.
"""

DOM_EXTRACTION_PROMPT = """Analyse the following HTML content from the SEBI website.
Identify all repeating announcement / circular entries on the page.

For each entry, extract:
1. title — the full announcement title text
2. issue_date — the date it was issued (normalise to YYYY-MM-DD)
3. confidence — your confidence in the accuracy of the extraction (0.0 – 1.0)

The HTML content:
---
{html}
---

Return your response as structured JSON matching the schema provided."""

VISION_EXTRACTION_PROMPT = """This is a screenshot of the SEBI (Securities and
Exchange Board of India) circulars listing page.

Identify all visible announcement entries. For each, extract:
1. title — the full announcement title
2. issue_date — the issue date (normalise to YYYY-MM-DD)
3. confidence — your confidence in this extraction (0.0 – 1.0)

Return structured JSON matching the schema provided."""

REFINED_PROMPT = """The previous extraction attempt produced invalid or incomplete
results. Please try again with extra care.

Common issues to watch for:
- Dates embedded in URLs (e.g., /jan-2026/ means January 2026)
- Dates appearing as separate text near the title
- Titles that span multiple lines
- Dates in Indian format (DD/MM/YYYY or DD-Mon-YYYY)

The HTML content:
---
{html}
---

Return your response as structured JSON matching the schema provided."""


# ── Helper ────────────────────────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    """
    Aggressively clean HTML to extract only the announcement listing content.

    Strategy:
    1. Try to extract just the announcements table (table#sample_1)
    2. If not found, fall back to stripping scripts/styles and truncating
    """
    # Strategy 1: Extract just the announcements table
    # The SEBI page wraps all circulars in <table id="sample_1">
    table_match = re.search(
        r'<table[^>]*id=["\']sample_1["\'][^>]*>.*?</table>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if table_match:
        html = table_match.group()
        logger.info("Extracted announcements table (%d chars)", len(html))
    else:
        # Strategy 2: Try to find any table with announcement-like content
        # Look for tables containing <a class="points"
        table_match = re.search(
            r'<table[^>]*>(?:(?!<table).)*?class=["\']points["\'].*?</table>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if table_match:
            html = table_match.group()
            logger.info("Extracted content table via link pattern (%d chars)", len(html))

    # Remove script and style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    # Remove image tags (noise)
    html = re.sub(r"<img[^>]*>", "", html, flags=re.IGNORECASE)
    # Remove excessive whitespace
    html = re.sub(r"\s{2,}", " ", html)

    # Truncate if still too large
    if len(html) > MAX_HTML_CHARS_FOR_LLM:
        logger.warning(
            "HTML truncated from %d to %d chars for LLM",
            len(html),
            MAX_HTML_CHARS_FOR_LLM,
        )
        html = html[:MAX_HTML_CHARS_FOR_LLM]

    return html


def _get_llm(deployment: str) -> AzureChatOpenAI:
    """Create an AzureChatOpenAI instance for the given deployment."""
    return AzureChatOpenAI(
        azure_deployment=deployment,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=LLM_TEMPERATURE,
    )


# ── Strategy 1: Direct API ───────────────────────────────────────────────────

def extract_from_api(api_data: list | dict) -> ExtractionResult:
    """
    Parse announcements directly from a discovered JSON API response.
    No LLM needed — straightforward key mapping.
    """
    logger.info("Extracting from API data (no LLM needed)")
    items: list = []

    if isinstance(api_data, list):
        items = api_data
    elif isinstance(api_data, dict):
        for key in ("data", "results", "items", "records", "list"):
            if key in api_data and isinstance(api_data[key], list):
                items = api_data[key]
                break

    announcements: list[Announcement] = []
    for item in items:
        try:
            title = _extract_field(item, ["title", "name", "subject", "heading", "circular_name"])
            date_str = _extract_field(item, ["date", "issue_date", "issuedate", "publish_date", "circular_date"])
            if title and date_str:
                issue_date = _parse_date(date_str)
                if issue_date:
                    announcements.append(
                        Announcement(title=title, issue_date=issue_date, confidence=0.95)
                    )
        except Exception as exc:
            logger.debug("Skipping API item: %s", exc)

    return ExtractionResult(
        announcements=announcements,
        source_strategy="api",
        raw_count=len(items),
    )


def _extract_field(item: dict, candidate_keys: list[str]) -> Optional[str]:
    """Try multiple key names (case-insensitive) to extract a field."""
    item_lower = {k.lower(): v for k, v in item.items()}
    for key in candidate_keys:
        if key in item_lower and item_lower[key]:
            return str(item_lower[key])
    return None


def _parse_date(date_str: str) -> Optional[date]:
    """Try multiple date formats to parse a date string."""
    import datetime

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ── Strategy 2: DOM + LLM ────────────────────────────────────────────────────

async def extract_from_html(
    html: str,
    *,
    use_refined_prompt: bool = False,
) -> ExtractionResult:
    """
    Send cleaned HTML to an Azure OpenAI LLM and ask it to extract
    announcements semantically.

    Args:
        html: Raw HTML of the page.
        use_refined_prompt: If True, use the refined retry prompt.

    Returns:
        ExtractionResult with extracted announcements.
    """
    logger.info("Extracting from HTML using Azure LLM (deployment: %s)", LLM_DEPLOYMENT)
    cleaned = _clean_html(html)

    llm = _get_llm(LLM_DEPLOYMENT)
    structured_llm = llm.with_structured_output(AnnouncementList)

    prompt_template = REFINED_PROMPT if use_refined_prompt else DOM_EXTRACTION_PROMPT
    user_content = prompt_template.format(html=cleaned)

    try:
        result: AnnouncementList = await structured_llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ]
        )

        logger.info(
            "LLM extracted %d announcements from HTML",
            len(result.announcements),
        )

        return ExtractionResult(
            announcements=result.announcements,
            source_strategy="dom_llm",
            raw_count=len(result.announcements),
        )

    except Exception as exc:
        logger.error("LLM extraction failed: %s", exc)
        return ExtractionResult(
            announcements=[],
            source_strategy="dom_llm",
            raw_count=0,
            error=str(exc),
        )


# ── Strategy 3: Vision LLM ───────────────────────────────────────────────────

async def extract_from_screenshot(screenshot_b64: str) -> ExtractionResult:
    """
    Send a screenshot to a Vision-capable Azure LLM for extraction.

    Args:
        screenshot_b64: Base64-encoded PNG screenshot.

    Returns:
        ExtractionResult with extracted announcements.
    """
    logger.info("Extracting from screenshot using Vision LLM (deployment: %s)", VISION_DEPLOYMENT)

    llm = _get_llm(VISION_DEPLOYMENT)

    try:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "text", "text": VISION_EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}",
                            "detail": "high",
                        },
                    },
                ]
            ),
        ]

        # Vision models may not support structured output perfectly,
        # so we parse manually
        response = await llm.ainvoke(messages)
        content = response.content

        # Try to extract JSON from the response
        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if not json_match:
            json_match = re.search(r"\{.*\}", content, re.DOTALL)

        if json_match:
            data = json.loads(json_match.group())
            if isinstance(data, dict) and "announcements" in data:
                data = data["announcements"]
            if isinstance(data, list):
                announcements = []
                for item in data:
                    try:
                        ann = Announcement(**item)
                        ann.confidence = min(ann.confidence, 0.7)  # Lower confidence for vision
                        announcements.append(ann)
                    except Exception:
                        continue

                return ExtractionResult(
                    announcements=announcements,
                    source_strategy="vision_llm",
                    raw_count=len(announcements),
                )

        return ExtractionResult(
            announcements=[],
            source_strategy="vision_llm",
            raw_count=0,
            error="Could not parse Vision LLM response",
        )

    except Exception as exc:
        logger.error("Vision LLM extraction failed: %s", exc)
        return ExtractionResult(
            announcements=[],
            source_strategy="vision_llm",
            raw_count=0,
            error=str(exc),
        )
