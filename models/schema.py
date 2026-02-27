"""
Pydantic models for structured data throughout the scraper pipeline.

These models enforce type safety and are used by LangChain for
structured LLM output parsing.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class Announcement(BaseModel):
    """A single SEBI circular / announcement entry."""

    title: str = Field(
        ...,
        min_length=1,
        description="The full title of the SEBI circular or announcement.",
    )
    issue_date: date = Field(
        ...,
        description="The date the circular was issued, in YYYY-MM-DD format.",
    )
    detail_url: Optional[str] = Field(
        default=None,
        description="The URL to the intermediate detail page for this announcement.",
    )
    pdf_url: Optional[str] = Field(
        default=None,
        description="The direct download URL for the PDF.",
    )
    local_path: Optional[str] = Field(
        default=None,
        description="The absolute local path where the PDF is stored.",
    )
    file_name: Optional[str] = Field(
        default=None,
        description="The name of the downloaded PDF file.",
    )
    category: Optional[str] = Field(
        default=None,
        description="The remapped vertical/category (e.g. SEBI or AIF).",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score of the extraction (0.0 – 1.0).",
    )


class ExtractionResult(BaseModel):
    """Wrapper around a batch of extracted announcements."""

    announcements: list[Announcement] = Field(default_factory=list)
    source_strategy: str = Field(
        default="dom_llm",
        description="Strategy used: 'api', 'dom_llm', or 'vision_llm'.",
    )
    raw_count: int = Field(
        default=0,
        description="Number of items before validation / dedup.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if extraction partially failed.",
    )


class AnnouncementList(BaseModel):
    """Model used for structured LLM output parsing."""

    announcements: list[Announcement] = Field(
        ...,
        description="List of extracted SEBI announcements with title and issue_date.",
    )
