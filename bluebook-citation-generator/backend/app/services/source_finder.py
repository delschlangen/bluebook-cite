"""
Unsourced claim detection and source suggestion.

Enhanced with:
- Auto-lookup of potential sources
- Legal database integration for finding citations
- Suggested citation generation
"""

import re
from typing import List, Tuple, Optional, Dict, Any
from ..models.citation import UnsourcedClaim, Citation, CitationType, CitationStatus

class ClaimDetector:
    """
    Detects statements that require citations in legal writing.
    
    Types of claims needing citations:
    1. Legal rules and holdings
    2. Statistical claims
    3. Factual assertions
    4. Quotations
    5. Descriptions of other sources' arguments
    """
    
    LEGAL_PATTERNS = [
        r"(?:The|A)\s+(?:Supreme )?[Cc]ourt\s+(?:has\s+)?(?:held|ruled|found|determined|concluded|stated)",
        r"(?:Under|According to|Pursuant to)\s+(?:the\s+)?(?:\w+\s+)?(?:law|statute|regulation|rule|doctrine)",
        r"(?:The|A)\s+(?:\w+\s+)?(?:test|standard|doctrine|rule|principle)\s+(?:requires|provides|states|holds)",
        r"(?:Congress|The legislature)\s+(?:has\s+)?(?:enacted|passed|established|created)",
        r"(?:The Constitution|The \w+ Amendment)\s+(?:provides|guarantees|requires|prohibits)",
        r"(?:Courts|Judges|The judiciary)\s+(?:have|has)\s+(?:consistently|uniformly|generally)",
        r"[Ii]t is (?:well[- ])?(?:established|settled)\s+(?:law\s+)?that",
    ]
    
    STATISTICAL_PATTERNS = [
        r"\d+(?:\.\d+)?%",
        r"\d+(?:,\d{3})*(?:\.\d+)?\s+(?:people|individuals|cases|incidents|dollars)",
        r"(?:approximately|about|nearly|over|under|more than|less than)\s+\d+",
        r"(?:majority|minority|plurality)\s+of",
        r"(?:[Ss]tudies|[Rr]esearch|[Dd]ata|[Ee]vidence)\s+(?:show|indicate|suggest|demonstrate)",
    ]
    
    FACTUAL_PATTERNS = [
        r"[Ii]t is (?:a\s+)?(?:well[- ])?(?:known|established|documented)\s+(?:fact\s+)?that",
        r"[Aa]s a matter of fact",
        r"[Hh]istorically",
        r"[Tt]raditionally",
        r"[Gg]enerally(?:,)?\s+(?:speaking)?",
        r"[Ii]t is (?:commonly|widely|generally)\s+(?:accepted|believed|understood)",
    ]
    
    QUOTATION_PATTERN = r'"[^"]{15,}"'
    
    def __init__(self):
        self.legal_patterns = [re.compile(p, re.IGNORECASE) for p in self.LEGAL_PATTERNS]
        self.stat_patterns = [re.compile(p) for p in self.STATISTICAL_PATTERNS]
        self.fact_patterns = [re.compile(p, re.IGNORECASE) for p in self.FACTUAL_PATTERNS]
        self.quote_pattern = re.compile(self.QUOTATION_PATTERN)
    
    def detect_unsourced_claims(
        self,
        text: str,
        existing_citations: List[Tuple[int, int]]
    ) -> List[UnsourcedClaim]:
        """Scan text for claims that need citations but don't have them."""
        claims = []
        sentences = self._split_sentences(text)
        
        for sent_start, sent_end, sent_text in sentences:
            if self._has_nearby_citation(sent_start, sent_end, existing_citations):
                continue
            
            claim = self._analyze_sentence(sent_text, sent_start, sent_end)
            if claim:
                claims.append(claim)
        
        return claims
    
    def _split_sentences(self, text: str) -> List[Tuple[int, int, str]]:
        """Split text into sentences with position tracking."""
        sentence_enders = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')
        sentences = []
        last_end = 0
        
        for match in sentence_enders.finditer(text):
            sentence_text = text[last_end:match.start() + 1]
            sentences.append((last_end, match.start() + 1, sentence_text))
            last_end = match.end()
        
        if last_end < len(text):
            sentences.append((last_end, len(text), text[last_end:]))
        
        return sentences
    
    def _has_nearby_citation(
        self,
        start: int,
        end: int,
        citations: List[Tuple[int, int]]
    ) -> bool:
        """Check if there's a citation within or near the text span."""
        for cite_start, cite_end in citations:
            # Citation within span
            if start <= cite_start <= end:
                return True
            # Citation immediately follows (within 30 chars)
            if 0 <= cite_start - end <= 30:
                return True
        return False
    
    def _analyze_sentence(
        self,
        sentence: str,
        start: int,
        end: int
    ) -> Optional[UnsourcedClaim]:
        """Analyze a sentence for citation-worthy claims."""
        # Skip very short sentences
        if len(sentence.strip()) < 20:
            return None
        
        # Check for quotations first
        if self.quote_pattern.search(sentence):
            return UnsourcedClaim(
                text=sentence.strip(),
                position_start=start,
                position_end=end,
                claim_type="quotation",
                confidence=0.95,
                suggested_search_terms=self._extract_quote_terms(sentence),
            )
        
        # Check for legal claims
        for pattern in self.legal_patterns:
            if pattern.search(sentence):
                return UnsourcedClaim(
                    text=sentence.strip(),
                    position_start=start,
                    position_end=end,
                    claim_type="legal",
                    confidence=0.85,
                    suggested_search_terms=self._extract_legal_terms(sentence),
                )
        
        # Check for statistical claims
        for pattern in self.stat_patterns:
            if pattern.search(sentence):
                return UnsourcedClaim(
                    text=sentence.strip(),
                    position_start=start,
                    position_end=end,
                    claim_type="statistical",
                    confidence=0.90,
                    suggested_search_terms=self._extract_general_terms(sentence),
                )
        
        # Check for factual claims
        for pattern in self.fact_patterns:
            if pattern.search(sentence):
                return UnsourcedClaim(
                    text=sentence.strip(),
                    position_start=start,
                    position_end=end,
                    claim_type="factual",
                    confidence=0.70,
                    suggested_search_terms=self._extract_general_terms(sentence),
                )
        
        return None
    
    def _extract_quote_terms(self, sentence: str) -> List[str]:
        """Extract search terms from a quotation."""
        match = self.quote_pattern.search(sentence)
        if match:
            quote = match.group(0).strip('"')
            # Return first few words for search
            words = quote.split()[:6]
            return [" ".join(words)]
        return []
    
    def _extract_legal_terms(self, sentence: str) -> List[str]:
        """Extract legal search terms."""
        terms = []
        
        # Look for case names
        case_pattern = r'([A-Z][a-zA-Z]+)\s+v\.\s+([A-Z][a-zA-Z]+)'
        for match in re.finditer(case_pattern, sentence):
            terms.append(f"{match.group(1)} v. {match.group(2)}")
        
        # Legal concepts
        legal_concepts = [
            "due process", "equal protection", "free speech", "establishment clause",
            "commerce clause", "supremacy clause", "strict scrutiny", "rational basis",
            "standing", "mootness", "ripeness", "sovereign immunity", "qualified immunity",
            "probable cause", "reasonable suspicion", "exigent circumstances",
        ]
        
        sentence_lower = sentence.lower()
        for concept in legal_concepts:
            if concept in sentence_lower:
                terms.append(concept)
        
        return terms if terms else self._extract_general_terms(sentence)[:3]
    
    def _extract_general_terms(self, sentence: str) -> List[str]:
        """Extract general search terms."""
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'it', 'that', 'this',
            'as', 'of', 'to', 'in', 'for', 'on', 'with', 'by', 'from', 'at',
            'and', 'or', 'but', 'not', 'be', 'been', 'being', 'have', 'has',
            'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'may', 'might', 'must', 'shall', 'can', 'need', 'there', 'here',
        }

        words = re.findall(r'\b[a-zA-Z]{4,}\b', sentence.lower())
        key_terms = [w for w in words if w not in stop_words]

        return list(dict.fromkeys(key_terms))[:5]


class SourceFinder:
    """
    Automatically finds potential sources for unsourced claims.

    Integrates with legal databases to suggest actual citations
    for claims that need supporting authority.
    """

    def __init__(self, lookup_service=None):
        """
        Initialize with optional lookup service.

        Args:
            lookup_service: LegalLookupService instance for database queries
        """
        self.lookup_service = lookup_service
        self.claim_detector = ClaimDetector()

    async def find_sources_for_claims(
        self,
        claims: List[UnsourcedClaim],
        max_suggestions: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find potential sources for a list of unsourced claims.

        Returns enriched claims with suggested sources.
        """
        results = []

        for claim in claims:
            result = await self.find_sources_for_claim(claim, max_suggestions)
            results.append(result)

        return results

    async def find_sources_for_claim(
        self,
        claim: UnsourcedClaim,
        max_suggestions: int = 3
    ) -> Dict[str, Any]:
        """
        Find potential sources for a single unsourced claim.

        Uses claim type to determine search strategy.
        """
        result = {
            "claim_id": claim.id,
            "claim_text": claim.text,
            "claim_type": claim.claim_type,
            "search_terms": claim.suggested_search_terms,
            "suggested_sources": [],
            "suggested_citations": [],
        }

        if not self.lookup_service:
            return result

        # Different strategies based on claim type
        if claim.claim_type == "legal":
            sources = await self._find_legal_sources(claim, max_suggestions)
        elif claim.claim_type == "quotation":
            sources = await self._find_quotation_source(claim)
        elif claim.claim_type == "statistical":
            sources = await self._find_statistical_sources(claim, max_suggestions)
        else:  # factual
            sources = await self._find_factual_sources(claim, max_suggestions)

        result["suggested_sources"] = sources
        result["suggested_citations"] = self._format_suggested_citations(sources)

        return result

    async def _find_legal_sources(
        self,
        claim: UnsourcedClaim,
        max_suggestions: int
    ) -> List[Dict]:
        """Find case law and statutory sources for legal claims."""
        sources = []

        # Search for cases using legal terms
        search_terms = claim.suggested_search_terms or []

        # Try case name patterns first
        case_name_patterns = [
            term for term in search_terms
            if " v. " in term or " v " in term
        ]

        for term in case_name_patterns[:2]:
            try:
                result = await self.lookup_service.search_by_text(term, "case")
                if result.get("found"):
                    for suggestion in result.get("suggestions", [])[:max_suggestions]:
                        suggestion["source_type"] = "case"
                        suggestion["relevance"] = "high"
                        sources.append(suggestion)
            except Exception:
                pass

        # Try legal concept searches
        legal_concepts = [
            term for term in search_terms
            if term not in case_name_patterns and len(term) > 3
        ]

        for concept in legal_concepts[:3]:
            try:
                result = await self.lookup_service._search_case_by_text(concept)
                if result.get("found"):
                    for suggestion in result.get("suggestions", [])[:2]:
                        suggestion["source_type"] = "case"
                        suggestion["relevance"] = "medium"
                        suggestion["matched_concept"] = concept
                        if suggestion not in sources:
                            sources.append(suggestion)
            except Exception:
                pass

        return sources[:max_suggestions]

    async def _find_quotation_source(self, claim: UnsourcedClaim) -> List[Dict]:
        """Find the source of a quotation."""
        sources = []

        # Extract the quoted text
        quote_match = re.search(r'"([^"]+)"', claim.text)
        if not quote_match:
            return sources

        quote_text = quote_match.group(1)

        # Search for the quote in cases
        try:
            result = await self.lookup_service._search_case_by_text(quote_text[:100])
            if result.get("found"):
                for suggestion in result.get("suggestions", [])[:3]:
                    suggestion["source_type"] = "case"
                    suggestion["matched_quote"] = True
                    sources.append(suggestion)
        except Exception:
            pass

        # Also try article search
        try:
            result = await self.lookup_service._search_article_by_text(quote_text[:100])
            if result.get("found"):
                for suggestion in result.get("suggestions", [])[:2]:
                    suggestion["source_type"] = "article"
                    suggestion["matched_quote"] = True
                    sources.append(suggestion)
        except Exception:
            pass

        return sources

    async def _find_statistical_sources(
        self,
        claim: UnsourcedClaim,
        max_suggestions: int
    ) -> List[Dict]:
        """Find sources for statistical claims."""
        sources = []

        # Statistical claims often cite studies or government sources
        search_terms = claim.suggested_search_terms or []

        # Try article/study search
        for term in search_terms[:3]:
            try:
                result = await self.lookup_service._search_article_by_text(
                    f"{term} study statistics"
                )
                if result.get("found"):
                    for suggestion in result.get("suggestions", [])[:2]:
                        suggestion["source_type"] = "study"
                        suggestion["relevance"] = "medium"
                        sources.append(suggestion)
            except Exception:
                pass

        return sources[:max_suggestions]

    async def _find_factual_sources(
        self,
        claim: UnsourcedClaim,
        max_suggestions: int
    ) -> List[Dict]:
        """Find sources for general factual claims."""
        sources = []

        search_terms = claim.suggested_search_terms or []

        # Try multiple source types
        for term in search_terms[:2]:
            # Cases
            try:
                result = await self.lookup_service._search_case_by_text(term)
                if result.get("found"):
                    for suggestion in result.get("suggestions", [])[:1]:
                        suggestion["source_type"] = "case"
                        sources.append(suggestion)
            except Exception:
                pass

            # Articles
            try:
                result = await self.lookup_service._search_article_by_text(term)
                if result.get("found"):
                    for suggestion in result.get("suggestions", [])[:1]:
                        suggestion["source_type"] = "article"
                        sources.append(suggestion)
            except Exception:
                pass

        return sources[:max_suggestions]

    def _format_suggested_citations(self, sources: List[Dict]) -> List[str]:
        """Format found sources as Bluebook citations."""
        citations = []

        for source in sources:
            source_type = source.get("source_type", "")

            if source_type == "case":
                # Format case citation
                case_name = source.get("case_name", "")
                cite_list = source.get("citation", [])
                date_filed = source.get("date_filed", "")

                if case_name and cite_list:
                    cite_str = cite_list[0] if isinstance(cite_list, list) else str(cite_list)
                    year = date_filed[:4] if date_filed else ""
                    formatted = f"*{case_name}*, {cite_str}"
                    if year:
                        formatted += f" ({year})"
                    citations.append(formatted)

            elif source_type in ["article", "study"]:
                # Format article citation
                author = source.get("author", "")
                title = source.get("title", "")
                journal = source.get("container_title", "")
                volume = source.get("volume", "")
                page = source.get("page", "")
                year = source.get("year", "")

                if author and title:
                    formatted = f"{author}, *{title}*"
                    if volume and journal and page:
                        formatted += f", {volume} {journal} {page}"
                    if year:
                        formatted += f" ({year})"
                    citations.append(formatted)

        return citations

    async def analyze_document_for_sources(
        self,
        text: str,
        existing_citations: List[Tuple[int, int]]
    ) -> Dict[str, Any]:
        """
        Comprehensive analysis of a document's unsourced claims
        with automatic source suggestions.

        Returns:
            Dict with claims, sources, and statistics
        """
        # Detect unsourced claims
        claims = self.claim_detector.detect_unsourced_claims(text, existing_citations)

        # Find sources for each claim
        enriched_claims = await self.find_sources_for_claims(claims)

        # Calculate statistics
        claims_with_sources = sum(
            1 for c in enriched_claims
            if c.get("suggested_sources")
        )

        return {
            "total_claims": len(claims),
            "claims_with_suggestions": claims_with_sources,
            "claims": enriched_claims,
            "priority_claims": [
                c for c in enriched_claims
                if c.get("suggested_sources") or c["claim_type"] in ["quotation", "legal"]
            ],
        }
