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
    tally_lookups,
)
from ..utils.bluebook_patterns import abbreviate_party_name
from ..utils.field_guidance import CITATION_TEMPLATES, guidance_for
from ..utils.text_normalize import normalize_text
from .citation_engine import ENGINE
from .spec_engine import STYLES

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
    missing_details: list[dict[str, Any]] = field(default_factory=list)
    template: str | None = None
    # Set when the data-driven engine recognised the citation: which kind it is, and how
    # well established its format is. `style` is the typeface convention that was applied.
    kind: str | None = None
    kind_label: str | None = None
    format_confidence: str | None = None
    style: str = "law_review"
    rule_note: str | None = None
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
            "missing_details": self.missing_details,
            "template": self.template,
            "kind": self.kind,
            "kind_label": self.kind_label,
            "format_confidence": self.format_confidence,
            "style": self.style,
            "rule_note": self.rule_note,
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


# Reporters that carry U.S. Supreme Court decisions, normalised.
_SCOTUS_REPORTERS = {"US", "SCT", "LED", "LED2D"}


def is_scotus_reporter(reporter: str | None) -> bool:
    """True when this reporter publishes U.S. Supreme Court decisions."""
    if not reporter:
        return False
    normalised = "".join(c for c in reporter if c.isalnum()).upper()
    return normalised in _SCOTUS_REPORTERS


def build_template(citation: Citation, gaps: list[str]) -> str | None:
    """Render the citation in its finished shape, gaps marked in brackets.

    Naming the missing fields tells someone what is wrong. Showing them the
    whole citation with the holes in place tells them what it should look like,
    which is the thing they are actually trying to produce.
    """
    template = CITATION_TEMPLATES.get(citation.type.value)
    if not template:
        return None

    missing = set(gaps)

    def slot(field: str, value: Any) -> str:
        if field in missing or value in (None, "", []):
            return f"[{guidance_for(field)['label']}]"
        return str(value)

    if citation.type == CitationType.CASE:
        if citation.parties and len(citation.parties) >= 2:
            parties = (
                f"{abbreviate_party_name(citation.parties[0])} v. "
                f"{abbreviate_party_name(citation.parties[1])}"
            )
        else:
            parties = "[party names]"

        # Rule 10.4: the U.S. Supreme Court takes no court identifier, so the
        # slot is dropped rather than shown as a gap the reader must fill.
        # Every SCOTUS reporter counts, not just U.S., and "US" without periods
        # has to normalise to the same thing as "U.S.".
        if is_scotus_reporter(citation.reporter):
            court = ""
        elif citation.court:
            court = f"{citation.court} "
        else:
            court = "[court] "

        return template.format(
            parties=parties,
            volume=slot("volume", citation.volume),
            reporter=slot("reporter", citation.reporter),
            page=slot("page", citation.page),
            court=court,
            year=slot("year", citation.year),
        )

    fields = {
        name: slot(name, getattr(citation, name, None))
        for name in ("title_number", "code", "section", "author", "title",
                     "journal", "volume", "page", "year", "url")
    }
    try:
        return template.format(**fields)
    except KeyError:
        return None


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

    async def repair(self, text: str, style: str = "law_review") -> RepairResult:
        # Phone keyboards and word processors turn apostrophes and hyphens into curly
        # quotes and en dashes, which defeat every pattern. One character for one.
        text = normalize_text(text or "").strip()
        if style not in STYLES:
            style = "law_review"

        if not text:
            return RepairResult(
                input=text,
                status=UNPARSEABLE,
                style=style,
                notes=["Nothing to repair. Paste a citation or part of one."],
            )

        # Two readers look at the same text. The data-driven engine understands most
        # kinds of citation; the older readers handle cases, books, articles and the
        # U.S. Code. Whichever accounts for more of what was pasted wins, and the
        # engine wins a tie, exactly as in the browser.
        engine_match = ENGINE.best_match(text)
        legacy = self.extractor.extract_all(text, include_spec=False)
        legacy_best = (
            max(legacy, key=lambda c: c.position_end - c.position_start) if legacy else None
        )

        engine_length = (engine_match.end - engine_match.start) if engine_match else -1
        legacy_length = (
            legacy_best.position_end - legacy_best.position_start if legacy_best else -1
        )

        if engine_match is not None and engine_length >= legacy_length:
            return self._from_engine(text, engine_match, style)

        if legacy_best is None:
            return RepairResult(
                input=text,
                status=UNPARSEABLE,
                style=style,
                notes=[
                    "This does not look like a kind of citation this tool recognises "
                    "yet. Choose the kind of source below to see what its citation needs."
                ],
            )

        return await self._from_legacy(text, legacy_best, style)

    def _from_engine(self, text: str, match, style: str) -> RepairResult:
        """A citation the data-driven engine recognised."""
        spec = ENGINE.type_spec(match.type_id)
        missing = ENGINE.missing(match.type_id, match.fields)
        by_name = {f["name"]: f for f in spec["fields"]}
        formatted = ENGINE.render(match.type_id, match.fields, style)

        details = [
            {
                "field": n,
                "label": by_name[n]["label"],
                "rule": by_name[n].get("rule", ""),
                "display_rule": ENGINE.display_rule(by_name[n].get("rule")),
                "why": by_name[n].get("why", ""),
            }
            for n in missing
        ]

        notes = [
            "This citation was already complete. Formatting applied."
            if formatted
            else "The fields above are what this citation still needs.",
            *spec.get("notes", []),
        ]
        if spec.get("confidence") != "high":
            notes.append(
                "This format is less thoroughly checked than the others. Confirm it in "
                "your Bluebook before relying on it."
            )

        return RepairResult(
            input=text,
            status=RESOLVED if formatted else INCOMPLETE,
            citation_type=spec.get("citation_type", "other"),
            parsed=dict(match.fields),
            missing=missing,
            missing_labels=[by_name[n]["label"] for n in missing],
            missing_details=details,
            template=ENGINE.render(match.type_id, match.fields, style, gaps=True),
            kind=spec["id"],
            kind_label=spec["label"],
            format_confidence=spec.get("confidence"),
            style=style,
            rule_note=ENGINE.spec.get("edition_note") if any(d["display_rule"] for d in details) else None,
            formatted=formatted,
            # Nothing was fetched or inferred: the user's own words are the source.
            confidence=1.0 if formatted else None,
            source="your input" if formatted else None,
            notes=notes,
        )

    async def _from_legacy(self, text: str, citation: Citation, style: str) -> RepairResult:
        """A case, book, article or U.S. Code citation, read by the older readers."""
        is_law_review = style == "law_review"
        gaps = missing_fields(citation)

        result = RepairResult(
            input=text,
            status=INCOMPLETE,
            citation_type=citation.type.value,
            parsed=_parsed_fields(citation),
            missing=gaps,
            missing_labels=[FIELD_LABELS.get(g, g) for g in gaps],
            missing_details=[guidance_for(g) for g in gaps],
            template=build_template(citation, gaps),
            style=style,
        )
        if any(d.get("display_rule") for d in result.missing_details):
            result.rule_note = ENGINE.spec.get("edition_note")

        # Already complete. Format it and say so; no lookup is needed, and the
        # user's own input is the provenance.
        if not gaps:
            result.status = RESOLVED
            result.formatted = self.formatter.format_citation(citation, is_law_review)
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
        # The lookup methods turn every failure (a refused request, a timeout, a rate limit) into
        # "found: false", so "the source had no such record" and "the source could not be asked"
        # look the same in the result. Counting at the point where each request is made keeps
        # them apart, and a lawyer must not be told a case has no record when nobody looked.
        try:
            with tally_lookups() as tally:
                lookup = await self.lookup.smart_complete(citation)
        except Exception:
            result.notes.append(
                "The lookup service could not be reached, so only the parse "
                "is shown. The missing fields above are still accurate."
            )
            return result

        if lookup.get("unavailable"):
            return result  # the caller says why nothing was looked up

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
                result.formatted = self.formatter.format_citation(filled, result.style == "law_review")
                result.confidence = confidence
                result.source = lookup.get("source")
                result.verify_url = url
                result.missing = remaining
                result.missing_labels = [
                    FIELD_LABELS.get(f, f) for f in remaining
                ]
                result.missing_details = [guidance_for(f) for f in remaining]
                result.template = build_template(filled, remaining)
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

        if tally.unreachable:
            result.notes.append(
                "The outside sources could not be reached, so nothing was looked up. "
                "That does not mean there is no such record. The missing fields above "
                "are what this citation still needs."
            )
            return result

        rejected = lookup.get("rejected_count") or 0
        if rejected:
            result.notes.append(
                f"{rejected} search result(s) were discarded as too dissimilar "
                "to your input. Nothing is reported that cannot be verified."
            )
        if tally.failed:
            result.notes.append(
                "No matching record was found in the sources that answered, and some "
                "sources could not be reached. The missing fields above are what this "
                "citation still needs."
            )
        else:
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
