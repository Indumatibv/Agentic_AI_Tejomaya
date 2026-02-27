"""
Excel Manager — Handles structured Excel reporting for the SEBI Scraper.
"""

import pandas as pd
from pathlib import Path
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

def save_announcements_to_excel(announcements: List[Dict], output_path: Path):
    """
    Save extracted and validated announcements to an Excel file with the required columns.
    
    Verticals, SubCategory, Year, Month, IssueDate, Title, PDF_URL, File Name, Path
    """
    if not announcements:
        logger.warning("No announcements to save to Excel.")
        return

    logger.info("Saving %d announcements to Excel: %s", len(announcements), output_path)

    data = []
    for ann in announcements:
        # User requested to only include the downloaded announcement in the final report
        if not ann.get("local_path"):
            continue

        # Format IssueDate for readability
        issue_date = ann.get("issue_date", "")
        if hasattr(issue_date, "strftime"):
             formatted_date = issue_date.strftime("%d-%m-%Y")
        else:
             formatted_date = str(issue_date)

        # Prepare row data, ensuring we handle both Pydantic models (dicts) and raw dicts
        row = {
            "Verticals": ann.get("category", "SEBI"),
            "SubCategory": ann.get("subfolder", "Circulars"),
            "Year": ann.get("year", ""),
            "Month": ann.get("month", ""),
            "IssueDate": formatted_date,
            "Title": ann.get("title", ""),
            "PDF_URL": ann.get("pdf_url", ""),
            "File Name": ann.get("file_name", ""),
            "Path": ann.get("local_path", "")
        }
        data.append(row)

    df = pd.DataFrame(data)
    
    # Ensure columns are in the correct order
    columns = ["Verticals", "SubCategory", "Year", "Month", "IssueDate", "Title", "PDF_URL", "File Name", "Path"]
    df = df[columns]

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        logger.info("Existing report found. Overwriting: %s", output_path)
    else:
        logger.info("Creating new report: %s", output_path)

    try:
        # Explicitly remove existing file to ensure refresh
        if output_path.exists():
            output_path.unlink()
            logger.info("Removed existing file to ensure full refresh.")
        
        df.to_excel(output_path, index=False)
        logger.info("Excel report generated successfully.")
    except Exception as exc:
        logger.error("Failed to save Excel report: %s", exc)

def load_link_tasks_from_excel(input_path: Path) -> List[Dict]:
    """
    Load tasks (category, subfolder, url) from an input Excel file.
    Expected columns: Verticals, SubCategory, URL
    """
    if not input_path.exists():
        logger.warning("Input Excel not found: %s", input_path)
        return []

    try:
        df = pd.read_excel(input_path)
        tasks = []
        for _, row in df.iterrows():
            tasks.append({
                "category": row.get("Verticals", "SEBI"),
                "subfolder": row.get("SubCategory", "Circulars"),
                "url": row.get("URL", "")
            })
        return [t for t in tasks if t["url"]]
    except Exception as exc:
        logger.error("Failed to load tasks from Excel: %s", exc)
        return []
