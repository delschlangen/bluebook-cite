"""Tests for the relevance floor that prevents fabricated citations.

Search APIs rank by relevance and return their best guess for any string.
Treating "the API returned a row" as "we found the source" is how a case name
became an unrelated journal article in production. These tests pin the floor.

All HTTP is mocked. Nothing here touches a live API.
"""

import httpx
import pytest
import respx

from app.models.citation import Citation, CitationStatus, CitationType
from app.services.lookup_service import (
    CONFIDENT_MATCH_THRESHOLD,
    MATCH_THRESHOLD,
    LegalLookupService,
    match_score,
)

CROSSREF = "https://api.crossref.org/works"
COURTLISTENER = "https://www.courtlistener.com/api/rest/v3/search/"


class TestMatchScore:
    def test_exact_match_scores_one(self):
        assert match_score("Brandenburg v. Ohio", "Brandenburg v. Ohio") == 1.0

    def test_close_match_clears_confident_bar(self):
        score = match_score("Moody v. NetChoice", "Moody v. NetChoice, LLC")
        assert score >= CONFIDENT_MATCH_THRESHOLD

    @pytest.mark.parametrize(
        "query,candidate",
        [
            # The two fabrications seen in the deployed app.
            (
                "In Gonzalez v. Google",
                "Beyond the Editorial Analogy: First Amendment Protections for "
                "Platform Content Moderation",
            ),
            (
                "The Supreme Court recently granted certiorari in Moody. "
                "Research indicates that content moderation decisions affect",
                "Beyond the Editorial Analogy After Moody v. NetChoice",
            ),
        ],
    )
    def test_known_fabrications_fall_below_the_floor(self, query, candidate):
        assert match_score(query, candidate) < MATCH_THRESHOLD

    @pytest.mark.parametrize("query", ["", "   ", "the a of and", "v."])
    def test_empty_or_stopword_query_scores_zero(self, query):
        assert match_score(query, "Some Perfectly Real Article Title") == 0.0

    def test_empty_candidate_scores_zero(self):
        assert match_score("Brandenburg v. Ohio", "") == 0.0

    def test_score_is_bounded(self):
        for q, c in [("a b c", "x y z"), ("Ohio", "Ohio"), ("", "")]:
            assert 0.0 <= match_score(q, c) <= 1.0


def _crossref_payload(*titles):
    return {
        "message": {
            "items": [
                {
                    "title": [t],
                    "author": [{"given": "A.", "family": "Author"}],
                    "container-title": ["Some Law Review"],
                    "volume": "51",
                    "page": "1149",
                    "published": {"date-parts": [[2018]]},
                    "DOI": "10.0000/test",
                    "URL": "https://doi.org/10.0000/test",
                }
                for t in titles
            ]
        }
    }


def _courtlistener_payload(*case_names):
    return {
        "results": [
            {
                "caseName": name,
                "citation": ["395 U.S. 444"],
                "court": "Supreme Court",
                "dateFiled": "1969-06-09",
                "absolute_url": "/opinion/1/test/",
            }
            for name in case_names
        ]
    }


@pytest.mark.asyncio
class TestArticleSearchRejectsIrrelevantHits:
    @respx.mock
    async def test_unrelated_article_is_not_reported_as_found(self):
        respx.get(CROSSREF).mock(
            return_value=httpx.Response(
                200,
                json=_crossref_payload(
                    "Beyond the Editorial Analogy: First Amendment Protections "
                    "for Platform Content Moderation"
                ),
            )
        )
        service = LegalLookupService()
        try:
            result = await service._search_article_by_text("In Gonzalez v. Google")
        finally:
            await service.close()

        assert result["found"] is False
        assert result["data"] is None
        assert result["suggestions"] == []
        assert result["rejected_count"] == 1

    @respx.mock
    async def test_genuinely_matching_article_is_found(self):
        title = "Free Speech in the Algorithmic Society"
        respx.get(CROSSREF).mock(
            return_value=httpx.Response(200, json=_crossref_payload(title))
        )
        service = LegalLookupService()
        try:
            result = await service._search_article_by_text(title)
        finally:
            await service.close()

        assert result["found"] is True
        assert result["data"]["title"] == title
        assert result["confidence"] >= CONFIDENT_MATCH_THRESHOLD

    @respx.mock
    async def test_empty_api_response_is_not_found(self):
        respx.get(CROSSREF).mock(
            return_value=httpx.Response(200, json={"message": {"items": []}})
        )
        service = LegalLookupService()
        try:
            result = await service._search_article_by_text("anything")
        finally:
            await service.close()
        assert result["found"] is False


@pytest.mark.asyncio
class TestCaseSearchRejectsIrrelevantHits:
    @respx.mock
    async def test_wrong_case_is_not_reported_as_found(self):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(
                200, json=_courtlistener_payload("Roe v. Wade")
            )
        )
        service = LegalLookupService()
        try:
            result = await service._search_case_by_text("Brandenburg v. Ohio")
        finally:
            await service.close()

        assert result["found"] is False
        assert result["data"] is None

    @respx.mock
    async def test_correct_case_is_found(self):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(
                200, json=_courtlistener_payload("Brandenburg v. Ohio")
            )
        )
        service = LegalLookupService()
        try:
            result = await service._search_case_by_text("Brandenburg v. Ohio")
        finally:
            await service.close()

        assert result["found"] is True
        assert result["data"]["case_name"] == "Brandenburg v. Ohio"
        assert result["data"]["absolute_url"].startswith("https://www.courtlistener.com")

    @respx.mock
    async def test_every_returned_candidate_carries_provenance(self):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(
                200, json=_courtlistener_payload("Brandenburg v. Ohio")
            )
        )
        service = LegalLookupService()
        try:
            result = await service._search_case_by_text("Brandenburg v. Ohio")
        finally:
            await service.close()

        for suggestion in result["suggestions"]:
            assert suggestion["absolute_url"], "candidate has no verifiable link"


@pytest.mark.asyncio
class TestSmartCompleteRouting:
    """A case-shaped string must never be answered with a journal article."""

    @respx.mock
    async def test_case_shaped_input_never_hits_crossref(self):
        courtlistener = respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        crossref = respx.get(CROSSREF).mock(
            return_value=httpx.Response(
                200, json=_crossref_payload("Some Unrelated Article")
            )
        )

        citation = Citation(
            type=CitationType.OTHER,
            status=CitationStatus.INCOMPLETE,
            raw_text="In Gonzalez v. Google",
            position_start=0,
            position_end=21,
        )
        service = LegalLookupService()
        try:
            result = await service.smart_complete(citation)
        finally:
            await service.close()

        assert courtlistener.called
        assert not crossref.called, "a case name was searched against a journal index"
        assert result.get("inferred_type") == "case"
        assert result["found"] is False

    @respx.mock
    async def test_unresolvable_input_reports_not_found(self):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        respx.get(CROSSREF).mock(
            return_value=httpx.Response(200, json={"message": {"items": []}})
        )

        citation = Citation(
            type=CitationType.OTHER,
            status=CitationStatus.INCOMPLETE,
            raw_text="some prose that is not a citation at all",
            position_start=0,
            position_end=40,
        )
        service = LegalLookupService()
        try:
            result = await service.smart_complete(citation)
        finally:
            await service.close()

        assert result["found"] is False
        assert result["data"] is None
