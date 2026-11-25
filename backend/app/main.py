"""
FastAPI application for Bluebook Citation Generator.
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.gzip import GZipMiddleware

from . import limits, watchdog
from .asgi import BodyLimit, BootIdHeader, JsonErrors
from .limits import (
    MAX_CITATIONS_RETURNED,
    MAX_CLAIMS_RETURNED,
    MAX_TEXT_CHARS,
    MAX_UPLOAD_BYTES,
    too_long_message,
)
from .models.citation import (
    AnalysisResponse,
    AnalysisStats,
    Citation,
    CitationStatus,
    CitationType,
    DocumentAnalysis,
    LookupSummary,
    UploadResponse,
)
from .services.bluebook_rules import BluebookFormatter
from .services.context_analyzer import DocumentContextAnalyzer
from .services.extractor import CitationExtractor, TooManyCitationsError
from .services.lookup_service import (
    CitationCompleter,
    LegalLookupService,
    parse_volume_reporter_page,
    tally_lookups,
)
from .services.parser import DocumentTooLongError, UnsupportedDocumentError
from .services.repair import CitationRepairer
from .services.sandbox import ParseBusyError, ParseUnavailableError, parse_isolated
from .services.source_finder import ClaimDetector, SourceFinder
from .services.spec_engine import STYLES

# Cap on lookups running at once for a single document. Enough to hide network
# latency, low enough to stay a polite client of free public APIs.
MAX_CONCURRENT_LOOKUPS = 6

# Hard ceiling on how long citation completion may take for one document.
# Extraction and formatting still return if this is hit; only the enrichment
# is dropped, so a slow upstream degrades the result instead of failing it.
COMPLETION_BUDGET_SECONDS = float(os.getenv("COMPLETION_BUDGET_SECONDS", "25"))

# How long one analysis may take in total, answered as a readable 504 when exceeded. The page
# waits 120 s, so this leaves room for the upload and download on a slow connection.
ANALYSIS_DEADLINE_SECONDS = float(os.getenv("ANALYSIS_DEADLINE_SECONDS", "90"))

# Analyses allowed to wait behind the one that is running. Beyond that the server says it is
# busy (503) instead of stacking up work that would all time out together.
MAX_QUEUED_ANALYSES = int(os.getenv("MAX_QUEUED_ANALYSES", "2"))

# Claims the legacy source-finding endpoints will search outside sources for, per request. They
# search one claim after another, so the number bounds the time as well as the load on the
# free public APIs.
MAX_CLAIMS_FOR_SOURCES = int(os.getenv("MAX_CLAIMS_FOR_SOURCES", "25"))

# How often a running request checks that the person is still there.
DISCONNECT_POLL_SECONDS = 0.5

# Cap on how many citations one document may send to outside lookups. Time alone
# is not a safe bound: with fast upstreams a very long document could still queue
# thousands of requests against free public APIs.
MAX_LOOKUPS_PER_DOCUMENT = int(os.getenv("MAX_LOOKUPS_PER_DOCUMENT", "200"))

# Uploads are unauthenticated, so the body is read with a hard cap rather than
# pulled into memory in full. Content-Type is client-supplied and cannot be
# trusted on its own; the parser validates the actual bytes. The limit itself
# lives in limits.py with every other one.

# The small endpoints take one citation, a case name or a search phrase. Nothing they accept needs
# more than this, and a limit in characters is the only bound that holds for every regular
# expression that will ever read these strings: a 3 KB string of spaces once held the event loop
# for 45 seconds here, inside a 1 MB body limit.
MAX_FIELD_CHARS = int(os.getenv("MAX_FIELD_CHARS", "2000"))

# The repair endpoint takes one citation, not a document. The cap keeps it
# cheap and steers whole-document work to the upload path.
MAX_REPAIR_CHARS = int(os.getenv("MAX_REPAIR_CHARS", "2000"))
REPAIR_BUDGET_SECONDS = float(os.getenv("REPAIR_BUDGET_SECONDS", "20"))

# Browser origins allowed to call this API.
#
# An origin is scheme + host + port only. The path is NOT part of it, so a
# site served from https://example.com/some-project/ sends
# "Origin: https://example.com" and must be listed as exactly that.
#
# Set EXTRA_ALLOWED_ORIGINS (comma separated) to add more without a deploy.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://delschlangen.github.io",
    "https://delschlangen.com",
    "https://www.delschlangen.com",
]
ALLOWED_ORIGINS += [
    origin.strip()
    for origin in os.getenv("EXTRA_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# Global services
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


# --- running CPU-bound work without freezing the server --------------------------------------
#
# The analysis is CPU work (about 2 s per million characters). Run on the event loop it blocks
# every other request, /health included, for the whole time: measured at 7 s twice for a
# 1,000-page document. It runs in a worker thread instead, one job at a time so that two large
# documents do not fight over the interpreter lock.
#
# A thread cannot be killed. If a job outlives the request's deadline the page is answered, but
# the lock is held until the thread really finishes, so a second job is not started on top of it.

_cpu_gate_state: dict = {}
_active_analyses = 0


def _cpu_gate() -> asyncio.Semaphore:
    """One semaphore per running event loop (asyncio primitives are tied to the loop that
    first waits on them, and the tests create a new loop for each client)."""
    loop = asyncio.get_running_loop()
    if _cpu_gate_state.get("loop") is not loop:
        _cpu_gate_state["loop"] = loop
        _cpu_gate_state["gate"] = asyncio.Semaphore(1)
    return _cpu_gate_state["gate"]


async def _cpu(fn, *args):
    """Run CPU-bound `fn` in a thread, one at a time, holding the slot until it truly ends."""
    gate = _cpu_gate()
    await gate.acquire()
    watchdog.cpu_job_started()
    try:
        future = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    except BaseException:
        watchdog.cpu_job_finished()
        gate.release()
        raise

    def finished(done: asyncio.Future) -> None:
        watchdog.cpu_job_finished()
        gate.release()
        if not done.cancelled():
            done.exception()  # mark retrieved: nobody may be waiting if the request timed out

    future.add_done_callback(finished)
    return await asyncio.shield(future)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the lookup service on startup and close it cleanly on shutdown.

    Only runs on hosts that dispatch lifespan events. The lazy accessor above
    covers the hosts that do not.
    """
    get_lookup_service()
    guard = asyncio.create_task(watchdog.run())
    yield
    guard.cancel()
    await asyncio.gather(guard, return_exceptions=True)
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

log = logging.getLogger("bluebook")


# Identifies this process. A page that saw one boot_id and then, after a failed request, a
# different one knows the server restarted in between (a crash or an out-of-memory kill) and can
# say so, instead of guessing at "could not reach the server". It is on every response
# (X-Boot-Id) as well as in /health, so the id the page remembers is the one from just before a
# request that failed.
BOOT_ID = uuid.uuid4().hex[:12]
STARTED_AT = time.time()

# Each add_middleware wraps everything added before it, so the last one is the outermost. The
# order matters: errors and the body limit answer INSIDE CORS, so the page can read them (a
# browser hides a response that has no Access-Control-Allow-Origin, and the page could only say
# "could not reach the server" for what is really a 413 or a bug). See asgi.py for why these
# are written as plain ASGI middleware.
app.add_middleware(BodyLimit)
app.add_middleware(JsonErrors)
app.add_middleware(BootIdHeader, boot_id=BOOT_ID)

# The analysis of a long document is a large block of repetitive JSON, and the document text
# comes back with the upload; both compress about ten to one, which matters on a phone.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # No cookies or auth headers are used, and allow_credentials=True forbids
    # ever widening the origin list to a wildcard. Off is both safer and
    # accurate about what this API does.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    # Without this a script cannot read these two headers off a cross-origin response.
    expose_headers=["X-Boot-Id", "Retry-After"],
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
        "boot_id": BOOT_ID,
        "uptime_s": round(time.time() - STARTED_AT),
        "limits": limits.as_dict(),
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
async def upload_document(request: Request, file: UploadFile = File(...)):
    """Upload a legal document for citation analysis.

    The format is detected from the file's bytes. The Content-Type the browser
    reports is deliberately ignored: phones send an empty or generic type for
    Word and PDF files from iCloud or Google Drive, and rejecting on it turned
    a working upload into a failure the user could not diagnose.
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        # The file is read in a short-lived child process (services/sandbox.py), not in
        # this one: a hostile or merely unlucky PDF can abort native code or hold the
        # interpreter lock in a regular expression, and neither a thread nor a deadline can
        # stop that. A child can be killed, and the server only waits for it.
        #
        # A person who gives up (closes the tab, locks the phone) must not keep a child, and a
        # place in the line of uploads, for up to 35 seconds: _bounded drops the work, and
        # parse_isolated kills its child when it is cancelled.
        parsed = await _bounded(
            request, parse_isolated(content, file.filename, max_text_chars=MAX_TEXT_CHARS)
        )
    except _ClientGone:
        return Response(status_code=499)  # nobody is listening; this is only for the log
    except ParseBusyError as e:
        # Not a problem with the file, and not 415: say the server is busy and when to retry.
        raise HTTPException(
            status_code=503, detail=str(e), headers={"Retry-After": str(e.retry_after)}
        ) from e
    except ParseUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail="The server could not start its document reader. Please try again in a minute.",
            headers={"Retry-After": "30"},
        ) from e
    except DocumentTooLongError as e:
        # 413, not 415: the file is a kind we read, it is just too long. The message
        # states the limit and what to do.
        raise HTTPException(status_code=413, detail=str(e)) from e
    except UnsupportedDocumentError as e:
        # The message already says what to do about it.
        raise HTTPException(status_code=415, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to parse document: {e}"
        ) from e

    document_text = parsed.text
    if not document_text or not document_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted. If this is a scanned PDF it needs OCR first.",
        )

    # The byte limit does not bound the work (a small file can expand to a lot of text), so the
    # text itself is limited, whatever the format. PDFs were already stopped by the reader.
    if len(document_text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail=too_long_message(len(document_text), MAX_TEXT_CHARS))

    doc_id = str(uuid.uuid4())

    analyzer = DocumentContextAnalyzer()
    structure = await asyncio.to_thread(analyzer.analyze_document_structure, document_text)

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
        format=parsed.format,
        footnote_count=parsed.footnote_count,
        endnote_count=parsed.endnote_count,
        warnings=parsed.warnings,
    )


async def _complete_citations(citations):
    """Enrich incomplete citations concurrently, under a total time budget.

    Returns (citations, LookupSummary).

    The lookups overlap and the whole phase is bounded, so a slow upstream
    degrades the response instead of failing it. When the budget runs out, every
    lookup that had already finished is KEPT and only the unfinished ones are
    dropped. (This used to discard all of them, so the longer the document, the
    more likely it was to get no enrichment at all.) The summary says how many
    were skipped so the page can say so rather than imply it looked everything up.
    """
    # Engine-recognised kinds (reports, rules, regulations, legislative materials...) are
    # never sent to an outside search. No free source can verify a record for them, and
    # searching a case database for a Federal Register cite can only return noise.
    eligible = [
        c for c in citations
        if c.status.value in ("incomplete", "needs_verification") and not c.kind
    ]
    # Bound the number of tasks as well as the time, so a huge document cannot queue
    # thousands of requests against free public APIs.
    to_look_up = eligible[:MAX_LOOKUPS_PER_DOCUMENT]

    finished: dict[int, Citation] = {}
    matched = 0
    failed = 0
    budget_exhausted = False

    if to_look_up:
        completer = CitationCompleter(get_lookup_service())
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)

        async def complete_one(citation):
            nonlocal matched, failed
            async with semaphore:
                with tally_lookups() as tally:
                    try:
                        done = await completer.complete_citation(citation)
                    except Exception:
                        # A failed enrichment must not fail the document. The
                        # citation is still returned exactly as it was found.
                        finished[id(citation)] = citation
                        failed += 1
                        return
                finished[id(citation)] = done
                results = getattr(done, "lookup_results", None)
                if results and results.get("found"):
                    matched += 1
                elif tally.unreachable:
                    # Every request made for this citation failed, so "not found" would be
                    # false: the sources were never asked.
                    failed += 1

        tasks = [asyncio.create_task(complete_one(c)) for c in to_look_up]
        try:
            _, pending = await asyncio.wait(tasks, timeout=COMPLETION_BUDGET_SECONDS)
            if pending:
                budget_exhausted = True
        finally:
            # On the time budget, and equally when the request is abandoned or passes its
            # deadline while waiting here: nothing may keep running in the background. (asyncio.wait
            # does not cancel what it waits for when the waiter itself is cancelled, so a 504
            # used to leave up to 200 outside requests running and feeding the semaphore.)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def finalize() -> list:
        done = []
        for citation in citations:
            citation = finished.get(id(citation), citation)
            citation.suggested_correction = formatter.format_citation(citation)
            done.append(citation)
        return done

    completed = await _cpu(finalize)

    summary = LookupSummary(
        eligible=len(eligible),
        completed=len(finished),
        skipped=len(eligible) - len(finished),
        budget_exhausted=budget_exhausted,
        matched=matched,
        failed=failed,
    )
    return completed, summary


async def _extract(text: str) -> list[Citation]:
    """Find the citations, or refuse a text with more than one analysis will build."""
    try:
        return await _cpu(extractor.extract_all, text)
    except TooManyCitationsError as e:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This document has {e}, which is more than one analysis can handle. "
                "Split it at a chapter or section boundary and check the parts one at a time."
            ),
        ) from e


async def _analyze(document_id: str, text: str, filename: str) -> AnalysisResponse:
    """The whole analysis. Its CPU stages run in a worker thread; the lookups stay on the loop."""
    citations = await _extract(text)

    completed_citations, lookup_summary = await _complete_citations(citations)

    def analyse_the_whole_document():
        short_forms = DocumentContextAnalyzer().analyze_citation_sequence(completed_citations)
        positions = [(c.position_start, c.position_end) for c in completed_citations]
        return short_forms, ClaimDetector().detect_unsourced_claims(text, positions)

    short_form_suggestions, unsourced = await _cpu(analyse_the_whole_document)

    # Everything above is computed over the whole document, so the totals are true. What is
    # SENT is capped: a phone cannot usefully render thousands of cards (4,000 citations took
    # 3.9 s to first paint and 8,000 claims blocked a tap for 10 s), and the payload grows with
    # them. The page is told both numbers so it can say "showing 2,000 of 2,450".
    shown_citations = completed_citations[:MAX_CITATIONS_RETURNED]
    shown_ids = {c.id for c in shown_citations}
    short_form_suggestions = [
        s for s in short_form_suggestions if s.get("citation_id") in shown_ids
    ]
    # Keep the most likely claims, then put them back in document order.
    shown_claims = sorted(
        sorted(unsourced, key=lambda c: -c.confidence)[:MAX_CLAIMS_RETURNED],
        key=lambda c: c.position_start,
    )

    stats = AnalysisStats(
        total_citations=len(completed_citations),
        complete=sum(1 for c in completed_citations if c.status.value == "complete"),
        incomplete=sum(1 for c in completed_citations if c.status.value == "incomplete"),
        needs_verification=sum(1 for c in completed_citations if c.status.value == "needs_verification"),
        unsourced_claims=len(unsourced),
        citations_shown=len(shown_citations),
        claims_shown=len(shown_claims),
    )

    analysis = DocumentAnalysis(
        document_id=document_id,
        filename=filename,
        total_footnotes=max((c.footnote_number or 0) for c in completed_citations) if completed_citations else 0,
        citations=shown_citations,
        unsourced_claims=shown_claims,
    )

    return AnalysisResponse(
        analysis=analysis,
        short_form_suggestions=short_form_suggestions,
        stats=stats,
        lookup=lookup_summary,
    )


_BUSY_DETAIL = "The server is busy analyzing other documents. Please try again in a minute."


@asynccontextmanager
async def _admitted():
    """Count a request in, or refuse it as busy.

    One analysis runs at a time and a few may wait. Past that the work would all time out
    together, so say the server is busy while a retry can still succeed."""
    global _active_analyses
    if _active_analyses >= 1 + MAX_QUEUED_ANALYSES:
        raise HTTPException(status_code=503, detail=_BUSY_DETAIL, headers={"Retry-After": "30"})
    _active_analyses += 1
    try:
        yield
    finally:
        _active_analyses -= 1


class _ClientGone(Exception):
    """The person closed the page, locked the phone or pressed reset while their request ran."""


async def _until_client_disconnects(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(DISCONNECT_POLL_SECONDS)


async def _bounded(request: Request, work):
    """Await `work` until it finishes, the deadline passes (504), or the client is gone.

    A client that has gone cannot be answered, so what it asked for is dropped: its lookups are
    cancelled and the stages not yet started are never begun. (A stage already running in a
    thread cannot be stopped, but it was the only thing left to wait for. Before this, every
    abandoned request ran to the end and kept its place in the queue, so a phone that resets
    twice was told the server was busy with other people's documents.)"""
    job = asyncio.ensure_future(work)
    watcher = asyncio.ensure_future(_until_client_disconnects(request))
    try:
        done, _ = await asyncio.wait(
            {job, watcher}, timeout=ANALYSIS_DEADLINE_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
        if job in done:
            return job.result()
        if watcher in done:
            raise _ClientGone
        raise HTTPException(
            status_code=504,
            detail=(
                "Analyzing this document took longer than the "
                f"{ANALYSIS_DEADLINE_SECONDS:g}-second limit. Try a shorter document, or split "
                "it at a chapter or section boundary and check the parts one at a time."
            ),
        )
    finally:
        job.cancel()
        watcher.cancel()
        await asyncio.gather(job, watcher, return_exceptions=True)


def _require_text_within_limit(text: str) -> None:
    # The same limit the upload enforces. These endpoints are public and take the text directly,
    # so they cannot rely on the upload having checked.
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail=too_long_message(len(text), MAX_TEXT_CHARS))


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_citations(
    request: Request,
    document_id: str = Body(...),
    text: str = Body(...),
    filename: str = Body(default="document"),
):
    """Extract and analyze all citations in the document."""
    _require_text_within_limit(text)
    async with _admitted():
        try:
            return await _bounded(request, _analyze(document_id, text, filename))
        except _ClientGone:
            return Response(status_code=499)  # nobody is listening; this is only for the log


def _too_long(name: str) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=(
            f"'{name}' is longer than the {MAX_FIELD_CHARS:,} characters one citation can need. "
            "For a whole document, use the upload tab."
        ),
    )


def _require_short(name: str, value) -> None:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        raise _too_long(name)


def _require_short_fields(data: dict) -> None:
    """Refuse a citation object any of whose text fields is longer than a citation can be.

    The formatter and the lookups read these fields with regular expressions on the event loop."""
    if not isinstance(data, dict):
        return
    for name, value in data.items():
        if isinstance(value, str):
            _require_short(str(name)[:40], value)
        elif isinstance(value, list | tuple):
            if len(value) > 50:
                raise _too_long(str(name)[:40])
            for item in value:
                _require_short(str(name)[:40], item)


@app.post("/api/format")
async def format_citation(citation_data: dict):
    """Format a single citation according to Bluebook rules."""
    _require_short_fields(citation_data)
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
    _require_short_fields(citation_data)
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
    _require_short("parties", parties)
    _require_short("citation", citation)
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
        parsed = parse_volume_reporter_page(citation)
        if parsed:
            search_citation.volume, search_citation.reporter, search_citation.page = parsed

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
    _require_short("text", text)
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
    request: Request,
    text: str = Body(...),
    max_suggestions: int = Body(default=3),
):
    """
    Find potential sources for unsourced claims in text.

    Analyzes the text for claims that need citations and
    searches legal databases for relevant sources.
    """
    _require_text_within_limit(text)

    async def work():
        source_finder = SourceFinder(get_lookup_service())

        # First detect claims (CPU work: off the event loop, one job at a time)
        claims = await _cpu(ClaimDetector().detect_unsourced_claims, text, [])

        # Find sources for each claim, a bounded number of them
        enriched_claims = await source_finder.find_sources_for_claims(
            claims, max_suggestions, max_claims=MAX_CLAIMS_FOR_SOURCES
        )
        return {
            "total_claims": len(claims),
            "claims_searched": len(enriched_claims),
            "claims_with_sources": sum(1 for c in enriched_claims if c.get("suggested_sources")),
            "claims": enriched_claims,
        }

    async with _admitted():
        try:
            return await _bounded(request, work())
        except _ClientGone:
            return Response(status_code=499)


@app.post("/api/analyze-comprehensive")
async def analyze_comprehensive(
    request: Request,
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

    The page does not use this; /api/analyze is the endpoint it calls. It stays for callers that
    do, under the same limits as /api/analyze (text size, one analysis at a time with a short
    queue, a deadline, and a bounded number of outside lookups).
    """
    _require_text_within_limit(text)

    async def work():
        citations = await _extract(text)

        # Complete incomplete citations, concurrently and under the lookup budget; this also
        # fills in each citation's suggested correction.
        completed_citations, lookup_summary = await _complete_citations(citations)

        def analyse():
            context_analyzer = DocumentContextAnalyzer()
            return (
                context_analyzer.analyze_citation_sequence(completed_citations),
                context_analyzer.get_citation_summary(completed_citations),
            )

        short_form_suggestions, citation_summary = await _cpu(analyse)

        unsourced_analysis = None
        if find_sources:
            source_finder = SourceFinder(get_lookup_service())
            citation_positions = [(c.position_start, c.position_end) for c in completed_citations]
            unsourced_analysis = await source_finder.analyze_document_for_sources(
                text, citation_positions, max_claims=MAX_CLAIMS_FOR_SOURCES
            )

        stats = AnalysisStats(
            total_citations=len(completed_citations),
            complete=sum(1 for c in completed_citations if c.status.value == "complete"),
            incomplete=sum(1 for c in completed_citations if c.status.value == "incomplete"),
            needs_verification=sum(
                1 for c in completed_citations if c.status.value == "needs_verification"
            ),
            unsourced_claims=unsourced_analysis["total_claims"] if unsourced_analysis else 0,
        )

        analysis = DocumentAnalysis(
            document_id=document_id,
            filename=filename,
            total_footnotes=max((c.footnote_number or 0) for c in completed_citations)
            if completed_citations
            else 0,
            citations=completed_citations,
            unsourced_claims=[],  # Simplified, full data in unsourced_analysis
        )

        return {
            "analysis": analysis.model_dump(),
            "short_form_suggestions": short_form_suggestions,
            "stats": stats.model_dump(),
            "citation_summary": citation_summary,
            "unsourced_analysis": unsourced_analysis,
            "lookup": lookup_summary.model_dump(),
        }

    async with _admitted():
        try:
            return await _bounded(request, work())
        except _ClientGone:
            return Response(status_code=499)


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
    _require_short("query", query)
    results = await get_lookup_service().search_by_text(query, search_type)
    return results


@app.post("/api/repair")
async def repair_citation(
    text: str = Body(..., embed=True),
    style: str = Body(default="law_review", embed=True),
):
    """Diagnose and, where possible, complete a single pasted citation.

    Returns one of four statuses:

    - `resolved`    complete and formatted, with a link to verify it
    - `ambiguous`   candidates found, none confident enough to apply
    - `incomplete`  the gaps are identified but no record was found
    - `unparseable` not recognizable as a citation

    `style` is `law_review` (footnotes: authors and titles in capitals) or
    `practitioner` (court documents: ordinary type, italic titles).

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

    if style not in STYLES:
        raise HTTPException(
            status_code=422,
            detail=f"style must be one of: {', '.join(STYLES)}.",
        )

    repairer = CitationRepairer(get_lookup_service(), extractor, formatter)
    try:
        result = await asyncio.wait_for(
            repairer.repair(text, style), timeout=REPAIR_BUDGET_SECONDS
        )
    except TimeoutError:
        # Fall back to the offline diagnosis, which is still useful.
        result = await CitationRepairer(
            _OfflineLookup(), extractor, formatter
        ).repair(text, style)
        result.notes.append(
            "The lookup timed out, so only the parse is shown."
        )
    return result.as_dict()


class _OfflineLookup:
    """Stand-in used when a lookup exceeds its budget, so the endpoint can
    still return the parse and the list of missing fields."""

    async def smart_complete(self, citation):
        # "unavailable" tells the repairer to say nothing about records: the endpoint adds
        # its own note that the lookup timed out.
        return {"found": False, "data": None, "suggestions": [], "unavailable": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
