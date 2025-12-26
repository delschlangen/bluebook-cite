"""
FastAPI application for Bluebook Citation Generator.
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid

from .services.parser import DocumentParser
from .services.extractor import CitationExtractor
from .services.bluebook_rules import BluebookFormatter, ShortFormManager
from .services.context_analyzer import DocumentContextAnalyzer
from .services.lookup_service import LegalLookupService, CitationCompleter
from .services.source_finder import ClaimDetector
from .models.citation import (
    Citation, DocumentAnalysis, UploadResponse, 
    AnalysisResponse, AnalysisStats, CitationType
)

# Global services
parser = DocumentParser()
extractor = CitationExtractor()
formatter = BluebookFormatter()
lookup_service: LegalLookupService = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    global lookup_service
    lookup_service = LegalLookupService()
    yield
    await lookup_service.close()

app = FastAPI(
    title="Bluebook Citation Generator",
    description="Automated citation formatting per Bluebook 21st Edition",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Bluebook Citation Generator API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a legal document for citation analysis."""
    allowed_types = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "txt",
    }
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Supported: PDF, DOCX, TXT"
        )
    
    content = await file.read()
    
    try:
        document_text = parser.parse(content, file.content_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse document: {str(e)}")
    
    doc_id = str(uuid.uuid4())
    
    analyzer = DocumentContextAnalyzer()
    structure = analyzer.analyze_document_structure(document_text)
    
    preview_length = 500
    preview = document_text[:preview_length]
    if len(document_text) > preview_length:
        preview += "..."
    
    return UploadResponse(
        document_id=doc_id,
        filename=file.filename or "document",
        word_count=structure["estimated_word_count"],
        citation_style=structure["citation_style"],
        has_footnotes=structure["has_footnotes"],
        text_preview=preview,
        full_text=document_text,
    )


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_citations(
    document_id: str = Body(...),
    text: str = Body(...),
    filename: str = Body(default="document"),
):
    """Extract and analyze all citations in the document."""
    # Extract citations
    citations = extractor.extract_all(text)
    
    # Complete incomplete citations
    completer = CitationCompleter(lookup_service)
    completed_citations = []
    
    for citation in citations:
        if citation.status.value in ["incomplete", "needs_verification"]:
            citation = await completer.complete_citation(citation)
        
        # Generate formatted suggestion
        citation.suggested_correction = formatter.format_citation(citation)
        completed_citations.append(citation)
    
    # Analyze citation sequence for short forms
    context_analyzer = DocumentContextAnalyzer()
    short_form_suggestions = context_analyzer.analyze_citation_sequence(completed_citations)
    
    # Detect unsourced claims
    claim_detector = ClaimDetector()
    citation_positions = [(c.position_start, c.position_end) for c in completed_citations]
    unsourced = claim_detector.detect_unsourced_claims(text, citation_positions)
    
    # Calculate stats
    stats = AnalysisStats(
        total_citations=len(completed_citations),
        complete=sum(1 for c in completed_citations if c.status.value == "complete"),
        incomplete=sum(1 for c in completed_citations if c.status.value == "incomplete"),
        needs_verification=sum(1 for c in completed_citations if c.status.value == "needs_verification"),
        unsourced_claims=len(unsourced),
    )
    
    # Build analysis
    analysis = DocumentAnalysis(
        document_id=document_id,
        filename=filename,
        total_footnotes=max((c.footnote_number or 0) for c in completed_citations) if completed_citations else 0,
        citations=completed_citations,
        unsourced_claims=unsourced,
    )
    
    return AnalysisResponse(
        analysis=analysis,
        short_form_suggestions=short_form_suggestions,
        stats=stats,
    )


@app.post("/api/format")
async def format_citation(citation_data: dict):
    """Format a single citation according to Bluebook rules."""
    try:
        citation = Citation(**citation_data)
        formatted = formatter.format_citation(citation)
        
        return {
            "original": citation.raw_text,
            "formatted": formatted,
            "type": citation.type.value,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/lookup")
async def lookup_citation(citation_data: dict):
    """Look up a citation in legal databases."""
    try:
        citation = Citation(**citation_data)
        results = await lookup_service.lookup_citation(citation)
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/lookup/case")
async def lookup_case(
    parties: str = Body(default=None),
    citation: str = Body(default=None),
):
    """Look up a case by parties or citation string."""
    search_citation = Citation(
        type=CitationType.CASE,
        status="incomplete",
        raw_text=parties or citation or "",
        position_start=0,
        position_end=0,
    )
    
    if parties and " v. " in parties:
        parts = parties.split(" v. ")
        search_citation.parties = [p.strip() for p in parts]
    elif parties and " v " in parties:
        parts = parties.split(" v ")
        search_citation.parties = [p.strip() for p in parts]
    
    if citation:
        import re
        match = re.match(r"(\d+)\s+([A-Za-z.\s]+)\s+(\d+)", citation)
        if match:
            search_citation.volume = match.group(1)
            search_citation.reporter = match.group(2).strip()
            search_citation.page = match.group(3)
    
    results = await lookup_service.lookup_citation(search_citation)
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
