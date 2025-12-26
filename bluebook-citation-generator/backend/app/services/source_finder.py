"""
Unsourced claim detection and source suggestion.
"""

import re
from typing import List, Tuple, Optional
from ..models.citation import UnsourcedClaim

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
