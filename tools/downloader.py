"""
Downloader — Handles PDF discovery and downloading from SEBI detail pages.
"""

import logging
import re
import aiohttp
import asyncio
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright
from config import PDF_BASE_DIR, PAGE_TIMEOUT_MS

logger = logging.getLogger(__name__)

async def extract_pdf_url_from_detail_page(page_url: str) -> Optional[str]:
    """
    Navigates to the intermediate page and extracts the direct PDF URL from the iframe.
    """
    if not page_url:
        return None

    logger.info("Extracting PDF URL from detail page: %s", page_url)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(page_url, timeout=PAGE_TIMEOUT_MS, wait_until="networkidle")
            
            # Look for iframe with src containing 'file='
            iframe_src = await page.evaluate('''() => {
                const iframe = document.querySelector('iframe[src*="file="]');
                return iframe ? iframe.src : null;
            }''')
            
            if iframe_src:
                # Parse the 'file' parameter
                parsed_url = urlparse(iframe_src)
                params = parse_qs(parsed_url.query)
                if 'file' in params:
                    pdf_url = params['file'][0]
                    logger.info("Found PDF URL: %s", pdf_url)
                    return pdf_url
            
            # Fallback: look for any .pdf link
            pdf_link = await page.evaluate('''() => {
                const a = document.querySelector('a[href$=".pdf"]');
                return a ? a.href : null;
            }''')
            
            if pdf_link:
                logger.info("Found PDF link fallback: %s", pdf_link)
                return pdf_link

        except Exception as exc:
            logger.error("Failed to extract PDF URL from %s: %s", page_url, exc)
        finally:
            await browser.close()
            
    return None

async def download_pdf(pdf_url: str, save_dir: Path, filename: str) -> Optional[Path]:
    """
    Downloads a PDF file from the given URL and saves it to the specified directory.
    """
    if not pdf_url:
        return None

    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{filename}.pdf"

    logger.info("Downloading PDF: %s -> %s", pdf_url, save_path)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(pdf_url, timeout=30) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    if save_path.exists():
                        logger.info("PDF already exists. Replacing: %s", save_path)
                        save_path.unlink()
                    
                    save_path.write_bytes(content)
                    logger.info("Downloaded PDF successfully.")
                    return save_path
                else:
                    logger.error("Failed to download PDF (status %d): %s", response.status, pdf_url)
    except Exception as exc:
        logger.error("Error downloading PDF: %s", exc)
        
    return None

def get_structured_path(base_dir: Path, category: str, subfolder: str, issue_date) -> Path:
    """
    Constructs the structured path: downloads/Tejomaya_pdfs_test/Akshayam Data/SEBI/Circulars/YYYY/Month/
    """
    from datetime import date
    
    if isinstance(issue_date, str):
        try:
            from datetime import datetime
            issue_date = datetime.fromisoformat(issue_date).date()
        except:
            issue_date = date.today()
    elif not isinstance(issue_date, date):
        issue_date = date.today()

    year = str(issue_date.year)
    month = issue_date.strftime("%B")
    
    return base_dir / category / subfolder / year / month
