"""
Bluebook 21st Edition formatting rules engine.
"""

import re
import html
from typing import Optional, List, Tuple
from ..models.citation import Citation, CitationType, CitationContext
from ..utils.bluebook_patterns import (
    abbreviate_party_name,
    get_reporter_abbreviation,
    get_court_abbreviation,
    get_journal_abbreviation,
)


def clean_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities from text."""
    if not text:
        return text
    # Decode HTML entities like &lt; &gt; &amp;
    text = html.unescape(text)
    # Remove HTML tags like <i>, </i>, <b>, etc.
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

class BluebookFormatter:
    """Formats citations according to Bluebook 21st Edition rules."""
    
    def format_citation(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format a citation based on its type."""
        formatters = {
            CitationType.CASE: self.format_case,
            CitationType.STATUTE: self.format_statute,
            CitationType.REGULATION: self.format_regulation,
            CitationType.LAW_REVIEW: self.format_law_review,
            CitationType.BOOK: self.format_book,
            CitationType.WEBSITE: self.format_website,
        }
        
        formatter = formatters.get(citation.type)
        if formatter:
            return formatter(citation, is_law_review)
        return citation.raw_text
    
    def format_case(self, citation: Citation, is_law_review: bool = True) -> str:
        """
        Format case citation per Bluebook Rule 10.
        
        Law review format: Case Name, Vol. Reporter Page, Pincite (Court Year).
        Brief format: Case Name, Vol. Reporter Page, Pincite (Court Year)
        """
        if not citation.parties or len(citation.parties) < 2:
            return citation.raw_text
        
        # Format case name (Rule 10.2)
        plaintiff = abbreviate_party_name(citation.parties[0])
        defendant = abbreviate_party_name(citation.parties[1])
        case_name = f"{plaintiff} v. {defendant}"
        
        # Build reporter citation (Rule 10.3)
        if citation.volume and citation.reporter and citation.page:
            reporter = get_reporter_abbreviation(citation.reporter)
            reporter_cite = f"{citation.volume} {reporter} {citation.page}"
            
            # Add pincite if present (Rule 10.3.2)
            if citation.pincite:
                reporter_cite += f", {citation.pincite}"
        else:
            reporter_cite = ""
        
        # Build parenthetical (Rule 10.4)
        court_year = self._format_court_year(citation.court, citation.year)
        
        if is_law_review and reporter_cite:
            return f"*{case_name}*, {reporter_cite} ({court_year})."
        elif reporter_cite:
            return f"{case_name}, {reporter_cite} ({court_year})"
        else:
            return f"*{case_name}*" if is_law_review else case_name
    
    def _format_court_year(self, court: Optional[str], year: Optional[int]) -> str:
        """Format court and year parenthetical per Rule 10.4."""
        if not year:
            return ""
        
        if not court:
            return str(year)
        
        # Get court abbreviation
        court_abbrev = get_court_abbreviation(court)
        
        # No court abbreviation needed for U.S. Supreme Court
        if court_abbrev == "" or "U.S." in (court or ""):
            return str(year)
        
        return f"{court_abbrev} {year}"
    
    def format_statute(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format statute citation per Bluebook Rule 12."""
        if not citation.title_number or not citation.section:
            return citation.raw_text
        
        code = citation.code or "U.S.C."
        base = f"{citation.title_number} {code} § {citation.section}"
        
        if citation.subsection:
            base += f"({citation.subsection})"
        
        if citation.year:
            return f"{base} ({citation.year})."
        return f"{base}."
    
    def format_regulation(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format regulation citation per Bluebook Rule 14."""
        if not citation.title_number or not citation.section:
            return citation.raw_text
        
        base = f"{citation.title_number} C.F.R. § {citation.section}"
        
        if citation.year:
            return f"{base} ({citation.year})."
        return f"{base}."
    
    def format_law_review(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format law review article citation per Bluebook Rule 16."""
        parts = []

        if citation.author:
            parts.append(clean_html(citation.author))

        if citation.title:
            title = clean_html(citation.title)
            parts.append(f"*{title}*")
        
        if citation.volume and citation.journal and citation.page:
            journal = get_journal_abbreviation(citation.journal)
            vol_cite = f"{citation.volume} {journal} {citation.page}"
            if citation.pincite:
                vol_cite += f", {citation.pincite}"
            parts.append(vol_cite)
        
        if citation.year:
            parts.append(f"({citation.year})")
        
        if parts:
            return ", ".join(parts[:2]) + " " + " ".join(parts[2:]) + "."
        return citation.raw_text
    
    def format_book(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format book citation per Bluebook Rule 15."""
        parts = []

        if citation.author:
            # Author followed by comma
            parts.append(clean_html(citation.author) + ",")

        if citation.title:
            # Book titles in small caps for law reviews
            title = clean_html(citation.title)
            parts.append(title.upper())

        # Build parenthetical
        paren_parts = []
        if citation.edition:
            paren_parts.append(f"{citation.edition} ed.")
        if citation.year:
            paren_parts.append(str(citation.year))

        if paren_parts:
            parts.append(f"({' '.join(paren_parts)})")

        return " ".join(parts) + "."
    
    def format_website(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format website citation per Bluebook Rule 18."""
        parts = []

        if citation.author:
            parts.append(clean_html(citation.author))

        if citation.title:
            title = clean_html(citation.title)
            parts.append(f"*{title}*")
        
        if citation.url:
            parts.append(citation.url)
        
        if citation.access_date:
            parts.append(f"(last visited {citation.access_date})")
        
        if parts:
            return ", ".join(parts) + "."
        return citation.raw_text


class ShortFormManager:
    """
    Manages short form citations per Bluebook Rules 4 and 10.9.
    
    Key rules:
    - "Id." can only be used when citing to immediately preceding authority
    - "Id." cannot be used after a "see" or other signal citing multiple sources
    - Supra can be used after first full citation
    - Short case names must be distinctive
    """
    
    def __init__(self):
        self.citation_contexts: dict[str, CitationContext] = {}
        self.footnote_history: List[List[str]] = []
        self.current_footnote: int = 0
    
    def register_citation(self, citation: Citation, footnote_num: int) -> None:
        """Register a full citation for short form tracking."""
        context = CitationContext(
            citation_id=citation.id,
            first_occurrence_footnote=footnote_num,
            full_citation=citation.suggested_correction or citation.raw_text,
            last_used_footnote=footnote_num,
        )
        
        self.citation_contexts[citation.id] = context
        
        # Update footnote history
        while len(self.footnote_history) < footnote_num:
            self.footnote_history.append([])
        
        if footnote_num > 0:
            self.footnote_history[footnote_num - 1].append(citation.id)
    
    def can_use_id(
        self,
        citation_id: str,
        current_footnote: int,
        is_first_in_footnote: bool = True
    ) -> bool:
        """
        Check if "Id." can be used per Rule 4.1.
        
        Id. can be used when:
        1. Citing to immediately preceding citation (same footnote or previous)
        2. Previous footnote had only ONE source
        3. No intervening different citations
        """
        if current_footnote <= 0:
            return False
        
        if not is_first_in_footnote:
            # Check if previous citation in same footnote is the same source
            if current_footnote <= len(self.footnote_history):
                prev_cites = self.footnote_history[current_footnote - 1]
                if prev_cites and prev_cites[-1] == citation_id:
                    return True
            return False
        
        # Check previous footnote
        if current_footnote <= 1:
            return False
        
        prev_footnote_idx = current_footnote - 2
        if prev_footnote_idx >= len(self.footnote_history):
            return False
        
        prev_footnote_cites = self.footnote_history[prev_footnote_idx]
        
        # Id. requires exactly ONE citation in previous footnote
        if len(prev_footnote_cites) != 1:
            return False
        
        return prev_footnote_cites[0] == citation_id
    
    def get_short_form(
        self,
        citation: Citation,
        current_footnote: int,
        pincite: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Get appropriate short form for a citation.
        
        Returns: (short_form_type, formatted_citation)
        """
        context = self.citation_contexts.get(citation.id)
        if not context:
            return ("full", "")
        
        # Check for Id.
        if self.can_use_id(citation.id, current_footnote):
            if pincite:
                return ("id", f"Id. at {pincite}.")
            return ("id", "Id.")
        
        # For cases, use short case form
        if citation.type == CitationType.CASE:
            return ("short_case", self._format_short_case(citation, context, pincite))
        
        # For other types, use supra
        return ("supra", self._format_supra(citation, context, pincite))
    
    def _format_short_case(
        self,
        citation: Citation,
        context: CitationContext,
        pincite: Optional[str] = None
    ) -> str:
        """Format short form case citation per Rule 10.9."""
        if not citation.parties:
            return f"supra note {context.first_occurrence_footnote}"
        
        # Use first party name if distinctive
        short_name = citation.parties[0]
        
        # Common non-distinctive names
        non_distinctive = ["United States", "State", "People", "Commonwealth", "City", "County"]
        
        if short_name in non_distinctive and len(citation.parties) > 1:
            short_name = citation.parties[1]
        
        # Abbreviate if needed
        short_name = abbreviate_party_name(short_name)
        
        if citation.volume and citation.reporter:
            base = f"*{short_name}*, {citation.volume} {citation.reporter}"
            if pincite:
                return f"{base} at {pincite}."
            elif citation.page:
                return f"{base} at {citation.page}."
            return f"{base}."
        
        return f"*{short_name}*, supra note {context.first_occurrence_footnote}."
    
    def _format_supra(
        self,
        citation: Citation,
        context: CitationContext,
        pincite: Optional[str] = None
    ) -> str:
        """Format supra citation per Rule 4.2."""
        # Use hereinafter name if available
        if context.hereinafter_name:
            prefix = context.hereinafter_name
        elif citation.author:
            # Use author's last name
            prefix = citation.author.split()[-1]
        else:
            prefix = ""
        
        if prefix:
            base = f"{prefix}, supra note {context.first_occurrence_footnote}"
        else:
            base = f"supra note {context.first_occurrence_footnote}"
        
        if pincite:
            return f"{base}, at {pincite}."
        return f"{base}."
