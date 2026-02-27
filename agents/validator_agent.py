"""
Validator Agent — validates, deduplicates, and scores extracted announcements.

Ensures data quality after extraction:
- Date format and realism checks
- Non-empty title validation
- Duplicate removal
- Confidence scoring adjustments
"""

import logging
from datetime import date, timedelta
from typing import Optional

from models.schema import Announcement, ExtractionResult
from config import MIN_ANNOUNCEMENT_YEAR, EXCLUDED_KEYWORDS, AIF_KEYWORDS

logger = logging.getLogger(__name__)


class ValidationStats:
    """Tracks validation outcomes for reporting."""

    def __init__(self) -> None:
        self.total_input: int = 0
        self.valid: int = 0
        self.removed_empty_title: int = 0
        self.removed_invalid_date: int = 0
        self.removed_duplicates: int = 0
        self.removed_unrealistic_date: int = 0
        self.excluded_by_keyword: int = 0
        self.remapped_to_aif: int = 0

    def summary(self) -> str:
        return (
            f"Validation: {self.valid}/{self.total_input} passed | "
            f"excluded={self.excluded_by_keyword}, "
            f"remapped_AIF={self.remapped_to_aif}, "
            f"duplicates={self.removed_duplicates}, "
            f"empty_title={self.removed_empty_title}"
        )


async def validate_announcements(
    extraction: ExtractionResult,
    base_category: str = "SEBI",
) -> tuple[list[Announcement], ValidationStats]:
    """
    Validate and clean a list of extracted announcements.

    Checks:
    1. Title is non-empty and has meaningful content
    2. Date is valid and realistic
    3. No exact duplicates (by title + date)
    4. Confidence adjustments based on data quality
    5. Dynamic category remapping (e.g. SEBI -> AIF)

    Args:
        extraction: The raw ExtractionResult from the extractor agent.
        base_category: The initial category (e.g. "SEBI", "RBI").

    Returns:
        Tuple of (validated announcements, validation statistics).
    """
    stats = ValidationStats()
    stats.total_input = len(extraction.announcements)

    validated: list[Announcement] = []
    seen: set[tuple[str, date]] = set()

    today = date.today()
    # Allow a small future buffer (3 days) for timezone differences
    max_date = today + timedelta(days=3)
    min_date = date(MIN_ANNOUNCEMENT_YEAR, 1, 1)

    for ann in extraction.announcements:
        # 1. Title validation
        title = ann.title.strip()
        if not _is_valid_title(title):
            stats.removed_empty_title += 1
            continue

        # 2. Keyword Exclusion
        is_excluded = False
        for kw in EXCLUDED_KEYWORDS:
            if kw.lower() in title.lower():
                logger.info("Excluding announcement due to keyword '%s': %s", kw, title)
                is_excluded = True
                break
        
        if is_excluded:
            stats.excluded_by_keyword += 1
            continue

        # 3. Date realism check
        if not _is_realistic_date(ann.issue_date, min_date, max_date):
            stats.removed_unrealistic_date += 1
            continue

        # 4. Duplicate check
        dedup_key = (_normalise_title(title), ann.issue_date)
        if dedup_key in seen:
            stats.removed_duplicates += 1
            continue
        seen.add(dedup_key)

        # 5. Dynamic Category Mapping (Source-agnostic logic)
        category = base_category
        
        # Only SEBI -> AIF remapping for now
        if base_category == "SEBI":
            for kw in AIF_KEYWORDS:
                if kw.lower() in title.lower():
                    logger.info("Mapping vertical to AIF due to keyword '%s': %s", kw, title)
                    category = "AIF"
                    stats.remapped_to_aif += 1
                    break

        # 6. Confidence adjustment and final object creation
        adjusted_confidence = _adjust_confidence(ann)
        validated_ann = ann.model_copy(update={
            "confidence": adjusted_confidence,
            "category": category
        })

        validated.append(validated_ann)
        stats.valid += 1

    logger.info(stats.summary())
    return validated, stats


def _is_valid_title(title: str) -> bool:
    """Check that a title has meaningful content."""
    if not title or not title.strip():
        return False
    # Must have at least some alphabetic characters
    alpha_count = sum(1 for c in title if c.isalpha())
    return alpha_count >= 5


def _is_realistic_date(
    d: date,
    min_date: date,
    max_date: date,
) -> bool:
    """Check that a date falls within a realistic range for SEBI circulars."""
    return min_date <= d <= max_date


def _normalise_title(title: str) -> str:
    """Normalise title for deduplication — lowercase, strip extra whitespace."""
    return " ".join(title.lower().split())


def _adjust_confidence(ann: Announcement) -> float:
    """
    Adjust the confidence score based on heuristic quality signals.

    Boosts:
    - Title contains regulatory keywords (domain-agnostic)
    - Date is recent

    Penalties:
    - Very short title
    - Very old date
    """
    score = ann.confidence

    # Title length heuristic
    if len(ann.title) < 20:
        score *= 0.8
    elif len(ann.title) > 50:
        score = min(score * 1.05, 1.0)

    # Regulatory keyword boost (broadened)
    regulatory_keywords = {
        "sebi", "rbi", "nse", "bse", "circular", "regulation", 
        "amendment", "notification", "master direction", "guideline"
    }
    title_lower = ann.title.lower()
    if any(kw in title_lower for kw in regulatory_keywords):
        score = min(score * 1.1, 1.0)
    
    # Category match boost
    if ann.category and ann.category.lower() in title_lower:
        score = min(score * 1.05, 1.0)

    # Recency check
    days_old = (date.today() - ann.issue_date).days
    if days_old > 3650:  # Older than 10 years
        score *= 0.9

    return round(min(max(score, 0.0), 1.0), 3)
