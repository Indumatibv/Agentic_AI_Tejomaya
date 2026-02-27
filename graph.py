"""
LangGraph workflow — multi-node agent graph for the SEBI scraper.

Orchestrates the full pipeline:
  loader → network_inspector → extractor → validator → output

With conditional retry logic and screenshot fallback on failure.
"""

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Optional

from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field

from models.schema import Announcement, ExtractionResult
from tools.browser import load_page
from tools.network_inspector import inspect_network, NetworkInspectionResult
from tools.screenshot import capture_screenshot
from agents.extractor_agent import (
    extract_from_api,
    extract_from_html,
    extract_from_screenshot,
)
from agents.validator_agent import validate_announcements, ValidationStats
from tools.downloader import extract_pdf_url_from_detail_page, download_pdf, get_structured_path
from config import (
    URL_of_domain,
    MAX_RETRIES,
    OUTPUT_DIR,
    PDF_BASE_DIR,
    RETRY_DELAY_SECONDS,
    WEEKS_BACK,
    EXCLUDED_KEYWORDS,
    AIF_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class ScraperState(BaseModel):
    """Shared state flowing through the LangGraph nodes."""

    url: str = Field(default=URL_of_domain)
    html: Optional[str] = Field(default=None)
    network_result: Optional[dict] = Field(default=None)
    extraction_result: Optional[dict] = Field(default=None)
    validated_announcements: list[Announcement] = Field(default_factory=list)
    category: str
    subfolder: str
    downloaded_count: int = Field(default=0)
    validation_stats: Optional[dict] = Field(default=None)
    retry_count: int = Field(default=0)
    errors: list[str] = Field(default_factory=list)
    strategy_used: str = Field(default="")
    screenshot_b64: Optional[str] = Field(default=None)
    output_path: Optional[str] = Field(default=None)


# ── Node functions ────────────────────────────────────────────────────────────

async def loader_node(state: ScraperState) -> dict:
    """Load the SEBI page and return the HTML content."""
    logger.info("═══ LOADER NODE ═══")
    try:
        html = await load_page(state.url)
        logger.info("Page loaded: %d characters", len(html))
        return {"html": html}
    except Exception as exc:
        error_msg = f"Loader failed: {exc}"
        logger.error(error_msg)
        return {"errors": state.errors + [error_msg]}


async def network_inspector_node(state: ScraperState) -> dict:
    """Inspect network traffic for a JSON API."""
    logger.info("═══ NETWORK INSPECTOR NODE ═══")
    try:
        result: NetworkInspectionResult = await inspect_network(state.url)
        return {
            "network_result": {
                "found_json_api": result.found_json_api,
                "api_url": result.api_url,
                "api_response_body": result.api_response_body,
                "xhr_urls": result.xhr_urls,
            }
        }
    except Exception as exc:
        logger.warning("Network inspection failed (non-fatal): %s", exc)
        return {
            "network_result": {
                "found_json_api": False,
                "api_url": None,
                "api_response_body": None,
                "xhr_urls": [],
            }
        }


async def extractor_node(state: ScraperState) -> dict:
    """Extract announcements using the best available strategy."""
    logger.info("═══ EXTRACTOR NODE ═══ (attempt %d)", state.retry_count + 1)

    extraction: Optional[ExtractionResult] = None

    # Strategy 1: Use API if discovered
    net = state.network_result or {}
    if net.get("found_json_api") and net.get("api_response_body"):
        logger.info("Using API strategy")
        extraction = extract_from_api(net["api_response_body"])
        if extraction.announcements:
            return {
                "extraction_result": extraction.model_dump(),
                "strategy_used": "api",
            }
        logger.warning("API extraction yielded 0 results, falling back to DOM+LLM")

    # Strategy 2: DOM + LLM
    if state.html:
        logger.info("Using DOM + LLM strategy")
        use_refined = state.retry_count > 0
        extraction = await extract_from_html(state.html, use_refined_prompt=use_refined)
        if extraction.announcements:
            return {
                "extraction_result": extraction.model_dump(),
                "strategy_used": "dom_llm",
            }
        logger.warning("DOM+LLM extraction yielded 0 results")

    # If we get here, extraction failed or is empty
    error_msg = extraction.error if extraction else "No HTML available for extraction"
    return {
        "extraction_result": (extraction.model_dump() if extraction else None),
        "strategy_used": "failed",
        "errors": state.errors + [f"Extraction failed: {error_msg}"],
        "retry_count": state.retry_count + 1,
    }


async def validator_node(state: ScraperState) -> dict:
    """Validate extracted announcements and filter by date window."""
    logger.info("═══ VALIDATOR NODE ═══")
    
    extraction_dict = state.extraction_result
    if not extraction_dict:
        return {"errors": ["No extraction result to validate"]}
    
    # 1. Re-parse into Pydantic model for clean logic
    extraction = ExtractionResult(**extraction_dict)
    
    # 2. Run core validation (Exclusions, Remapping, Scoring, Dedup)
    validated, stats_obj = await validate_announcements(extraction, base_category=state.category)
    
    # 3. Apply Date Window Filtering (Manual sync with WEEKS_BACK)
    today = date.today()
    weekday = today.weekday()
    this_monday = today - timedelta(days=weekday)
    
    if WEEKS_BACK == 0:
        start_date = this_monday
        end_date = today
    else:
        start_date = this_monday - timedelta(weeks=WEEKS_BACK)
        end_date = start_date + timedelta(days=6)
        
    logger.info("Scraping window: %s to %s", start_date, end_date)
    
    final_announcements = []
    out_of_window = 0
    
    for ann in validated:
        if ann.issue_date < start_date or ann.issue_date > end_date:
            out_of_window += 1
            continue
        
        # Ensure subfolder is set (from state)
        ann.category = ann.category or state.category
        final_announcements.append(ann)
        
    logger.info(
        "Validation complete: %d/25 passed | window_out=%d, %s",
        len(final_announcements), 
        out_of_window,
        stats_obj.summary()
    )
    
    # Convert stats to dict for state
    stats_dict = {
        "total": len(extraction.announcements),
        "valid": len(final_announcements),
        "out_of_window": out_of_window,
        "excluded": stats_obj.excluded_by_keyword,
        "remapped": stats_obj.remapped_to_aif,
        "duplicates": stats_obj.removed_duplicates
    }
    
    return {
        "validated_announcements": final_announcements,
        "validation_stats": stats_dict
    }


async def output_node(state: ScraperState) -> dict:
    """Write results to JSON and format for display."""
    logger.info("═══ OUTPUT NODE ═══")

    announcements = state.validated_announcements
    output_path = OUTPUT_DIR / "announcements.json"

    # Serialise dates as strings for JSON
    serialisable = []
    for ann in announcements:
        entry = ann.model_dump()
        if isinstance(entry.get("issue_date"), date):
            entry["issue_date"] = entry["issue_date"].isoformat()
        serialisable.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(serialisable, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Results saved to: %s", output_path)

    return {"output_path": str(output_path)}


async def pdf_downloader_node(state: ScraperState) -> dict:
    """Download PDFs for each validated announcement."""
    logger.info("═══ PDF DOWNLOADER NODE ═══")
    
    announcements = state.validated_announcements
    downloaded = 0
    updated_announcements = []
    
    # Process all announcements matching the period
    for ann in announcements:
        detail_url = ann.detail_url
        if not detail_url:
            updated_announcements.append(ann)
            continue
            
        # 1. Extract PDF URL
        pdf_url = await extract_pdf_url_from_detail_page(detail_url)
        if pdf_url:
            ann.pdf_url = pdf_url
            
            # 2. Determine folder structure
            issue_date = ann.issue_date
            ann_category = ann.category or state.category
            save_dir = get_structured_path(PDF_BASE_DIR, ann_category, state.subfolder, issue_date)
            
            # 3. Download PDF
            # Clean filename: replace spaces/special chars with underscores
            clean_title = re.sub(r'[^\w\s-]', '', ann.title or "document").strip().replace(' ', '_')
            filename = f"{clean_title[:100]}"
            
            local_path = await download_pdf(pdf_url, save_dir, filename)
            if local_path:
                ann.local_path = str(local_path)
                ann.file_name = f"{filename}.pdf"
                downloaded += 1
                
        updated_announcements.append(ann)
        
    return {
        "validated_announcements": updated_announcements,
        "downloaded_count": downloaded
    }


async def screenshot_fallback_node(state: ScraperState) -> dict:
    """Capture screenshot and extract via Vision LLM."""
    logger.info("═══ SCREENSHOT FALLBACK NODE ═══")
    try:
        b64 = await capture_screenshot(state.url)
        extraction = await extract_from_screenshot(b64)
        return {
            "extraction_result": extraction.model_dump(),
            "strategy_used": "vision_llm",
            "screenshot_b64": b64,
            "retry_count": state.retry_count + 1,
        }
    except Exception as exc:
        error_msg = f"Screenshot fallback failed: {exc}"
        logger.error(error_msg)
        return {
            "errors": state.errors + [error_msg],
            "retry_count": state.retry_count + 1,
        }


# ── Conditional edges ─────────────────────────────────────────────────────────

def should_retry_or_fallback(state: ScraperState) -> str:
    """Decide whether to proceed, retry, or use screenshot fallback."""
    extraction = state.extraction_result or {}
    announcements = extraction.get("announcements", [])

    if announcements:
        # We have results — proceed to validation
        return "validate"

    if state.retry_count < MAX_RETRIES:
        if state.retry_count == 0:
            # First failure — retry with refined prompt
            return "retry_extract"
        else:
            # Second+ failure — try screenshot fallback
            return "screenshot_fallback"

    # Max retries exceeded
    return "validate"  # Proceed with whatever we have (possibly empty)


def after_screenshot_decision(state: ScraperState) -> str:
    """After screenshot fallback, decide whether to validate or give up."""
    extraction = state.extraction_result or {}
    if extraction.get("announcements"):
        return "validate"
    if state.retry_count < MAX_RETRIES:
        return "retry_extract"
    return "validate"


# ── Build the graph ───────────────────────────────────────────────────────────

def build_scraper_graph() -> StateGraph:
    """
    Construct the LangGraph StateGraph for the SEBI scraper pipeline.

    Graph topology:
        loader → network_inspector → extractor → [conditional]
                                                     ├─ validate → output → END
                                                     ├─ retry_extract → extractor
                                                     └─ screenshot_fallback → [conditional]
                                                                                ├─ validate
                                                                                └─ retry_extract
    """
    graph = StateGraph(ScraperState)

    # Add nodes
    graph.add_node("loader", loader_node)
    graph.add_node("network_inspector", network_inspector_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("validator", validator_node)
    graph.add_node("output", output_node)
    graph.add_node("screenshot_fallback", screenshot_fallback_node)
    graph.add_node("pdf_downloader", pdf_downloader_node)

    # Linear edges
    graph.add_edge("loader", "network_inspector")
    graph.add_edge("network_inspector", "extractor")

    # Conditional edge after extraction
    graph.add_conditional_edges(
        "extractor",
        should_retry_or_fallback,
        {
            "validate": "validator",
            "retry_extract": "extractor",
            "screenshot_fallback": "screenshot_fallback",
        },
    )

    # Conditional edge after screenshot fallback
    graph.add_conditional_edges(
        "screenshot_fallback",
        after_screenshot_decision,
        {
            "validate": "validator",
            "retry_extract": "extractor",
        },
    )

    # Linear edges to finish
    graph.add_edge("validator", "pdf_downloader")
    graph.add_edge("pdf_downloader", "output")
    graph.add_edge("output", END)

    # Entry point
    graph.set_entry_point("loader")

    return graph


def compile_scraper():
    """Compile and return the runnable scraper graph."""
    graph = build_scraper_graph()
    return graph.compile()
