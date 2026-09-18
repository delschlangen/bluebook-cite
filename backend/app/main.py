"""
FastAPI application for Bluebook Citation Generator.
"""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .models.citation import (
    AnalysisResponse,
    AnalysisStats,
    Citation,
    CitationStatus,
    CitationType,
    DocumentAnalysis,
    UploadResponse,
)
from .services.bluebook_rules import BluebookFormatter
from .services.context_analyzer import DocumentContextAnalyzer
from .services.extractor import CitationExtractor
from .services.lookup_service import CitationCompleter, LegalLookupService
from .services.parser import DocumentParser
from .services.repair import CitationRepairer
from .services.source_finder import ClaimDetector, SourceFinder

# Cap on lookups running at once for a single document. Enough to hide network
# latency, low enough to stay a polite client of free public APIs.
MAX_CONCURRENT_LOOKUPS = 6

# Hard ceiling on how long citation completion may take for one document.
# Extraction and formatting still return if this is hit; only the enrichment
# is dropped, so a slow upstream degrades the result instead of failing it.
COMPLETION_BUDGET_SECONDS = float(os.getenv("COMPLETION_BUDGET_SECONDS", "25"))

# Uploads are unauthenticated, so the body is read with a hard cap rather than
# pulled into memory in full. Content-Type is client-supplied and cannot be
# trusted on its own; the parser validates the actual bytes.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024

# The repair endpoint takes one citation, not a document. The cap keeps it
# cheap and steers whole-document work to the upload path.
MAX_REPAIR_CHARS = int(os.getenv("MAX_REPAIR_CHARS", "2000"))
REPAIR_BUDGET_SECONDS = float(os.getenv("REPAIR_BUDGET_SECONDS", "20"))

# Global services
parser = DocumentParser()
extractor = CitationExtractor()
formatter = BluebookFormatter()
_lookup_service: LegalLookupService | None = None


def get_lookup_service() -> LegalLookupService:
    """Return the shared lookup service, creating it on first use.

    Creating this in the lifespan hook alone is not safe everywhere: some
    serverless runtimes do not run ASGI lifespan events, which would leave the
    service as None and fail every request that needs a lookup. Creating it
    lazily works under uvicorn and under a serverless runtime alike.
    """
    global _lookup_service
    if _lookup_service is None or _lookup_service.client is None:
        _lookup_service = LegalLookupService()
    return _lookup_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the lookup service on startup and close it cleanly on shutdown.

    Only runs on hosts that dispatch lifespan events. The lazy accessor above
    covers the hosts that do not.
    """
    get_lookup_service()
    yield
    global _lookup_service
    if _lookup_service is not None:
        await _lookup_service.close()
        _lookup_service = None

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
        "https://delschlangen.github.io",
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
    """Health check, and enough build detail to answer "which build is live?".

    When the frontend and backend deploy separately, a frontend calling an
    endpoint an older backend does not have is indistinguishable from the
    backend being down. Listing the routes makes that answerable without
    guessing.
    """
    return {
        "status": "healthy",
        "version": "1.0.0",
        "commit": (
            os.getenv("VERCEL_GIT_COMMIT_SHA")
            or os.getenv("RAILWAY_GIT_COMMIT_SHA")
            or "unknown"
        )[:7],
        "host": "vercel" if os.getenv("VERCEL") else (
            "railway" if os.getenv("RAILWAY_ENVIRONMENT") else "local"
        ),
        "endpoints": sorted(
            route.path for route in app.routes
            if getattr(route, "path", "").startswith("/api")
        ),
    }


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

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        # pdfplumber and python-docx are synchronous and CPU-bound. Calling
        # them directly would block the event loop for the whole parse and
        # stall every other in-flight request.
        document_text = await asyncio.to_thread(
            parser.parse, content, file.content_type
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to parse document: {e}"
        ) from e

    if not document_text or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted. If this is a scanned PDF it needs OCR first.",
        )

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


async def _complete_citations(citations):
    """Enrich incomplete citations concurrently, under a total time budget.

    Previously this ran one lookup at a time with a long per-call timeout, so a
    document with a handful of incomplete citations could outlive any browser's
    patience and surface as an opaque network failure. Now the lookups overlap,
    the whole phase is bounded, and exceeding the budget degrades the response
    instead of failing it.
    """
    needs_lookup = [
        c for c in citations
        if c.status.value in ("incomplete", "needs_verification")
    ]

    if needs_lookup:
        completer = CitationCompleter(get_lookup_service())
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)

        async def complete_one(citation):
            async with semaphore:
                try:
                    return await completer.complete_citation(citation)
                except Exception:
                    # A failed enrichment must not fail the document. The
                    # citation is still returned exactly as it was found.
                    return citation

        try:
            enriched = await asyncio.wait_for(
                asyncio.gather(
                    *(complete_one(c) for c in needs_lookup),
                    return_exceptions=True,
                ),
                timeout=COMPLETION_BUDGET_SECONDS,
            )
            replacements = {
                id(original): result
                for original, result in zip(needs_lookup, enriched, strict=True)
                if not isinstance(result, Exception) and result is not None
            }
        except TimeoutError:
            replacements = {}
    else:
        replacements = {}

    completed = []
    for citation in citations:
        citation = replacements.get(id(citation), citation)
        citation.suggested_correction = formatter.format_citation(citation)
        completed.append(citation)
    return completed


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_citations(
    document_id: str = Body(...),
    text: str = Body(...),
    filename: str = Body(default="document"),
):
    """Extract and analyze all citations in the document."""
    # Extract citations
    citations = extractor.extract_all(text)

    completed_citations = await _complete_citations(citations)

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
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/lookup")
async def lookup_citation(citation_data: dict):
    """Look up a citation in legal databases."""
    try:
        citation = Citation(**citation_data)
        results = await get_lookup_service().lookup_citation(citation)
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/lookup/case")
async def lookup_case(
    parties: str = Body(default=None),
    citation: str = Body(default=None),
):
    """Look up a case by parties or citation string."""
    search_citation = Citation(
        type=CitationType.CASE,
        status=CitationStatus.INCOMPLETE,
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

    results = await get_lookup_service().lookup_citation(search_citation)
    return results


@app.post("/api/complete-from-text")
async def complete_from_text(text: str = Body(..., embed=True)):
    """
    Complete a citation from minimal text input.

    Accepts:
    - Case names (e.g., "Roe v. Wade")
    - Partial citations (e.g., "Brown v Board")
    - URLs (e.g., "https://example.com/article")
    - Article titles or author names
    - Statute references (e.g., "42 USC 1983")

    Returns a completed citation with all available information.
    """
    completer = CitationCompleter(get_lookup_service())
    citation, results = await completer.complete_from_text(text)

    # Format the completed citation
    formatted = formatter.format_citation(citation)

    return {
        "input": text,
        "citation": citation.model_dump(),
        "formatted": formatted,
        "lookup_results": results,
        "confidence": citation.confidence_score,
        "status": citation.status.value,
    }


@app.post("/api/find-sources")
async def find_sources(
    text: str = Body(...),
    max_suggestions: int = Body(default=3),
):
    """
    Find potential sources for unsourced claims in text.

    Analyzes the text for claims that need citations and
    searches legal databases for relevant sources.
    """
    source_finder = SourceFinder(get_lookup_service())

    # First detect claims
    claim_detector = ClaimDetector()
    claims = claim_detector.detect_unsourced_claims(text, [])

    # Find sources for each claim
    enriched_claims = await source_finder.find_sources_for_claims(claims, max_suggestions)

    return {
        "total_claims": len(claims),
        "claims_with_sources": sum(1 for c in enriched_claims if c.get("suggested_sources")),
        "claims": enriched_claims,
    }


@app.post("/api/analyze-comprehensive")
async def analyze_comprehensive(
    document_id: str = Body(...),
    text: str = Body(...),
    filename: str = Body(default="document"),
    find_sources: bool = Body(default=True),
):
    """
    Comprehensive document analysis with all features.

    Includes:
    - Citation extraction and completion
    - Short form suggestions
    - Unsourced claim detection with source suggestions
    - Citation summary statistics
    """
    # Extract citations
    citations = extractor.extract_all(text)

    # Complete incomplete citations using smart lookup
    completer = CitationCompleter(get_lookup_service())
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

    # Get citation summary
    citation_summary = context_analyzer.get_citation_summary(completed_citations)

    # Detect and find sources for unsourced claims
    unsourced_analysis = None
    if find_sources:
        source_finder = SourceFinder(get_lookup_service())
        citation_positions = [(c.position_start, c.position_end) for c in completed_citations]
        unsourced_analysis = await source_finder.analyze_document_for_sources(
            text, citation_positions
        )

    # Calculate stats
    stats = AnalysisStats(
        total_citations=len(completed_citations),
        complete=sum(1 for c in completed_citations if c.status.value == "complete"),
        incomplete=sum(1 for c in completed_citations if c.status.value == "incomplete"),
        needs_verification=sum(1 for c in completed_citations if c.status.value == "needs_verification"),
        unsourced_claims=unsourced_analysis["total_claims"] if unsourced_analysis else 0,
    )

    # Build analysis
    analysis = DocumentAnalysis(
        document_id=document_id,
        filename=filename,
        total_footnotes=max((c.footnote_number or 0) for c in completed_citations) if completed_citations else 0,
        citations=completed_citations,
        unsourced_claims=[],  # Simplified, full data in unsourced_analysis
    )

    return {
        "analysis": analysis.model_dump(),
        "short_form_suggestions": short_form_suggestions,
        "stats": stats.model_dump(),
        "citation_summary": citation_summary,
        "unsourced_analysis": unsourced_analysis,
    }


@app.post("/api/search")
async def search_citations(
    query: str = Body(...),
    search_type: str = Body(default="case"),
):
    """
    Search legal databases for citations.

    search_type can be:
    - "case": Search for case law
    - "article": Search for law review articles
    - "statute": Parse and lookup statutes
    """
    results = await get_lookup_service().search_by_text(query, search_type)
    return results


@app.post("/api/repair")
async def repair_citation(text: str = Body(..., embed=True)):
    """Diagnose and, where possible, complete a single pasted citation.

    Returns one of four statuses:

    - `resolved`    complete and formatted, with a link to verify it
    - `ambiguous`   candidates found, none confident enough to apply
    - `incomplete`  the gaps are identified but no record was found
    - `unparseable` not recognizable as a citation

    A formatted citation is only ever returned when it came from the user's
    own complete input or from a matched record carrying a verification URL.
    """
    if len(text or "") > MAX_REPAIR_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Paste up to {MAX_REPAIR_CHARS} characters. "
                "For a whole document, use the upload tab."
            ),
        )

    repairer = CitationRepairer(get_lookup_service(), extractor, formatter)
    try:
        result = await asyncio.wait_for(
            repairer.repair(text), timeout=REPAIR_BUDGET_SECONDS
        )
    except TimeoutError:
        # Fall back to the offline diagnosis, which is still useful.
        result = await CitationRepairer(
            _OfflineLookup(), extractor, formatter
        ).repair(text)
        result.notes.append(
            "The lookup timed out, so only the parse is shown."
        )
    return result.as_dict()


class _OfflineLookup:
    """Stand-in used when a lookup exceeds its budget, so the endpoint can
    still return the parse and the list of missing fields."""

    async def smart_complete(self, citation):
        return {"found": False, "data": None, "suggestions": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
