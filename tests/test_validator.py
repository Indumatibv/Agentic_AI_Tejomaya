"""
Unit tests for the Validator Agent.

Tests cover:
- Valid announcements pass through
- Empty / meaningless titles are rejected
- Future dates are rejected
- Ancient (unrealistic) dates are rejected
- Duplicate announcements are removed
- Confidence scoring adjustments
"""

import asyncio
from datetime import date, timedelta

import pytest

# Adjust path so we can import from the project root
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.schema import Announcement, ExtractionResult
from agents.validator_agent import validate_announcements, _is_valid_title, _adjust_confidence


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_extraction(announcements: list[Announcement]) -> ExtractionResult:
    """Create an ExtractionResult from a list of Announcements."""
    return ExtractionResult(
        announcements=announcements,
        source_strategy="test",
        raw_count=len(announcements),
    )


def _run(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestValidAnnouncement:
    """Test that valid announcements pass validation."""

    def test_valid_announcement_passes(self):
        ann = Announcement(
            title="SEBI Circular on Disclosure Norms",
            issue_date=date(2025, 6, 15),
            confidence=0.9,
        )
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 1
        assert validated[0].title == ann.title
        assert validated[0].issue_date == ann.issue_date
        assert stats.valid == 1
        assert stats.total_input == 1

    def test_multiple_valid_announcements(self):
        announcements = [
            Announcement(title="Circular on Stock Brokers", issue_date=date(2025, 1, 10)),
            Announcement(title="Amendment to SEBI Regulations", issue_date=date(2025, 3, 20)),
            Announcement(title="Valuation of physical Assets", issue_date=date(2025, 5, 5)),
        ]
        extraction = _make_extraction(announcements)
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 3
        assert stats.valid == 3


class TestEmptyTitleRejection:
    """Test that empty or meaningless titles are rejected."""

    def test_empty_string_rejected(self):
        ann = Announcement(title="     ", issue_date=date(2025, 1, 1), confidence=0.9)
        # Pydantic will reject an empty string due to min_length=1
        # But whitespace-only bypasses min_length, so validator catches it
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 0
        assert stats.removed_empty_title == 1

    def test_too_few_alpha_chars_rejected(self):
        ann = Announcement(title="123-456", issue_date=date(2025, 1, 1), confidence=0.9)
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 0
        assert stats.removed_empty_title == 1


class TestDateValidation:
    """Test date realism checks."""

    def test_future_date_rejected(self):
        future = date.today() + timedelta(days=30)
        ann = Announcement(title="Future Circular Announcement", issue_date=future, confidence=0.9)
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 0
        assert stats.removed_unrealistic_date == 1

    def test_ancient_date_rejected(self):
        ann = Announcement(
            title="Ancient Circular Before SEBI Existed",
            issue_date=date(1980, 1, 1),
            confidence=0.9,
        )
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 0
        assert stats.removed_unrealistic_date == 1

    def test_recent_date_accepted(self):
        ann = Announcement(
            title="Recent SEBI Circular on Market Regulations",
            issue_date=date(2025, 1, 15),
            confidence=0.9,
        )
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 1


class TestDuplicateRemoval:
    """Test that exact duplicates are removed."""

    def test_exact_duplicates_removed(self):
        ann1 = Announcement(title="SEBI Circular on Brokers", issue_date=date(2025, 3, 1))
        ann2 = Announcement(title="SEBI Circular on Brokers", issue_date=date(2025, 3, 1))
        extraction = _make_extraction([ann1, ann2])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 1
        assert stats.removed_duplicates == 1

    def test_case_insensitive_duplicates(self):
        ann1 = Announcement(title="SEBI Circular on Brokers", issue_date=date(2025, 3, 1))
        ann2 = Announcement(title="sebi circular on brokers", issue_date=date(2025, 3, 1))
        extraction = _make_extraction([ann1, ann2])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 1
        assert stats.removed_duplicates == 1

    def test_different_dates_not_duplicate(self):
        ann1 = Announcement(title="SEBI Circular on Brokers", issue_date=date(2025, 3, 1))
        ann2 = Announcement(title="SEBI Circular on Brokers", issue_date=date(2025, 4, 1))
        extraction = _make_extraction([ann1, ann2])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))

        assert len(validated) == 2
        assert stats.removed_duplicates == 0


class TestConfidenceScoring:
    """Test confidence score adjustments."""

    def test_regulatory_keyword_boosts_confidence(self):
        ann = Announcement(
            title="SEBI Circular on Amendment to Regulation",
            issue_date=date(2025, 1, 1),
            confidence=0.8,
        )
        adjusted = _adjust_confidence(ann)
        assert adjusted > 0.8  # Should be boosted

    def test_short_title_reduces_confidence(self):
        ann = Announcement(
            title="Short title here",
            issue_date=date(2025, 1, 1),
            confidence=0.9,
        )
        adjusted = _adjust_confidence(ann)
        assert adjusted < 0.9  # Should be reduced

    def test_confidence_never_exceeds_one(self):
        ann = Announcement(
            title="SEBI Circular on Amendment to Regulation — Very Long Detailed Title",
            issue_date=date(2025, 1, 1),
            confidence=1.0,
        )
        adjusted = _adjust_confidence(ann)
        assert adjusted <= 1.0


class TestKeywordExclusion:
    """Test that unwanted announcements are skipped based on keywords."""

    def test_excluded_keyword_rejected(self):
        ann = Announcement(title="Mutual fund inauguration contest", issue_date=date(2025, 1, 1))
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))
        assert len(validated) == 0
        assert stats.excluded_by_keyword == 1

    def test_case_insensitive_exclusion(self):
        ann = Announcement(title="MUTUAL FUND NEWS", issue_date=date(2025, 1, 1))
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))
        assert len(validated) == 0
        assert stats.excluded_by_keyword == 1


class TestCategoryRemapping:
    """Test that SEBI -> AIF remapping works correctly."""

    def test_remaps_to_aif_on_keyword(self):
        ann = Announcement(title="Circular for Portfolio Managers", issue_date=date(2025, 1, 1))
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))
        assert len(validated) == 1
        assert validated[0].category == "AIF"
        assert stats.remapped_to_aif == 1

    def test_stays_sebi_by_default(self):
        ann = Announcement(title="Standard SEBI Circular", issue_date=date(2025, 1, 1))
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="SEBI"))
        assert len(validated) == 1
        assert validated[0].category == "SEBI"
        assert stats.remapped_to_aif == 0

    def test_rbi_category_persistence(self):
        ann = Announcement(title="RBI Master Direction on Fintech", issue_date=date(2025, 1, 1))
        extraction = _make_extraction([ann])
        validated, stats = _run(validate_announcements(extraction, base_category="RBI"))
        assert len(validated) == 1
        assert validated[0].category == "RBI"
        assert stats.remapped_to_aif == 0
