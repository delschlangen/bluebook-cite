"""
Pydantic models for citations and document analysis.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from enum import Enum
import uuid

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
    footnote_number: Optional[int] = None
    
    # Case citation components
    parties: Optional[List[str]] = None
    volume: Optional[str] = None
    reporter: Optional[str] = None
    page: Optional[str] = None
    pincite: Optional[str] = None
    court: Optional[str] = None
    year: Optional[int] = None
    parallel_citations: Optional[List[str]] = None
    
    # Article/book components
    author: Optional[str] = None
    title: Optional[str] = None
    journal: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[str] = None
    
    # Statute/regulation components
    title_number: Optional[str] = None
    code: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None
    
    # URL components
    url: Optional[str] = None
    access_date: Optional[str] = None
    
    # Processing metadata
    suggested_correction: Optional[str] = None
    confidence_score: float = 0.0
    lookup_results: Optional[dict] = None
    
    # Short form tracking
    is_short_form: bool = False
    references_citation_id: Optional[str] = None
    short_form_type: Optional[Literal["id", "supra", "hereinafter", "short_case"]] = None

class CitationContext(BaseModel):
    """Tracks citation usage for short form decisions."""
    citation_id: str
    first_occurrence_footnote: int
    full_citation: str
    short_forms_used: List[str] = []
    hereinafter_name: Optional[str] = None
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
    suggested_search_terms: List[str] = []
    suggested_sources: List[dict] = []

class DocumentAnalysis(BaseModel):
    """Complete analysis of a document's citations."""
    document_id: str
    filename: str
    total_footnotes: int = 0
    citations: List[Citation] = []
    citation_contexts: List[CitationContext] = []
    unsourced_claims: List[UnsourcedClaim] = []
    issues_found: List[dict] = []
    corrected_text: Optional[str] = None

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
    short_form_suggestions: List[dict]
    stats: AnalysisStats
