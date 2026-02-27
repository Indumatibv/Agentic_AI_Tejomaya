"""
CLI entrypoint for the SEBI Agentic Scraper.

Usage:
    python main.py

The scraper will:
1. Load the SEBI circulars page using Playwright
2. Inspect network traffic for backend JSON APIs
3. Extract announcements using LLM-powered semantic analysis
4. Validate and deduplicate results
5. Output a formatted table and save JSON to output/announcements.json
"""

import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

from config import SEBI_URL, LOG_LEVEL, LOG_FORMAT, OUTPUT_DIR, AZURE_OPENAI_KEY
from graph import compile_scraper, ScraperState


def setup_logging() -> None:
    """Configure structured logging for the entire application."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def print_results_table(announcements: list[dict]) -> None:
    """Print announcements in a formatted table to stdout."""
    if not announcements:
        print("\n⚠️  No announcements extracted.")
        return

    # Header
    print("\n" + "=" * 100)
    print(f"{'No.':<5} {'Issue Date':<14} {'Conf.':<7} {'Title'}")
    print("-" * 100)

    for i, ann in enumerate(announcements, 1):
        issue_date = ann.get("issue_date", "N/A")
        if isinstance(issue_date, date):
            issue_date = issue_date.isoformat()
        confidence = ann.get("confidence", 0.0)
        title = ann.get("title", "N/A")

        # Truncate title for display
        display_title = title[:70] + "..." if len(title) > 70 else title
        print(f"{i:<5} {issue_date:<14} {confidence:<7.2f} {display_title}")

    print("=" * 100)
    print(f"Total: {len(announcements)} announcements\n")


async def run_scraper() -> int:
    """
    Execute the full scraper pipeline and return an exit code.

    Returns:
        0: Success (announcements extracted)
        1: Partial success (some announcements, with errors)
        2: Failure (no announcements extracted)
    """
    logger = logging.getLogger(__name__)

    # Validate API key
    if not AZURE_OPENAI_KEY:
        logger.error(
            "AZURE_OPENAI_KEY is not set. "
            "Set it via environment variable or .env file."
        )
        print("\n❌ Error: AZURE_OPENAI_KEY is not configured.")
        print("   Set it via: export AZURE_OPENAI_KEY='your-key-here'")
        print("   Or create a .env file in the project root.\n")
        return 2

    logger.info("=" * 60)
    logger.info("SEBI Agentic Scraper — Starting")
    logger.info("Target URL: %s", SEBI_URL)
    logger.info("Output dir: %s", OUTPUT_DIR)
    logger.info("=" * 60)

    try:
        # Compile and invoke the LangGraph pipeline
        scraper = compile_scraper()
        initial_state = ScraperState(url=SEBI_URL)

        logger.info("Invoking scraper graph...")
        final_state = await scraper.ainvoke(initial_state.model_dump())

        # Extract results
        announcements = final_state.get("validated_announcements", [])
        errors = final_state.get("errors", [])
        strategy = final_state.get("strategy_used", "unknown")
        output_path = final_state.get("output_path")
        stats = final_state.get("validation_stats", {})

        # Print results
        print_results_table(announcements)

        # Print metadata
        print(f"📊 Strategy used: {strategy}")
        if stats:
            print(
                f"📋 Validation: {stats.get('valid', 0)}/{stats.get('total_input', 0)} passed"
            )
        if output_path:
            print(f"💾 JSON saved to: {output_path}")

        if errors:
            print(f"\n⚠️  Errors encountered ({len(errors)}):")
            for err in errors:
                print(f"   • {err}")

        # Determine exit code
        if announcements and not errors:
            logger.info("Scraper completed successfully (%d announcements)", len(announcements))
            return 0
        elif announcements:
            logger.warning(
                "Scraper completed with warnings (%d announcements, %d errors)",
                len(announcements),
                len(errors),
            )
            return 1
        else:
            logger.error("Scraper failed — no announcements extracted")
            return 2

    except KeyboardInterrupt:
        logger.info("Scraper interrupted by user")
        return 2
    except Exception as exc:
        logger.exception("Unhandled exception: %s", exc)
        print(f"\n❌ Fatal error: {exc}")
        return 2


def main() -> None:
    """Main entrypoint — sets up logging and runs the async scraper."""
    setup_logging()
    exit_code = asyncio.run(run_scraper())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
