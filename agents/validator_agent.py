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
from config import MIN_ANNOUNCEMENT_YEAR

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

    def summary(self) -> str:
        return (
            f"Validation: {self.valid}/{self.total_input} passed | "
            f"empty_title={self.removed_empty_title}, "
            f"invalid_date={self.removed_invalid_date}, "
            f"unrealistic_date={self.removed_unrealistic_date}, "
            f"duplicates={self.removed_duplicates}"
        )


async def validate_announcements(
    extraction: ExtractionResult,
) -> tuple[list[Announcement], ValidationStats]:
    """
    Validate and clean a list of extracted announcements.

    Checks:
    1. Title is non-empty and has meaningful content
    2. Date is valid and realistic
    3. No exact duplicates (by title + date)
    4. Confidence adjustments based on data quality

    Args:
        extraction: The raw ExtractionResult from the extractor agent.

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
        if not _is_valid_title(ann.title):
            stats.removed_empty_title += 1
            logger.debug("Removed (empty/invalid title): %s", ann.title[:50])
            continue

        # 2. Date realism check
        if not _is_realistic_date(ann.issue_date, min_date, max_date):
            stats.removed_unrealistic_date += 1
            logger.debug(
                "Removed (unrealistic date %s): %s",
                ann.issue_date,
                ann.title[:50],
            )
            continue

        # 3. Duplicate check
        dedup_key = (_normalise_title(ann.title), ann.issue_date)
        if dedup_key in seen:
            stats.removed_duplicates += 1
            logger.debug("Removed (duplicate): %s", ann.title[:50])
            continue
        seen.add(dedup_key)

        # 4. Confidence adjustment
        adjusted_confidence = _adjust_confidence(ann)
        validated_ann = ann.model_copy(update={"confidence": adjusted_confidence})

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
    - Title contains 'SEBI' or regulatory keywords
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

    # Regulatory keyword boost
    regulatory_keywords = {"sebi", "circular", "regulation", "amendment", "notification"}
    title_lower = ann.title.lower()
    if any(kw in title_lower for kw in regulatory_keywords):
        score = min(score * 1.1, 1.0)

    # Recency check
    days_old = (date.today() - ann.issue_date).days
    if days_old > 3650:  # Older than 10 years
        score *= 0.9

    return round(min(max(score, 0.0), 1.0), 3)
