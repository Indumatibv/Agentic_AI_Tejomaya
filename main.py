import asyncio
import logging
import sys
from datetime import date
from typing import List, Dict

from config import AZURE_OPENAI_KEY, LINKS_EXCEL, URL_of_domain, FINAL_EXCEL_OUTPUT
from graph import compile_scraper, ScraperState
from tools.excel_manager import load_link_tasks_from_excel, save_announcements_to_excel

def setup_logging() -> None:
    """Configure structured logging."""
    from config import LOG_LEVEL, LOG_FORMAT
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

async def run_multi_source_scraper():
    """
    Main loop for multi-source scraping.
    """
    logger = logging.getLogger(__name__)

    if not AZURE_OPENAI_KEY:
        logger.error("AZURE_OPENAI_KEY not found. Please check your .env file.")
        return

    # 1. Default task (skipping Excel loading as requested)
    tasks = [{"category": "SEBI", "subfolder": "Consultation Paper", "url": URL_of_domain}]
    logger.info("Using default task with URL: %s", URL_of_domain)

    # 2. Setup graph
    scraper = compile_scraper()
    all_results: List[Dict] = []

    logger.info("Starting batch processing of %d tasks...", len(tasks))

    # 3. Process each task
    for i, task in enumerate(tasks, 1):
        category = task["category"]
        subfolder = task["subfolder"]
        url = task["url"]

        logger.info("-" * 60)
        logger.info("TASK %d/%d: [%s] -> [%s]", i, len(tasks), category, subfolder)
        logger.info("URL: %s", url)
        logger.info("-" * 60)

        try:
            # Prepare initial state
            initial_state = ScraperState(
                url=url,
                category=category,
                subfolder=subfolder
            )

            # Invoke graph
            final_state = await scraper.ainvoke(initial_state.model_dump())
            
            # Collect results
            new_announcements = final_state.get("validated_announcements", [])
            downloaded = final_state.get("downloaded_count", 0)
            
            logger.info("Extracted %d valid announcements", len(new_announcements))
            logger.info("PDFs downloaded successfully: %d", downloaded)
            
            for ann_obj in new_announcements:
                # Convert Pydantic object to dict for processing/saving
                ann = ann_obj.model_dump()
                
                # Ensure category and subfolder are set
                ann["category"] = ann.get("category") or category
                ann["subfolder"] = ann.get("subfolder") or subfolder
                
                issue_date = ann.get("issue_date")
                dt = None
                if isinstance(issue_date, date):
                    dt = issue_date
                elif isinstance(issue_date, str):
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(issue_date).date()
                    except:
                        pass
                
                if dt:
                    ann["year"] = dt.year
                    ann["month"] = dt.strftime("%B")
                
                all_results.append(ann)

        except Exception as exc:
            logger.error("Failed to process task %s: %s", url, exc)

    # 4. Final Save
    logger.info("=" * 60)
    logger.info("SCRAPING COMPLETE: %d total announcements found.", len(all_results))
    save_announcements_to_excel(all_results, FINAL_EXCEL_OUTPUT)
    logger.info("Excel results saved to: %s", FINAL_EXCEL_OUTPUT)
    logger.info("=" * 60)

def main() -> None:
    setup_logging()
    try:
        asyncio.run(run_multi_source_scraper())
    except KeyboardInterrupt:
        print("\nScraper stopped by user.")
    except Exception as exc:
        print(f"\nFatal error: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()
