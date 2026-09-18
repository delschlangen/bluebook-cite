"""
Pydantic models for citations and document analysis.
"""

import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class CitationType(str, Enum):
    CASE = "case"
    STATUTE = "statute"
    REGULATION = "regulation"
    LAW_REVIEW = "law_review"
    BOOK = "book"
    NEWSPAPER = "newspaper"
    WEBSITE = "website"
    LEGISLATIVE = "legislative"
    TREATY = "treaty"
    CONSTITUTION = "constitution"
    OTHER = "other"

class CitationStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    MALFORMED = "malformed"
    NEEDS_VERIFICATION = "needs_verification"

class Citation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: CitationType
    status: CitationStatus
    raw_text: str
    position_start: int
    position_end: int
    footnote_number: int | None = None

    # Case citation components
    parties: list[str] | None = None
    volume: str | None = None
    reporter: str | None = None
    page: str | None = None
    pincite: str | None = None
    court: str | None = None
    year: int | None = None
    parallel_citations: list[str] | None = None

    # Article/book components
    author: str | None = None
    title: str | None = None
    journal: str | None = None
    publisher: str | None = None
    edition: str | None = None

    # Statute/regulation components
    title_number: str | None = None
    code: str | None = None
    section: str | None = None
    subsection: str | None = None

    # URL components
    url: str | None = None
    access_date: str | None = None

    # Processing metadata
    suggested_correction: str | None = None
    confidence_score: float = 0.0
    lookup_results: dict | None = None

    # Short form tracking
    is_short_form: bool = False
    references_citation_id: str | None = None
    short_form_type: Literal["id", "supra", "hereinafter", "short_case"] | None = None

class CitationContext(BaseModel):
    """Tracks citation usage for short form decisions."""
    citation_id: str
    first_occurrence_footnote: int
    full_citation: str
    short_forms_used: list[str] = []
    hereinafter_name: str | None = None
    last_used_footnote: int
    times_cited: int = 1

class UnsourcedClaim(BaseModel):
    """Represents a claim that may need a citation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    position_start: int
    position_end: int
    claim_type: Literal["factual", "legal", "statistical", "quotation"]
    confidence: float
    suggested_search_terms: list[str] = []
    suggested_sources: list[dict] = []

class DocumentAnalysis(BaseModel):
    """Complete analysis of a document's citations."""
    document_id: str
    filename: str
    total_footnotes: int = 0
    citations: list[Citation] = []
    citation_contexts: list[CitationContext] = []
    unsourced_claims: list[UnsourcedClaim] = []
    issues_found: list[dict] = []
    corrected_text: str | None = None

class UploadResponse(BaseModel):
    """Response from document upload."""
    document_id: str
    filename: str
    word_count: int
    citation_style: str
    has_footnotes: bool
    text_preview: str
    full_text: str

class AnalysisStats(BaseModel):
    """Statistics about citation analysis."""
    total_citations: int
    complete: int
    incomplete: int
    needs_verification: int
    unsourced_claims: int

class AnalysisResponse(BaseModel):
    """Response from citation analysis."""
    analysis: DocumentAnalysis
    short_form_suggestions: list[dict]
    stats: AnalysisStats
