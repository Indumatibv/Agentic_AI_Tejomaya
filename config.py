"""
Configuration module for the SEBI Agentic Scraper.

Loads settings from environment variables with sensible defaults.
Uses python-dotenv for local .env file support.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


# --- Azure OpenAI Settings ---
AZURE_OPENAI_ENDPOINT: str = os.getenv(
    "AZURE_OPENAI_ENDPOINT", "https://arcaquest-emr.openai.azure.com/"
)
AZURE_OPENAI_KEY: str = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION: str = os.getenv(
    "AZURE_OPENAI_API_VERSION", "2024-12-01-preview"
)

# --- LLM Deployment Names (Azure deployment names) ---
LLM_DEPLOYMENT: str = os.getenv("LLM_DEPLOYMENT", "gpt-4.1-mini")
VISION_DEPLOYMENT: str = os.getenv("VISION_DEPLOYMENT", "gpt-4.1-mini")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))

# --- Target URL ---
URL_of_domain: str = os.getenv(
    "URL_of_domain",
    "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=2&ssid=10&smid=0",
)

# --- Browser Settings ---
HEADLESS: bool = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
PAGE_TIMEOUT_MS: int = int(os.getenv("PAGE_TIMEOUT_MS", "60000"))
NETWORK_IDLE_TIMEOUT_MS: int = int(os.getenv("NETWORK_IDLE_TIMEOUT_MS", "30000"))

# --- Retry / Resilience ---
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY_SECONDS: float = float(os.getenv("RETRY_DELAY_SECONDS", "2.0"))

# Where PDFs should be stored
DEFAULT_PDF_BASE: Path = Path.home() / "Downloads" / "Tejomaya_pdfs_test" / "Akshayam Data"
PDF_BASE_DIR: Path = Path(os.getenv("PDF_BASE_DIR", str(DEFAULT_PDF_BASE)))
PDF_BASE_DIR.mkdir(parents=True, exist_ok=True)

# --- Paths ---
PROJECT_ROOT: Path = Path(__file__).resolve().parent
OUTPUT_DIR: Path = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LINKS_EXCEL: Path = DATA_DIR / "Links.xlsx"
FINAL_EXCEL_OUTPUT: Path = DATA_DIR / "Searching_agent_output.xlsx"

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = os.getenv(
    "LOG_FORMAT",
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

# --- Validation ---
MIN_ANNOUNCEMENT_YEAR: int = int(os.getenv("MIN_ANNOUNCEMENT_YEAR", "1992"))  # SEBI founded
MAX_HTML_CHARS_FOR_LLM: int = int(os.getenv("MAX_HTML_CHARS_FOR_LLM", "60000"))

# --- Scraping Window ---
# 0 = Current week (Mon-Now), 1 = Last week (Prev Mon - Prev Sun), etc.
WEEKS_BACK: int = int(os.getenv("WEEKS_BACK", "3"))

# --- Keyword Exclusions ---
EXCLUDED_KEYWORDS: list[str] = [
    "Mutual fund", "Mutual funds", "KRAs", "CRAs", "Niveshak Shivir", 
    "inauguration", "survey", "Minicipal Bond", "Municipal Bond",
    "contest", "campaign", "annual report", 
    "newspaper advertisement"
]

# --- Category Mappings (Verticals) ---
# If SEBI title contains these, change category from SEBI to AIF
AIF_KEYWORDS: list[str] = [
    "Portfolio Managers",
    "Angel investors", "Angel funds",
    "Infrastructure Investment Trust", "InviTs",
    "Real Estate Investment Trusts", "ReiTs",
    "Research Analyst",
    "Investment Advisors",
    "Alternative Investment Trusts",
    "Alternative Investment Funds",
    "AIF"
]
