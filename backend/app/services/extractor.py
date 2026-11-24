"""
Citation extraction engine using regex patterns.
"""

import re
from bisect import bisect_left, bisect_right

from .. import limits
from ..models.citation import Citation, CitationStatus, CitationType
from ..utils.bluebook_patterns import PATTERNS
from ..utils.text_normalize import normalize_text
from .citation_engine import ENGINE

# Procedural case-name forms where the leading words ARE the party name and
# must survive cleanup.
LEGAL_NAME_PREFIXES = (
    "in re ",
    "ex parte ",
    "ex rel. ",
    "in the matter of ",
    "matter of ",
    "estate of ",
)


class TooManyCitationsError(Exception):
    """The text holds more citations than one analysis will build."""

    def __init__(self, limit: int):
        super().__init__(f"more than {limit:,} citations")
        self.limit = limit


class SpanIndex:
    """Disjoint [start, end) spans kept sorted, so an overlap test is O(log n).

    Every caller only appends a span after _overlaps() said no, so the spans are
    pairwise disjoint and sorting by start also sorts by end.

    Every citation found claims one span, so `limit` is also a limit on how many citations are
    built. Each costs about 2 KB, and a text at the size limit can hold 375,000 bare "Id."
    (about 800 MB) before the 2,000 shown are chosen; real documents hold a few thousand.
    """

    def __init__(self, limit: int | None = None):
        self.starts: list[int] = []
        self.ends: list[int] = []
        self.limit = limit

    def append(self, span: tuple[int, int]) -> None:
        if self.limit is not None and len(self.starts) >= self.limit:
            raise TooManyCitationsError(self.limit)
        start, end = span
        i = bisect_left(self.starts, start)
        self.starts.insert(i, start)
        self.ends.insert(i, end)

    def overlaps(self, start: int, end: int) -> bool:
        i = bisect_left(self.starts, end)      # spans that begin before `end`
        return i > 0 and self.ends[i - 1] > start

    def __len__(self) -> int:
        return len(self.starts)


class CitationExtractor:
    """Extracts citations from legal text using Bluebook patterns."""

    def _clean_party_name(self, name: str) -> str:
        """Clean up party name captured by greedy regex.

        The greedy regex may capture entire sentences before "v.". This
        function extracts just the party name by finding where it actually
        starts (typically the last few capitalized words before the end).
        """
        name = name.strip()
        words = name.split()
        if not words:
            return name

        # Procedural forms are the party name. Trimming them produces
        # "re Grand Jury Subpoena" from "In re Grand Jury Subpoena".
        lowered = name.lower()
        for prefix in LEGAL_NAME_PREFIXES:
            if lowered.startswith(prefix):
                return name

        # Boundary words that signal end of preceding text, start of party name
        boundary_words = {'in', 'see', 'but', 'cf.', 'compare', 'e.g.', 'accord',
                          'held', 'ruled', 'found', 'stated', 'noted', 'concluded'}

        # Work backwards to find where the party name starts
        best_start = 0
        for i in range(len(words) - 1, -1, -1):
            word = words[i]
            word_lower = word.lower().rstrip('.,;:')

            # If we hit a sentence boundary (ends with period not abbreviation)
            if i < len(words) - 1 and word.endswith('.') and not self._is_abbreviation(word):
                best_start = i + 1
                break

            # If we hit a boundary word, the party name likely starts after it
            if word_lower in boundary_words:
                best_start = i + 1
                break

            # Stop if we've captured more than 6 words for the party name
            if len(words) - i > 6:
                best_start = i + 1
                break

        result_words = words[best_start:]

        # Strip leading citation signals and prose artifacts. "The" goes too,
        # per Rule 10.2.1(d). "A" and "An" do NOT: they are not covered by that
        # rule, and dropping them mangles names like
        # "A Book Named 'John Cleland's Memoirs' v. Attorney General".
        skip_words = {'The', 'See', 'In', 'But', 'Cf.', 'Also', 'also', 'that'}
        while result_words and result_words[0] in skip_words:
            result_words = result_words[1:]

        return ' '.join(result_words).strip() if result_words else name

    def _is_abbreviation(self, word: str) -> bool:
        """Check if a word ending in period is likely an abbreviation."""
        abbrevs = {'Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Jr.', 'Sr.', 'Inc.', 'Corp.',
                   'Co.', 'Ltd.', 'LLC.', 'v.', 'U.S.', 'S.', 'N.', 'E.', 'W.'}
        return word in abbrevs or (len(word) <= 4 and word.endswith('.'))

    def extract_all(self, text: str, include_spec: bool = True) -> list[Citation]:
        """Extract all citations from text.

        `include_spec` turns the data-driven types (constitutions, rules, regulations,
        reports and so on) on or off. The repair endpoint turns it off when it wants
        only the older case, statute and book readings to compare against.
        """
        # Curly quotes and en dashes from phones and word processors defeat the
        # patterns. The replacement is one character for one character, so every
        # offset still points at the same place in the original document.
        text = normalize_text(text)
        citations = []

        # Track positions to avoid duplicate matches (and to bound how many citations are built)
        matched_spans = SpanIndex(limit=limits.MAX_CITATIONS_ANALYZED)

        # The data-driven types go first so they claim their spans before the older,
        # looser patterns can read part of the same text as something else (a book,
        # for instance, out of "Agency, GAO-16-552, Title (2016)").
        if include_spec:
            citations.extend(self._extract_spec_types(text, matched_spans))

        # Extract each citation type in priority order
        citations.extend(self._extract_cases(text, matched_spans))
        citations.extend(self._extract_statutes(text, matched_spans))
        citations.extend(self._extract_law_reviews(text, matched_spans))
        citations.extend(self._extract_books(text, matched_spans))
        citations.extend(self._extract_short_forms(text, matched_spans))
        citations.extend(self._extract_urls(text, matched_spans))

        # Sort by position
        citations.sort(key=lambda c: c.position_start)

        # Assign footnote numbers based on context
        self._assign_footnotes(citations, text)

        return citations

    def _overlaps(self, start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        """Check if span overlaps with any existing span."""
        if isinstance(spans, SpanIndex):
            return spans.overlaps(start, end)
        for s_start, s_end in spans:
            if not (end <= s_start or start >= s_end):
                return True
        return False

    def _extract_cases(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract case citations."""
        citations = []

        # First, complete case citations
        for match in PATTERNS["case_complete"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            parties = [
                self._clean_party_name(match.group(1)),
                self._clean_party_name(match.group(2))
            ]
            volume = match.group(3)
            reporter = match.group(4).strip()
            page = match.group(5)
            pincite = match.group(6) if match.lastindex >= 6 else None
            court_year = match.group(7) if match.lastindex >= 7 else ""

            # Parse court and year from parenthetical
            year = None
            court = None
            year_match = re.search(r'(\d{4})', court_year)
            if year_match:
                year = int(year_match.group(1))
                court = court_year.replace(year_match.group(1), "").strip()

            citations.append(Citation(
                type=CitationType.CASE,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                parties=parties,
                volume=volume,
                reporter=reporter,
                page=page,
                pincite=pincite,
                court=court if court else None,
                year=year,
            ))

        # Then cases carrying a reporter citation but no year parenthetical.
        # These are mostly complete and must not be reported as though the
        # volume, reporter and page were absent.
        for match in PATTERNS["case_no_year"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.CASE,
                status=CitationStatus.INCOMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                parties=[
                    self._clean_party_name(match.group(1)),
                    self._clean_party_name(match.group(2)),
                ],
                volume=match.group(3),
                reporter=match.group(4).strip(),
                page=match.group(5),
            ))

        # Then, incomplete case citations (just party names)
        for match in PATTERNS["case_incomplete"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            parties = [
                self._clean_party_name(match.group(1)),
                self._clean_party_name(match.group(2))
            ]

            citations.append(Citation(
                type=CitationType.CASE,
                status=CitationStatus.INCOMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                parties=parties,
            ))

        return citations

    def _extract_statutes(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract statute citations."""
        citations = []

        # U.S.C. citations
        for match in PATTERNS["statute_usc"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.STATUTE,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                title_number=match.group(1),
                code="U.S.C.",
                section=match.group(2),
                subsection=match.group(3) if match.lastindex >= 3 else None,
            ))

        # State statute citations
        for match in PATTERNS["statute_state"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.STATUTE,
                status=CitationStatus.NEEDS_VERIFICATION,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                code=match.group(1).strip(),
                section=match.group(2),
            ))

        return citations

    def _extract_spec_types(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Citations of every kind described by the spec.

        These are never sent to an outside lookup: for most of them no free source can
        verify a record, so the honest output is the corrected form and a list of what
        is missing.
        """
        citations: list[Citation] = []
        for match in ENGINE.find_all(text):
            if self._overlaps(match.start, match.end, spans):
                continue
            spans.append((match.start, match.end))

            spec = ENGINE.type_spec(match.type_id)
            missing = ENGINE.missing(match.type_id, match.fields)
            citations.append(Citation(
                type=CitationType(spec.get("citation_type", "other")),
                status=CitationStatus.INCOMPLETE if missing else CitationStatus.COMPLETE,
                raw_text=text[match.start:match.end],
                position_start=match.start,
                position_end=match.end,
                kind=match.type_id,
                kind_label=spec["label"],
                spec_fields=match.fields,
                missing=missing,
                template=ENGINE.render(match.type_id, match.fields, gaps=True) if missing else None,
                format_confidence=spec.get("confidence"),
            ))
        return citations

    def _extract_law_reviews(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract law review article citations."""
        citations = []

        for match in PATTERNS["law_review"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.LAW_REVIEW,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                author=match.group(1).strip(),
                title=match.group(2).strip(),
                volume=match.group(3),
                journal=match.group(4).strip(),
                page=match.group(5),
                pincite=match.group(6) if match.lastindex >= 6 and match.group(6) else None,
                year=int(match.group(7)) if match.lastindex >= 7 else None,
            ))

        return citations

    def _extract_books(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract book citations."""
        citations = []

        for match in PATTERNS["book"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.BOOK,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                author=match.group(1).strip(),
                title=match.group(2).strip(),
                edition=match.group(3) if match.lastindex >= 3 and match.group(3) else None,
                year=int(match.group(4)) if match.lastindex >= 4 else None,
            ))

        return citations

    def _extract_short_forms(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract short form citations (Id., supra)."""
        citations = []

        # Id. citations
        for match in PATTERNS["id_citation"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.OTHER,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                is_short_form=True,
                short_form_type="id",
                # A bare "Id." has no groups at all, so lastindex is None, not 0. Comparing
                # None to an int raised TypeError, which made every document containing a
                # bare "Id." fail (the most common short form in legal writing).
                pincite=match.group(1),
            ))

        # Supra citations
        for match in PATTERNS["supra_citation"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.OTHER,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                is_short_form=True,
                short_form_type="supra",
                author=match.group(1).strip(),
                footnote_number=int(match.group(2)) if match.group(2) else None,
                pincite=match.group(3) if match.lastindex >= 3 else None,
            ))

        return citations

    def _extract_urls(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract URL citations."""
        citations = []

        for match in PATTERNS["url"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.WEBSITE,
                status=CitationStatus.INCOMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                url=match.group(0),
            ))

        return citations

    def _assign_footnotes(self, citations: list[Citation], text: str) -> None:
        """Assign footnote numbers to citations based on document structure."""
        # A Word document carries real footnote numbers, written in front of each
        # note by the parser. When any are present they are the truth, and the
        # guess below, which would misread numbered headings and lines that begin
        # with a reporter volume, is skipped entirely.
        footnote_positions = []
        explicit = list(PATTERNS["footnote_marker_explicit"].finditer(text))
        if explicit:
            # Endnotes are numbered separately and would collide with footnotes.
            footnote_positions = [
                (int(m.group(2)), m.start()) for m in explicit if not m.group(1)
            ]
            endnote_positions = [
                (int(m.group(2)), m.start()) for m in explicit if m.group(1)
            ]
            footnote_positions += endnote_positions
        else:
            for match in PATTERNS["footnote_marker"].finditer(text):
                footnote_positions.append((int(match.group(1)), match.start()))

        footnote_positions.sort(key=lambda x: x[1])
        fn_positions = [pos for _, pos in footnote_positions]
        fn_numbers = [num for num, _ in footnote_positions]

        # Nearest footnote marker at or before each citation: a binary search per
        # citation instead of a scan from the top of the document.
        for citation in citations:
            i = bisect_right(fn_positions, citation.position_start) - 1
            current_footnote = fn_numbers[i] if i >= 0 else 0
            if current_footnote > 0:
                citation.footnote_number = current_footnote
