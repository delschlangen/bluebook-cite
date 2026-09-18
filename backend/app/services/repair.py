"""Single-citation repair.

The user pastes whatever they have. This module answers three questions in
order: what did you give me, what is missing from it, and can I find the rest
in a source I can link you to.

The guarantee, and the reason this module exists separately from the document
pipeline: a citation is only ever reported as resolved when it is either
already complete, or completed from a record with a verification URL. There is
no path here that returns a formatted citation the user cannot check.
"""

from dataclasses import dataclass, field
from typing import Any

from ..models.citation import Citation, CitationStatus, CitationType
from ..services.bluebook_rules import BluebookFormatter
from ..services.extractor import CitationExtractor
from ..services.lookup_service import (
    CONFIDENT_MATCH_THRESHOLD,
    LegalLookupService,
)

# Fields the Bluebook requires before a citation of each type is complete.
REQUIRED_FIELDS: dict[CitationType, tuple[str, ...]] = {
    CitationType.CASE: ("parties", "volume", "reporter", "page", "year"),
    CitationType.STATUTE: ("title_number", "code", "section"),
    CitationType.REGULATION: ("title_number", "code", "section"),
    CitationType.LAW_REVIEW: ("author", "title", "volume", "journal", "page", "year"),
    CitationType.BOOK: ("author", "title", "year"),
    CitationType.WEBSITE: ("title", "url"),
}

# Human-readable names, so the UI can say "missing the reporter" rather than
# leaking a field name at the user.
FIELD_LABELS: dict[str, str] = {
    "parties": "party names",
    "volume": "volume number",
    "reporter": "reporter",
    "page": "first page",
    "year": "year",
    "title_number": "title number",
    "code": "code",
    "section": "section",
    "author": "author",
    "title": "title",
    "journal": "journal",
    "url": "URL",
}

# Status values, in the order the UI should treat them.
RESOLVED = "resolved"        # complete and formatted, verifiable
AMBIGUOUS = "ambiguous"      # plausible candidates, none confident enough
INCOMPLETE = "incomplete"    # we know what is missing, we cannot find it
UNPARSEABLE = "unparseable"  # not recognizable as a citation


@dataclass
class RepairResult:
    input: str
    status: str
    citation_type: str | None = None
    parsed: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    missing_labels: list[str] = field(default_factory=list)
    formatted: str | None = None
    confidence: float | None = None
    source: str | None = None
    verify_url: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "status": self.status,
            "citation_type": self.citation_type,
            "parsed": self.parsed,
            "missing": self.missing,
            "missing_labels": self.missing_labels,
            "formatted": self.formatted,
            "confidence": self.confidence,
            "source": self.source,
            "verify_url": self.verify_url,
            "candidates": self.candidates,
            "notes": self.notes,
        }


def _present(citation: Citation, field_name: str) -> bool:
    value = getattr(citation, field_name, None)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        # A case needs both sides, not just one.
        return len(value) >= 2 if field_name == "parties" else bool(value)
    return True


def missing_fields(citation: Citation) -> list[str]:
    required = REQUIRED_FIELDS.get(citation.type, ())
    return [f for f in required if not _present(citation, f)]


def _parsed_fields(citation: Citation) -> dict[str, Any]:
    keys = (
        "parties", "volume", "reporter", "page", "pincite", "court", "year",
        "title_number", "code", "section", "subsection",
        "author", "title", "journal", "edition", "url",
    )
    out = {}
    for key in keys:
        value = getattr(citation, key, None)
        if value not in (None, "", []):
            out[key] = value
    return out


def _candidate_url(raw: dict[str, Any]) -> str | None:
    for key in ("absolute_url", "url", "verify_url"):
        value = raw.get(key)
        if value and isinstance(value, str) and value.startswith("http"):
            return value
    return None


class CitationRepairer:
    """Diagnose and, where possible, complete a single pasted citation."""

    def __init__(
        self,
        lookup: LegalLookupService,
        extractor: CitationExtractor | None = None,
        formatter: BluebookFormatter | None = None,
    ):
        self.lookup = lookup
        self.extractor = extractor or CitationExtractor()
        self.formatter = formatter or BluebookFormatter()

    async def repair(self, text: str) -> RepairResult:
        text = (text or "").strip()
        if not text:
            return RepairResult(
                input=text,
                status=UNPARSEABLE,
                notes=["Nothing to repair. Paste a citation or part of one."],
            )

        citations = self.extractor.extract_all(text)
        if not citations:
            return RepairResult(
                input=text,
                status=UNPARSEABLE,
                notes=[
                    "This does not look like a citation yet. A case needs at "
                    "least two party names separated by \" v. \"."
                ],
            )

        # Longest match wins: it is the one that accounts for most of the input.
        citation = max(citations, key=lambda c: c.position_end - c.position_start)
        gaps = missing_fields(citation)

        result = RepairResult(
            input=text,
            status=INCOMPLETE,
            citation_type=citation.type.value,
            parsed=_parsed_fields(citation),
            missing=gaps,
            missing_labels=[FIELD_LABELS.get(g, g) for g in gaps],
        )

        # Already complete. Format it and say so; no lookup is needed, and the
        # user's own input is the provenance.
        if not gaps:
            result.status = RESOLVED
            result.formatted = self.formatter.format_citation(citation)
            result.confidence = 1.0
            result.source = "your input"
            result.notes.append(
                "This citation was already complete. Formatting applied."
            )
            return result

        return await self._try_to_fill(citation, result)

    async def _try_to_fill(
        self, citation: Citation, result: RepairResult
    ) -> RepairResult:
        try:
            lookup = await self.lookup.smart_complete(citation)
        except Exception:
            result.notes.append(
                "The lookup service could not be reached, so only the parse "
                "is shown. The missing fields above are still accurate."
            )
            return result

        raw_candidates = lookup.get("suggestions") or []
        for raw in raw_candidates[:5]:
            url = _candidate_url(raw)
            if not url:
                # No link means the user cannot check it, so it is not offered.
                continue
            result.candidates.append(
                {
                    "label": raw.get("case_name") or raw.get("title") or "Untitled",
                    "court": raw.get("court") or None,
                    "date": raw.get("date_filed") or raw.get("year") or None,
                    "citation": raw.get("citation") or None,
                    "confidence": raw.get("match_score"),
                    "verify_url": url,
                }
            )

        if lookup.get("found") and lookup.get("data"):
            data = lookup["data"]
            url = _candidate_url(data)
            confidence = data.get("match_score") or lookup.get("confidence")

            if url and confidence and confidence >= CONFIDENT_MATCH_THRESHOLD:
                filled = self._merge(citation, data)
                remaining = missing_fields(filled)
                result.formatted = self.formatter.format_citation(filled)
                result.confidence = confidence
                result.source = lookup.get("source")
                result.verify_url = url
                result.missing = remaining
                result.missing_labels = [
                    FIELD_LABELS.get(f, f) for f in remaining
                ]
                result.status = RESOLVED if not remaining else AMBIGUOUS
                result.notes.append(
                    "Completed from a matched record. Open the source link to "
                    "confirm before relying on it."
                )
                return result

        if result.candidates:
            result.status = AMBIGUOUS
            result.notes.append(
                "Close matches were found, but none was a confident enough "
                "match to fill in automatically. Pick the right one below."
            )
            return result

        rejected = lookup.get("rejected_count") or 0
        if rejected:
            result.notes.append(
                f"{rejected} search result(s) were discarded as too dissimilar "
                "to your input. Nothing is reported that cannot be verified."
            )
        result.notes.append(
            "No matching record was found. The missing fields above are what "
            "this citation still needs."
        )
        return result

    def _merge(self, citation: Citation, data: dict[str, Any]) -> Citation:
        """Apply looked-up fields onto a copy, never overwriting user input."""
        filled = citation.model_copy(deep=True)

        case_name = data.get("case_name")
        if case_name and len(filled.parties or []) < 2 and " v. " in case_name:
            left, _, right = case_name.partition(" v. ")
            filled.parties = [left.strip(), right.strip()]

        citations = data.get("citation")
        if citations and not (filled.volume and filled.reporter and filled.page):
            first = citations[0] if isinstance(citations, list) else citations
            parts = str(first).split()
            if len(parts) >= 3 and parts[0].isdigit() and parts[-1].isdigit():
                filled.volume = filled.volume or parts[0]
                filled.reporter = filled.reporter or " ".join(parts[1:-1])
                filled.page = filled.page or parts[-1]

        date_filed = data.get("date_filed") or ""
        if not filled.year and len(str(date_filed)) >= 4 and str(date_filed)[:4].isdigit():
            filled.year = int(str(date_filed)[:4])

        for source_key, target in (
            ("title", "title"),
            ("author", "author"),
            ("container_title", "journal"),
            ("volume", "volume"),
            ("page", "page"),
        ):
            value = data.get(source_key)
            if value and not getattr(filled, target, None):
                setattr(filled, target, value)

        if data.get("year") and not filled.year:
            try:
                filled.year = int(data["year"])
            except (TypeError, ValueError):
                pass

        if not missing_fields(filled):
            filled.status = CitationStatus.COMPLETE
        return filled
