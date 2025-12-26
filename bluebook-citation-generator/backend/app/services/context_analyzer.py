"""
Context-aware citation analysis for short form decisions.

Enhanced with:
- Better within-footnote id tracking
- String cite detection
- Infra reference support
- Smarter hereinafter suggestions
"""

from typing import List, Dict, Optional, Tuple
from ..models.citation import Citation, CitationContext, CitationType
from ..utils.bluebook_patterns import abbreviate_party_name

class DocumentContextAnalyzer:
    """
    Analyzes document structure to make citation decisions.

    Implements Bluebook rules:
    - Rule 4.1: Use of Id.
    - Rule 4.2: Use of Supra
    - Rule 10.9: Short forms for cases
    - Rule 3.5: Internal cross-references (infra/supra)
    """

    def __init__(self):
        self.footnote_citations: Dict[int, List[str]] = {}
        self.citation_first_use: Dict[str, int] = {}
        self.citation_contexts: Dict[str, CitationContext] = {}
        # Track citations within the current footnote for Id. decisions
        self.current_footnote_cites: List[str] = []
        # Track the last citation used (for within-footnote Id.)
        self.last_citation_key: Optional[str] = None
        self.last_footnote: int = 0
    
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
        """
        Analyze sequence of citations and suggest optimal short forms.

        Enhanced to handle:
        - Within-footnote Id. usage
        - String cites (consecutive citations in same sentence)
        - Multiple citation footnotes
        """
        suggestions = []
        seen: Dict[str, CitationContext] = {}
        footnote_history: Dict[int, List[str]] = {}
        # Track last citation for within-footnote Id.
        last_cite_key: Optional[str] = None
        last_fn: int = 0
        # Track position within footnote
        footnote_position: Dict[int, int] = {}

        for citation in citations:
            fn = citation.footnote_number or 0

            # Track position within this footnote
            if fn not in footnote_position:
                footnote_position[fn] = 0
            else:
                footnote_position[fn] += 1

            is_first_in_footnote = footnote_position[fn] == 0

            suggestion = {
                "citation_id": citation.id,
                "current_form": citation.raw_text,
                "suggested_form": None,
                "short_form_type": None,
                "explanation": None,
                "footnote_number": fn,
                "position_in_footnote": footnote_position[fn],
                "can_use_string_cite": False,
            }

            # Skip short forms - they're already short
            if citation.is_short_form:
                suggestion["short_form_type"] = citation.short_form_type
                suggestion["suggested_form"] = citation.raw_text
                suggestions.append(suggestion)
                last_cite_key = None  # Short forms break Id. chain
                last_fn = fn
                continue

            cite_key = self._get_citation_key(citation)

            if cite_key and cite_key in seen:
                context = seen[cite_key]

                # Check for within-footnote Id. (Rule 4.1)
                # Can use Id. if: same footnote AND last citation was this same source
                can_use_within_footnote_id = (
                    fn == last_fn and
                    last_cite_key == cite_key and
                    fn > 0
                )

                # Check for cross-footnote Id. (Rule 4.1)
                # Can use Id. if: different footnote AND previous footnote had exactly one source
                can_use_cross_footnote_id = (
                    fn != last_fn and
                    is_first_in_footnote and
                    self._can_use_id(cite_key, fn, footnote_history)
                )

                if can_use_within_footnote_id or can_use_cross_footnote_id:
                    if citation.pincite:
                        suggestion["suggested_form"] = f"Id. at {citation.pincite}."
                    else:
                        suggestion["suggested_form"] = "Id."
                    suggestion["short_form_type"] = "id"

                    if can_use_within_footnote_id:
                        suggestion["explanation"] = "Same source as immediately preceding citation in this footnote"
                    else:
                        suggestion["explanation"] = "Same source as the only citation in the previous footnote"

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

                # Check if string cite is possible (same footnote, different source)
                if not is_first_in_footnote and last_cite_key != cite_key:
                    suggestion["can_use_string_cite"] = True

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
                    hereinafter_reason = self._get_hereinafter_reason(citation)
                    if hereinafter_reason:
                        short_name = self._generate_hereinafter(citation)
                        context.hereinafter_name = short_name
                        suggestion["add_hereinafter"] = short_name
                        suggestion["explanation"] = hereinafter_reason

                    seen[cite_key] = context

                suggestion["suggested_form"] = citation.suggested_correction or citation.raw_text
                suggestion["short_form_type"] = "full"

            # Track in footnote history
            if fn > 0:
                if fn not in footnote_history:
                    footnote_history[fn] = []
                if cite_key:
                    footnote_history[fn].append(cite_key)

            # Update tracking for next iteration
            last_cite_key = cite_key
            last_fn = fn

            suggestions.append(suggestion)

        # Second pass: identify infra references
        suggestions = self._add_infra_suggestions(suggestions, seen)

        return suggestions

    def _add_infra_suggestions(
        self,
        suggestions: List[Dict],
        seen: Dict[str, CitationContext]
    ) -> List[Dict]:
        """
        Add suggestions for infra references where appropriate.

        Per Rule 3.5, use 'infra' to refer to material that appears later
        in the document.
        """
        # Find citations that are referenced before their first appearance
        for i, suggestion in enumerate(suggestions):
            if suggestion["short_form_type"] == "full":
                cite_id = suggestion["citation_id"]
                fn = suggestion["footnote_number"]

                # Check if any later citation references this
                later_refs = [
                    s for s in suggestions[i+1:]
                    if s.get("short_form_type") in ["supra", "id", "short_case"]
                    and s["footnote_number"] > fn
                ]

                if later_refs:
                    # This is a heavily-referenced source - hereinafter is helpful
                    if len(later_refs) >= 2 and "add_hereinafter" not in suggestion:
                        ctx = seen.get(f"first:{cite_id}")
                        if ctx:
                            suggestion["multiple_references"] = len(later_refs)

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
        return self._get_hereinafter_reason(citation) is not None

    def _get_hereinafter_reason(self, citation: Citation) -> Optional[str]:
        """
        Determine if hereinafter is appropriate and return reason.

        Per Bluebook Rule 4.2(b), hereinafter is appropriate when:
        - The title is very long (>60 chars)
        - There are multiple authors
        - The short form would be confusing
        """
        # Long titles benefit from hereinafter
        if citation.title and len(citation.title) > 60:
            return f"Long title ({len(citation.title)} chars) - consider adding [hereinafter]"

        # Multiple authors are unwieldy in supra
        if citation.author:
            if " & " in citation.author:
                return "Multiple authors - consider adding [hereinafter]"
            if citation.author.count(",") >= 2:
                return "Multiple authors - consider adding [hereinafter]"

        # Books and articles with generic titles
        if citation.type in [CitationType.LAW_REVIEW, CitationType.BOOK]:
            generic_starts = [
                "The ", "A ", "An ", "On ", "In ", "Notes on",
                "Introduction to", "Analysis of", "Study of"
            ]
            if citation.title:
                for start in generic_starts:
                    if citation.title.startswith(start) and len(citation.title) > 40:
                        return "Generic title pattern - consider adding [hereinafter]"

        return None

    def _generate_hereinafter(self, citation: Citation) -> str:
        """
        Generate hereinafter name.

        Creates a short, distinctive identifier per Rule 4.2(b).
        """
        if citation.title:
            # Find the most distinctive words in the title
            words = citation.title.split()

            # Skip common starting words
            skip_words = {"the", "a", "an", "on", "in", "of", "to", "for", "and"}
            distinctive_words = []

            for word in words:
                clean_word = word.strip(",:;.\"'")
                if clean_word.lower() not in skip_words and len(clean_word) > 2:
                    distinctive_words.append(clean_word)
                    if len(distinctive_words) >= 3:
                        break

            if distinctive_words:
                return " ".join(distinctive_words)

            # Fallback to first 3 words
            return " ".join(words[:3])

        if citation.author:
            # Use author's last name
            return citation.author.split()[-1]

        return "Source"

    def get_citation_summary(self, citations: List[Citation]) -> Dict:
        """
        Generate a summary of citation usage patterns in the document.

        Useful for identifying:
        - Most frequently cited sources
        - Citation style consistency issues
        - Opportunities for short form optimization
        """
        summary = {
            "total_citations": len(citations),
            "by_type": {},
            "short_form_usage": {
                "id": 0,
                "supra": 0,
                "short_case": 0,
                "full": 0,
            },
            "most_cited": [],
            "issues": [],
        }

        cite_counts: Dict[str, int] = {}

        for citation in citations:
            # Count by type
            type_name = citation.type.value
            summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1

            # Track short form usage
            if citation.is_short_form:
                sf_type = citation.short_form_type or "other"
                if sf_type in summary["short_form_usage"]:
                    summary["short_form_usage"][sf_type] += 1
            else:
                summary["short_form_usage"]["full"] += 1

            # Count individual citations
            key = self._get_citation_key(citation)
            if key:
                cite_counts[key] = cite_counts.get(key, 0) + 1

        # Find most cited
        sorted_cites = sorted(cite_counts.items(), key=lambda x: x[1], reverse=True)
        summary["most_cited"] = [
            {"key": k, "count": v}
            for k, v in sorted_cites[:5]
            if v > 1
        ]

        # Identify potential issues
        if summary["short_form_usage"]["full"] > summary["total_citations"] * 0.8:
            summary["issues"].append({
                "type": "underuse_short_forms",
                "message": "Many repeated citations could use short forms"
            })

        return summary
