"""
Legal database lookup service using free APIs.
No API keys required.

Enhanced with:
- Smarter search strategies for minimal input
- URL metadata extraction
- Fuzzy matching for case names
- Multiple fallback sources
"""

import httpx
import asyncio
import re
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse
from ..models.citation import Citation, CitationType, CitationStatus

class LegalLookupService:
    """
    Integrates with free legal databases to look up and verify citations.
    
    Sources (all free, no auth required):
    - CourtListener API: Comprehensive case law
    - CrossRef API: Academic articles
    - Open Library API: Books
    - eCFR API: Federal regulations
    - U.S. Code (Cornell Law): Federal statutes
    """
    
    def __init__(self):
        self.courtlistener_base = "https://www.courtlistener.com/api/rest/v3"
        self.crossref_base = "https://api.crossref.org/works"
        self.openlibrary_base = "https://openlibrary.org"
        self.ecfr_base = "https://www.ecfr.gov/api/versioner/v1"
        
        self.client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": "BluebookCitationGenerator/1.0 (Legal Research Tool)"
                }
            )
        return self.client
    
    async def lookup_citation(self, citation: Citation) -> Dict[str, Any]:
        """Route to appropriate lookup based on citation type."""
        lookup_methods = {
            CitationType.CASE: self._lookup_case,
            CitationType.STATUTE: self._lookup_statute,
            CitationType.REGULATION: self._lookup_regulation,
            CitationType.LAW_REVIEW: self._lookup_article,
            CitationType.BOOK: self._lookup_book,
        }
        
        method = lookup_methods.get(citation.type, self._no_lookup)
        return await method(citation)
    
    async def _lookup_case(self, citation: Citation) -> Dict[str, Any]:
        """Look up case in CourtListener."""
        results = {"found": False, "data": None, "suggestions": [], "source": "CourtListener"}
        
        try:
            client = await self._get_client()
            
            # Build search query
            search_params = {"type": "o", "order_by": "score desc"}
            
            # Try citation string first
            if citation.volume and citation.reporter and citation.page:
                cite_string = f"{citation.volume} {citation.reporter} {citation.page}"
                search_params["citation"] = cite_string
            elif citation.parties and len(citation.parties) >= 2:
                # Fallback to case name
                case_name = f"{citation.parties[0]} v. {citation.parties[1]}"
                search_params["case_name"] = case_name
            else:
                return results
            
            response = await client.get(
                f"{self.courtlistener_base}/search/",
                params=search_params
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    for result in data["results"][:5]:
                        parsed = self._parse_courtlistener_result(result)
                        results["suggestions"].append(parsed)
                    
                    results["found"] = True
                    results["data"] = results["suggestions"][0]
        
        except Exception as e:
            results["error"] = str(e)
        
        return results
    
    def _parse_courtlistener_result(self, result: dict) -> Dict[str, Any]:
        """Parse CourtListener API result."""
        return {
            "case_name": result.get("caseName", ""),
            "citation": result.get("citation", []),
            "court": result.get("court", ""),
            "court_id": result.get("court_id", ""),
            "date_filed": result.get("dateFiled", ""),
            "docket_number": result.get("docketNumber", ""),
            "absolute_url": f"https://www.courtlistener.com{result.get('absolute_url', '')}",
            "snippet": result.get("snippet", ""),
            "judge": result.get("judge", ""),
        }
    
    async def _lookup_statute(self, citation: Citation) -> Dict[str, Any]:
        """Look up federal statute."""
        results = {"found": False, "data": None, "suggestions": [], "source": "Cornell Law"}
        
        if citation.title_number and citation.section:
            # Cornell Law School has reliable U.S. Code links
            results["found"] = True
            results["data"] = {
                "title": citation.title_number,
                "section": citation.section,
                "code": citation.code or "U.S.C.",
                "url": f"https://www.law.cornell.edu/uscode/text/{citation.title_number}/{citation.section}",
                "govinfo_url": f"https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title{citation.title_number}-section{citation.section}",
            }
        
        return results
    
    async def _lookup_regulation(self, citation: Citation) -> Dict[str, Any]:
        """Look up federal regulation in eCFR."""
        results = {"found": False, "data": None, "suggestions": [], "source": "eCFR"}
        
        if citation.title_number and citation.section:
            try:
                client = await self._get_client()
                
                # Try eCFR API
                response = await client.get(
                    f"{self.ecfr_base}/full/{citation.title_number}/section-{citation.section}.json"
                )
                
                if response.status_code == 200:
                    results["found"] = True
                    results["data"] = response.json()
                else:
                    # Fallback to providing links
                    results["found"] = True
                    results["data"] = {
                        "title": citation.title_number,
                        "section": citation.section,
                        "ecfr_url": f"https://www.ecfr.gov/current/title-{citation.title_number}/section-{citation.section}",
                        "cornell_url": f"https://www.law.cornell.edu/cfr/text/{citation.title_number}/{citation.section}",
                    }
            
            except Exception as e:
                results["found"] = True
                results["data"] = {
                    "title": citation.title_number,
                    "section": citation.section,
                    "ecfr_url": f"https://www.ecfr.gov/current/title-{citation.title_number}/section-{citation.section}",
                    "cornell_url": f"https://www.law.cornell.edu/cfr/text/{citation.title_number}/{citation.section}",
                }
        
        return results
    
    async def _lookup_article(self, citation: Citation) -> Dict[str, Any]:
        """Look up law review article via CrossRef."""
        results = {"found": False, "data": None, "suggestions": [], "source": "CrossRef"}
        
        query_parts = []
        if citation.author:
            query_parts.append(citation.author)
        if citation.title:
            query_parts.append(citation.title)
        
        if not query_parts:
            return results
        
        try:
            client = await self._get_client()
            
            response = await client.get(
                self.crossref_base,
                params={
                    "query": " ".join(query_parts),
                    "rows": 5,
                    "select": "title,author,container-title,volume,page,published,DOI,URL",
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("message", {}).get("items", [])
                
                for item in items:
                    suggestion = {
                        "title": item.get("title", [""])[0] if item.get("title") else "",
                        "author": self._format_crossref_authors(item.get("author", [])),
                        "container_title": item.get("container-title", [""])[0] if item.get("container-title") else "",
                        "volume": item.get("volume", ""),
                        "page": item.get("page", ""),
                        "year": self._extract_crossref_year(item.get("published", {})),
                        "doi": item.get("DOI", ""),
                        "url": item.get("URL", ""),
                    }
                    results["suggestions"].append(suggestion)
                
                if results["suggestions"]:
                    results["found"] = True
                    results["data"] = results["suggestions"][0]
        
        except Exception as e:
            results["error"] = str(e)
        
        return results
    
    def _format_crossref_authors(self, authors: List[dict]) -> str:
        """Format CrossRef author list to Bluebook style."""
        if not authors:
            return ""
        
        formatted = []
        for author in authors[:3]:  # Limit to first 3 authors
            given = author.get("given", "")
            family = author.get("family", "")
            if given and family:
                formatted.append(f"{given} {family}")
            elif family:
                formatted.append(family)
        
        if len(formatted) == 1:
            return formatted[0]
        elif len(formatted) == 2:
            return f"{formatted[0]} & {formatted[1]}"
        elif len(formatted) >= 3:
            if len(authors) > 3:
                return f"{formatted[0]} et al."
            return f"{', '.join(formatted[:-1])} & {formatted[-1]}"
        return ""
    
    def _extract_crossref_year(self, published: dict) -> Optional[int]:
        """Extract year from CrossRef date format."""
        date_parts = published.get("date-parts", [[]])
        if date_parts and date_parts[0]:
            return date_parts[0][0]
        return None
    
    async def _lookup_book(self, citation: Citation) -> Dict[str, Any]:
        """Look up book via Open Library."""
        results = {"found": False, "data": None, "suggestions": [], "source": "Open Library"}
        
        query_parts = []
        if citation.author:
            query_parts.append(f"author:{citation.author}")
        if citation.title:
            query_parts.append(f"title:{citation.title}")
        
        if not query_parts:
            return results
        
        try:
            client = await self._get_client()
            
            response = await client.get(
                f"{self.openlibrary_base}/search.json",
                params={
                    "q": " ".join(query_parts),
                    "limit": 5,
                    "fields": "title,author_name,publisher,first_publish_year,isbn,key",
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                docs = data.get("docs", [])
                
                for doc in docs:
                    suggestion = {
                        "title": doc.get("title", ""),
                        "author": ", ".join(doc.get("author_name", [])[:2]),
                        "publisher": doc.get("publisher", [""])[0] if doc.get("publisher") else "",
                        "year": doc.get("first_publish_year"),
                        "isbn": doc.get("isbn", [""])[0] if doc.get("isbn") else None,
                        "openlibrary_key": doc.get("key", ""),
                        "url": f"https://openlibrary.org{doc.get('key', '')}" if doc.get("key") else "",
                    }
                    results["suggestions"].append(suggestion)
                
                if results["suggestions"]:
                    results["found"] = True
                    results["data"] = results["suggestions"][0]
        
        except Exception as e:
            results["error"] = str(e)
        
        return results
    
    async def _no_lookup(self, citation: Citation) -> Dict[str, Any]:
        """Fallback for unsupported citation types."""
        return {"found": False, "data": None, "suggestions": [], "source": None}

    async def lookup_website(self, citation: Citation) -> Dict[str, Any]:
        """Extract metadata from a URL to complete website citations."""
        results = {"found": False, "data": None, "suggestions": [], "source": "URL Metadata"}

        if not citation.url:
            return results

        try:
            client = await self._get_client()
            response = await client.get(citation.url, follow_redirects=True)

            if response.status_code == 200:
                html = response.text

                # Extract title
                title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else None

                # Extract meta author
                author_match = re.search(
                    r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)["\']',
                    html, re.IGNORECASE
                )
                if not author_match:
                    author_match = re.search(
                        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']author["\']',
                        html, re.IGNORECASE
                    )
                author = author_match.group(1).strip() if author_match else None

                # Extract publication date
                date_match = re.search(
                    r'<meta[^>]+(?:property=["\']article:published_time["\']|name=["\']date["\'])[^>]+content=["\']([^"\']+)["\']',
                    html, re.IGNORECASE
                )
                pub_date = date_match.group(1)[:10] if date_match else None

                # Get site name from og:site_name or domain
                site_match = re.search(
                    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']',
                    html, re.IGNORECASE
                )
                site_name = site_match.group(1) if site_match else urlparse(citation.url).netloc

                results["found"] = True
                results["data"] = {
                    "title": title,
                    "author": author,
                    "publication_date": pub_date,
                    "site_name": site_name,
                    "url": citation.url,
                }
        except Exception as e:
            results["error"] = str(e)

        return results

    async def search_by_text(self, search_text: str, search_type: str = "case") -> Dict[str, Any]:
        """
        Search for citations using free-form text.
        Useful when user just has a title, quote, or partial info.
        """
        results = {"found": False, "data": None, "suggestions": [], "source": None}

        if not search_text or len(search_text.strip()) < 3:
            return results

        search_text = search_text.strip()

        if search_type == "case":
            results = await self._search_case_by_text(search_text)
        elif search_type == "article":
            results = await self._search_article_by_text(search_text)
        elif search_type == "statute":
            results = await self._parse_statute_from_text(search_text)

        return results

    async def _search_case_by_text(self, text: str) -> Dict[str, Any]:
        """Search CourtListener with free-form text."""
        results = {"found": False, "data": None, "suggestions": [], "source": "CourtListener"}

        try:
            client = await self._get_client()

            # Try multiple search strategies
            search_queries = self._generate_case_search_queries(text)

            for query in search_queries:
                response = await client.get(
                    f"{self.courtlistener_base}/search/",
                    params={"q": query, "type": "o", "order_by": "score desc"}
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("results"):
                        for result in data["results"][:5]:
                            parsed = self._parse_courtlistener_result(result)
                            if parsed not in results["suggestions"]:
                                results["suggestions"].append(parsed)

                        if results["suggestions"]:
                            results["found"] = True
                            results["data"] = results["suggestions"][0]
                            break

        except Exception as e:
            results["error"] = str(e)

        return results

    def _generate_case_search_queries(self, text: str) -> List[str]:
        """Generate multiple search query variations for better matching."""
        queries = [text]

        # Check if it looks like a case name
        if " v. " in text or " v " in text:
            # Extract party names
            parts = re.split(r'\s+v\.?\s+', text, maxsplit=1)
            if len(parts) == 2:
                # Try just the party names
                queries.append(f'"{parts[0]}" "{parts[1]}"')
                # Try with v.
                queries.append(f"{parts[0]} v. {parts[1]}")

        # If it contains a year, try searching with it
        year_match = re.search(r'\b(19|20)\d{2}\b', text)
        if year_match:
            year = year_match.group(0)
            text_without_year = text.replace(year, "").strip()
            queries.append(f"{text_without_year} {year}")

        # Try removing common legal words that might interfere
        clean_text = re.sub(r'\b(Inc\.|Corp\.|Co\.|Ltd\.)\b', '', text)
        if clean_text != text:
            queries.append(clean_text.strip())

        return queries

    async def _search_article_by_text(self, text: str) -> Dict[str, Any]:
        """Search CrossRef with free-form text."""
        results = {"found": False, "data": None, "suggestions": [], "source": "CrossRef"}

        try:
            client = await self._get_client()

            # Filter to legal/law journals
            response = await client.get(
                self.crossref_base,
                params={
                    "query": text,
                    "rows": 10,
                    "filter": "type:journal-article",
                    "select": "title,author,container-title,volume,page,published,DOI,URL",
                }
            )

            if response.status_code == 200:
                data = response.json()
                items = data.get("message", {}).get("items", [])

                # Prioritize law journals
                law_items = []
                other_items = []

                for item in items:
                    container = item.get("container-title", [""])[0].lower() if item.get("container-title") else ""
                    if any(term in container for term in ["law", "legal", "juris", "journal"]):
                        law_items.append(item)
                    else:
                        other_items.append(item)

                for item in (law_items + other_items)[:5]:
                    suggestion = {
                        "title": item.get("title", [""])[0] if item.get("title") else "",
                        "author": self._format_crossref_authors(item.get("author", [])),
                        "container_title": item.get("container-title", [""])[0] if item.get("container-title") else "",
                        "volume": item.get("volume", ""),
                        "page": item.get("page", ""),
                        "year": self._extract_crossref_year(item.get("published", {})),
                        "doi": item.get("DOI", ""),
                        "url": item.get("URL", ""),
                    }
                    results["suggestions"].append(suggestion)

                if results["suggestions"]:
                    results["found"] = True
                    results["data"] = results["suggestions"][0]

        except Exception as e:
            results["error"] = str(e)

        return results

    async def _parse_statute_from_text(self, text: str) -> Dict[str, Any]:
        """Try to parse statute info from free-form text."""
        results = {"found": False, "data": None, "suggestions": [], "source": "Cornell Law"}

        # Try to extract USC citation
        usc_match = re.search(r'(\d+)\s*U\.?S\.?C\.?\s*§?\s*(\d+[a-z]?)', text, re.IGNORECASE)
        if usc_match:
            title = usc_match.group(1)
            section = usc_match.group(2)

            results["found"] = True
            results["data"] = {
                "title": title,
                "section": section,
                "code": "U.S.C.",
                "url": f"https://www.law.cornell.edu/uscode/text/{title}/{section}",
            }
            return results

        # Try CFR
        cfr_match = re.search(r'(\d+)\s*C\.?F\.?R\.?\s*§?\s*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if cfr_match:
            title = cfr_match.group(1)
            section = cfr_match.group(2)

            results["found"] = True
            results["source"] = "eCFR"
            results["data"] = {
                "title": title,
                "section": section,
                "code": "C.F.R.",
                "url": f"https://www.ecfr.gov/current/title-{title}/section-{section}",
            }

        return results

    async def smart_complete(self, citation: Citation) -> Dict[str, Any]:
        """
        Intelligently complete a citation using multiple strategies.
        Tries different approaches based on what info is available.
        """
        results = {"found": False, "data": None, "suggestions": [], "strategies_tried": []}

        # Strategy 1: Use existing lookup if we have structured data
        if citation.type != CitationType.OTHER:
            lookup_result = await self.lookup_citation(citation)
            results["strategies_tried"].append("structured_lookup")
            if lookup_result.get("found"):
                return lookup_result

        # Strategy 2: Try URL metadata extraction for websites
        if citation.url:
            url_result = await self.lookup_website(citation)
            results["strategies_tried"].append("url_metadata")
            if url_result.get("found"):
                return url_result

        # Strategy 3: Search by raw text
        if citation.raw_text:
            raw_text = citation.raw_text.strip()

            # Check if it looks like a case
            if " v. " in raw_text or " v " in raw_text:
                case_result = await self.search_by_text(raw_text, "case")
                results["strategies_tried"].append("case_text_search")
                if case_result.get("found"):
                    case_result["inferred_type"] = "case"
                    return case_result

            # Check if it looks like a statute
            if re.search(r'\b(U\.?S\.?C|C\.?F\.?R|Code|§)', raw_text, re.IGNORECASE):
                statute_result = await self.search_by_text(raw_text, "statute")
                results["strategies_tried"].append("statute_text_search")
                if statute_result.get("found"):
                    statute_result["inferred_type"] = "statute"
                    return statute_result

            # Try as article
            article_result = await self.search_by_text(raw_text, "article")
            results["strategies_tried"].append("article_text_search")
            if article_result.get("found"):
                article_result["inferred_type"] = "law_review"
                return article_result

            # Last resort: generic case search
            case_result = await self.search_by_text(raw_text, "case")
            results["strategies_tried"].append("fallback_case_search")
            if case_result.get("found"):
                return case_result

        return results

    async def close(self) -> None:
        """Close the HTTP client."""
        if self.client and not self.client.is_closed:
            await self.client.aclose()


class CitationCompleter:
    """Completes incomplete citations using lookup results."""

    def __init__(self, lookup_service: LegalLookupService):
        self.lookup = lookup_service

    async def complete_citation(self, citation: Citation) -> Citation:
        """Attempt to complete an incomplete citation using smart lookup."""
        if citation.status.value == "complete":
            return citation

        # Try smart completion first (uses multiple strategies)
        results = await self.lookup.smart_complete(citation)

        # If smart complete found nothing, try basic lookup
        if not results.get("found"):
            results = await self.lookup.lookup_citation(citation)

        if results.get("found") and results.get("data"):
            # Update citation type if it was inferred
            if results.get("inferred_type"):
                citation.type = CitationType(results["inferred_type"])

            citation = self._merge_lookup_data(citation, results["data"])
            citation.lookup_results = results
            citation.confidence_score = self._calculate_confidence(citation, results)

            if citation.confidence_score > 0.8:
                citation.status = CitationStatus.COMPLETE
            else:
                citation.status = CitationStatus.NEEDS_VERIFICATION

        return citation

    async def complete_from_text(self, text: str) -> Tuple[Optional[Citation], Dict[str, Any]]:
        """
        Create and complete a citation from raw text input.
        Useful when user just pastes a case name, title, or URL.
        """
        # Create a minimal citation object
        citation = Citation(
            type=CitationType.OTHER,
            status=CitationStatus.INCOMPLETE,
            raw_text=text,
            position_start=0,
            position_end=len(text),
        )

        # Check if it's a URL
        if text.startswith("http://") or text.startswith("https://"):
            citation.type = CitationType.WEBSITE
            citation.url = text

        # Use smart completion
        results = await self.lookup.smart_complete(citation)

        if results.get("found") and results.get("data"):
            if results.get("inferred_type"):
                citation.type = CitationType(results["inferred_type"])

            citation = self._merge_lookup_data(citation, results["data"])
            citation.lookup_results = results
            citation.confidence_score = self._calculate_confidence(citation, results)

            if citation.confidence_score > 0.8:
                citation.status = CitationStatus.COMPLETE
            else:
                citation.status = CitationStatus.NEEDS_VERIFICATION

        return citation, results
    
    def _merge_lookup_data(self, citation: Citation, data: dict) -> Citation:
        """Merge lookup data into citation, filling gaps."""
        if citation.type == CitationType.CASE:
            if not citation.parties and data.get("case_name"):
                parts = data["case_name"].split(" v. ")
                if len(parts) == 2:
                    citation.parties = [p.strip() for p in parts]
            
            if data.get("citation") and isinstance(data["citation"], list):
                for cite in data["citation"]:
                    if isinstance(cite, str):
                        # Parse citation string
                        import re
                        match = re.match(r"(\d+)\s+([A-Za-z.\s]+)\s+(\d+)", cite)
                        if match:
                            if not citation.volume:
                                citation.volume = match.group(1)
                            if not citation.reporter:
                                citation.reporter = match.group(2).strip()
                            if not citation.page:
                                citation.page = match.group(3)
                            break
            
            if not citation.year and data.get("date_filed"):
                try:
                    citation.year = int(data["date_filed"][:4])
                except (ValueError, TypeError):
                    pass
            
            if not citation.court and data.get("court"):
                citation.court = data["court"]
        
        elif citation.type == CitationType.LAW_REVIEW:
            if not citation.author and data.get("author"):
                citation.author = data["author"]
            if not citation.title and data.get("title"):
                citation.title = data["title"]
            if not citation.journal and data.get("container_title"):
                citation.journal = data["container_title"]
            if not citation.volume and data.get("volume"):
                citation.volume = str(data["volume"])
            if not citation.page and data.get("page"):
                page = data["page"]
                if "-" in str(page):
                    citation.page = str(page).split("-")[0]
                else:
                    citation.page = str(page)
            if not citation.year and data.get("year"):
                citation.year = data["year"]
        
        elif citation.type == CitationType.BOOK:
            if not citation.author and data.get("author"):
                citation.author = data["author"]
            if not citation.title and data.get("title"):
                citation.title = data["title"]
            if not citation.publisher and data.get("publisher"):
                citation.publisher = data["publisher"]
            if not citation.year and data.get("year"):
                citation.year = data["year"]

        elif citation.type == CitationType.WEBSITE:
            if not citation.author and data.get("author"):
                citation.author = data["author"]
            if not citation.title and data.get("title"):
                citation.title = data["title"]
            if not citation.url and data.get("url"):
                citation.url = data["url"]
            if not citation.access_date and data.get("publication_date"):
                citation.access_date = data["publication_date"]

        return citation
    
    def _calculate_confidence(self, citation: Citation, results: dict) -> float:
        """Calculate confidence score for completed citation."""
        required_fields = {
            CitationType.CASE: ["parties", "volume", "reporter", "page", "year"],
            CitationType.LAW_REVIEW: ["author", "title", "volume", "journal", "page", "year"],
            CitationType.STATUTE: ["title_number", "code", "section"],
            CitationType.REGULATION: ["title_number", "section"],
            CitationType.BOOK: ["author", "title", "year"],
        }
        
        fields = required_fields.get(citation.type, [])
        if not fields:
            return 0.5
        
        filled = sum(1 for f in fields if getattr(citation, f, None))
        score = filled / len(fields)
        
        # Boost if lookup found results
        if results.get("found"):
            score = min(1.0, score + 0.15)
        
        return score
