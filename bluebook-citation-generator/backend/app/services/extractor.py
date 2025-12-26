"""
Citation extraction engine using regex patterns.
"""

import re
from typing import List, Tuple, Optional
from ..models.citation import Citation, CitationType, CitationStatus
from ..utils.bluebook_patterns import PATTERNS, abbreviate_party_name

class CitationExtractor:
    """Extracts citations from legal text using Bluebook patterns."""
    
    def extract_all(self, text: str) -> List[Citation]:
        """Extract all citations from text."""
        citations = []
        
        # Track positions to avoid duplicate matches
        matched_spans: List[Tuple[int, int]] = []
        
        # Extract each citation type in priority order
        citations.extend(self._extract_cases(text, matched_spans))
        citations.extend(self._extract_statutes(text, matched_spans))
        citations.extend(self._extract_regulations(text, matched_spans))
        citations.extend(self._extract_law_reviews(text, matched_spans))
        citations.extend(self._extract_books(text, matched_spans))
        citations.extend(self._extract_short_forms(text, matched_spans))
        citations.extend(self._extract_urls(text, matched_spans))
        
        # Sort by position
        citations.sort(key=lambda c: c.position_start)
        
        # Assign footnote numbers based on context
        self._assign_footnotes(citations, text)
        
        return citations
    
    def _overlaps(self, start: int, end: int, spans: List[Tuple[int, int]]) -> bool:
        """Check if span overlaps with any existing span."""
        for s_start, s_end in spans:
            if not (end <= s_start or start >= s_end):
                return True
        return False
    
    def _extract_cases(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
        """Extract case citations."""
        citations = []
        
        # First, complete case citations
        for match in PATTERNS["case_complete"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue
            
            spans.append((match.start(), match.end()))
            
            parties = [match.group(1).strip(), match.group(2).strip()]
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
        
        # Then, incomplete case citations (just party names)
        for match in PATTERNS["case_incomplete"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue
            
            spans.append((match.start(), match.end()))
            
            parties = [match.group(1).strip(), match.group(2).strip()]
            
            citations.append(Citation(
                type=CitationType.CASE,
                status=CitationStatus.INCOMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                parties=parties,
            ))
        
        return citations
    
    def _extract_statutes(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
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
    
    def _extract_regulations(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
        """Extract regulation citations (C.F.R.)."""
        citations = []
        
        for match in PATTERNS["regulation_cfr"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue
            
            spans.append((match.start(), match.end()))
            
            citations.append(Citation(
                type=CitationType.REGULATION,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                title_number=match.group(1),
                code="C.F.R.",
                section=match.group(2),
            ))
        
        return citations
    
    def _extract_law_reviews(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
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
    
    def _extract_books(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
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
    
    def _extract_short_forms(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
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
                pincite=match.group(1) if match.lastindex >= 1 else None,
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
    
    def _extract_urls(self, text: str, spans: List[Tuple[int, int]]) -> List[Citation]:
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
    
    def _assign_footnotes(self, citations: List[Citation], text: str) -> None:
        """Assign footnote numbers to citations based on document structure."""
        # Find footnote markers
        footnote_positions = []
        for match in PATTERNS["footnote_marker"].finditer(text):
            footnote_positions.append((int(match.group(1)), match.start()))
        
        footnote_positions.sort(key=lambda x: x[1])
        
        # Assign footnote numbers based on proximity
        for citation in citations:
            # Find the nearest footnote marker before this citation
            current_footnote = 0
            for fn_num, fn_pos in footnote_positions:
                if fn_pos <= citation.position_start:
                    current_footnote = fn_num
                else:
                    break
            
            if current_footnote > 0:
                citation.footnote_number = current_footnote
