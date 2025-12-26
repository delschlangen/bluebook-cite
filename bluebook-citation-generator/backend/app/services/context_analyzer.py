"""
Context-aware citation analysis for short form decisions.
"""

from typing import List, Dict, Optional, Tuple
from ..models.citation import Citation, CitationContext, CitationType
from ..utils.bluebook_patterns import abbreviate_party_name

class DocumentContextAnalyzer:
    """Analyzes document structure to make citation decisions."""
    
    def __init__(self):
        self.footnote_citations: Dict[int, List[str]] = {}
        self.citation_first_use: Dict[str, int] = {}
        self.citation_contexts: Dict[str, CitationContext] = {}
    
    def analyze_document_structure(self, text: str) -> Dict:
        """Analyze overall document structure."""
        import re
        
        analysis = {
            "has_footnotes": False,
            "citation_style": "unknown",
            "section_count": 0,
            "estimated_word_count": len(text.split()),
        }
        
        # Detect footnote markers
        footnote_patterns = [
            r'\[\d+\]',
            r'(?:^|\s)\d{1,3}(?=\s+[A-Z])',
            r'(?:^|\s)\d{1,3}\.',
        ]
        
        for pattern in footnote_patterns:
            if re.search(pattern, text, re.MULTILINE):
                analysis["has_footnotes"] = True
                break
        
        # Count potential footnotes
        footnote_count = len(re.findall(r'\[\d+\]', text))
        
        if footnote_count > 10:
            analysis["citation_style"] = "law_review"
        elif footnote_count > 0:
            analysis["citation_style"] = "footnotes"
        else:
            analysis["citation_style"] = "inline"
        
        # Count sections
        section_patterns = [
            r'^(?:I{1,3}|IV|V|VI{0,3}|IX|X)\.',
            r'^\d+\.',
            r'^[A-Z]\.',
            r'^Section\s+\d+',
        ]
        
        for pattern in section_patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            analysis["section_count"] = max(analysis["section_count"], len(matches))
        
        return analysis
    
    def analyze_citation_sequence(self, citations: List[Citation]) -> List[Dict]:
        """Analyze sequence of citations and suggest optimal short forms."""
        suggestions = []
        seen: Dict[str, CitationContext] = {}
        footnote_history: Dict[int, List[str]] = {}
        
        for citation in citations:
            fn = citation.footnote_number or 0
            
            suggestion = {
                "citation_id": citation.id,
                "current_form": citation.raw_text,
                "suggested_form": None,
                "short_form_type": None,
                "explanation": None,
                "footnote_number": fn,
            }
            
            # Skip short forms - they're already short
            if citation.is_short_form:
                suggestion["short_form_type"] = citation.short_form_type
                suggestion["suggested_form"] = citation.raw_text
                suggestions.append(suggestion)
                continue
            
            # Check if this is a repeat
            cite_key = self._get_citation_key(citation)
            
            if cite_key and cite_key in seen:
                context = seen[cite_key]
                
                # Check if we can use Id.
                if self._can_use_id(cite_key, fn, footnote_history):
                    if citation.pincite:
                        suggestion["suggested_form"] = f"Id. at {citation.pincite}."
                    else:
                        suggestion["suggested_form"] = "Id."
                    suggestion["short_form_type"] = "id"
                    suggestion["explanation"] = "Same source as immediately preceding citation"
                
                # Use supra for non-cases
                elif citation.type != CitationType.CASE:
                    suggestion["suggested_form"] = self._format_supra(citation, context)
                    suggestion["short_form_type"] = "supra"
                    suggestion["explanation"] = f"Previously cited in note {context.first_occurrence_footnote}"
                
                # Use short case form
                else:
                    suggestion["suggested_form"] = self._format_short_case(citation, context)
                    suggestion["short_form_type"] = "short_case"
                    suggestion["explanation"] = "Short form for previously cited case"
                
                context.last_used_footnote = fn
                context.times_cited += 1
            
            else:
                # First occurrence
                if cite_key:
                    context = CitationContext(
                        citation_id=citation.id,
                        first_occurrence_footnote=fn,
                        full_citation=citation.suggested_correction or citation.raw_text,
                        last_used_footnote=fn,
                    )
                    
                    # Check if hereinafter is appropriate
                    if self._should_use_hereinafter(citation):
                        short_name = self._generate_hereinafter(citation)
                        context.hereinafter_name = short_name
                        suggestion["add_hereinafter"] = short_name
                        suggestion["explanation"] = "Consider adding [hereinafter] for long title"
                    
                    seen[cite_key] = context
                
                suggestion["suggested_form"] = citation.suggested_correction or citation.raw_text
                suggestion["short_form_type"] = "full"
            
            # Track in footnote history
            if fn > 0:
                if fn not in footnote_history:
                    footnote_history[fn] = []
                if cite_key:
                    footnote_history[fn].append(cite_key)
            
            suggestions.append(suggestion)
        
        return suggestions
    
    def _get_citation_key(self, citation: Citation) -> Optional[str]:
        """Generate a unique key for citation deduplication."""
        if citation.type == CitationType.CASE and citation.parties:
            return f"case:{citation.parties[0]}:{citation.parties[1] if len(citation.parties) > 1 else ''}"
        elif citation.type == CitationType.STATUTE:
            return f"statute:{citation.title_number}:{citation.section}"
        elif citation.type == CitationType.REGULATION:
            return f"reg:{citation.title_number}:{citation.section}"
        elif citation.type == CitationType.LAW_REVIEW:
            return f"article:{citation.author}:{citation.title}"
        elif citation.type == CitationType.BOOK:
            return f"book:{citation.author}:{citation.title}"
        return None
    
    def _can_use_id(
        self,
        cite_key: str,
        current_fn: int,
        footnote_history: Dict[int, List[str]]
    ) -> bool:
        """Check if Id. can be used per Rule 4.1."""
        if current_fn <= 0:
            return False
        
        # Check previous footnote
        prev_fn = current_fn - 1
        if prev_fn not in footnote_history:
            return False
        
        prev_cites = footnote_history[prev_fn]
        
        # Id. requires exactly one source in previous footnote
        if len(prev_cites) != 1:
            return False
        
        return prev_cites[0] == cite_key
    
    def _format_supra(self, citation: Citation, context: CitationContext) -> str:
        """Format supra citation."""
        if context.hereinafter_name:
            prefix = context.hereinafter_name
        elif citation.author:
            prefix = citation.author.split()[-1]
        else:
            prefix = ""
        
        if prefix:
            base = f"{prefix}, supra note {context.first_occurrence_footnote}"
        else:
            base = f"supra note {context.first_occurrence_footnote}"
        
        if citation.pincite:
            return f"{base}, at {citation.pincite}."
        return f"{base}."
    
    def _format_short_case(self, citation: Citation, context: CitationContext) -> str:
        """Format short form case citation."""
        if not citation.parties:
            return f"supra note {context.first_occurrence_footnote}."
        
        short_name = citation.parties[0]
        non_distinctive = ["United States", "State", "People", "Commonwealth"]
        
        if short_name in non_distinctive and len(citation.parties) > 1:
            short_name = citation.parties[1]
        
        short_name = abbreviate_party_name(short_name)
        
        if citation.volume and citation.reporter:
            base = f"*{short_name}*, {citation.volume} {citation.reporter}"
            if citation.pincite:
                return f"{base} at {citation.pincite}."
            elif citation.page:
                return f"{base} at {citation.page}."
        
        return f"*{short_name}*, supra note {context.first_occurrence_footnote}."
    
    def _should_use_hereinafter(self, citation: Citation) -> bool:
        """Check if hereinafter designation is appropriate."""
        if citation.title and len(citation.title) > 60:
            return True
        if citation.author and (" & " in citation.author or citation.author.count(",") >= 2):
            return True
        return False
    
    def _generate_hereinafter(self, citation: Citation) -> str:
        """Generate hereinafter name."""
        if citation.title:
            words = citation.title.split()[:3]
            return " ".join(words)
        if citation.author:
            return citation.author.split()[-1]
        return "Source"
