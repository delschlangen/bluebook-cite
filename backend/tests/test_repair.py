"""Tests for the single-citation repair endpoint.

The contract these tests defend: a formatted citation is returned only when it
came from the user's own complete input, or from a matched record carrying a
verification URL. There is no third path.
"""

import httpx
import pytest
import respx

from app.models.citation import Citation, CitationStatus, CitationType
from app.services.lookup_service import LegalLookupService
from app.services.repair import (
    INCOMPLETE,
    RESOLVED,
    UNPARSEABLE,
    CitationRepairer,
    missing_fields,
)

COURTLISTENER = "https://www.courtlistener.com/api/rest/v3/search/"
CROSSREF = "https://api.crossref.org/works"


@pytest.fixture
def repairer():
    return CitationRepairer(LegalLookupService())


def test_missing_fields_for_a_bare_case_name():
    citation = Citation(
        type=CitationType.CASE,
        status=CitationStatus.INCOMPLETE,
        raw_text="Moody v. NetChoice",
        position_start=0,
        position_end=18,
        parties=["Moody", "NetChoice"],
    )
    assert missing_fields(citation) == ["volume", "reporter", "page", "year"]


def test_missing_fields_empty_when_complete():
    citation = Citation(
        type=CitationType.CASE,
        status=CitationStatus.COMPLETE,
        raw_text="x",
        position_start=0,
        position_end=1,
        parties=["Moody", "NetChoice"],
        volume="603",
        reporter="U.S.",
        page="707",
        year=2024,
    )
    assert missing_fields(citation) == []


@pytest.mark.asyncio
class TestRepair:
    async def test_empty_input_is_unparseable(self, repairer):
        result = await repairer.repair("   ")
        assert result.status == UNPARSEABLE
        assert result.formatted is None

    async def test_prose_is_unparseable(self, repairer):
        result = await repairer.repair("I need a citation for something about speech")
        assert result.status == UNPARSEABLE
        assert result.formatted is None

    async def test_already_complete_citation_is_formatted_without_lookup(self, repairer):
        # No respx mock is installed, so any HTTP call would raise. Reaching
        # RESOLVED proves the complete path never hits the network.
        result = await repairer.repair("Brandenburg v. Ohio, 395 U.S. 444 (1969)")
        assert result.status == RESOLVED
        assert result.formatted == "*Brandenburg v. Ohio*, 395 U.S. 444 (1969)."
        assert result.missing == []
        assert result.confidence == 1.0

    @respx.mock
    async def test_partial_case_reports_what_is_missing(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await repairer.repair("Moody v. NetChoice")

        assert result.status == INCOMPLETE
        assert result.citation_type == "case"
        assert result.formatted is None
        assert set(result.missing) == {"volume", "reporter", "page", "year"}
        assert "reporter" in result.missing_labels
        assert result.notes

    @respx.mock
    async def test_confident_match_resolves_with_a_verify_url(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "caseName": "Moody v. NetChoice",
                            "citation": ["603 U.S. 707"],
                            "court": "Supreme Court",
                            "dateFiled": "2024-07-01",
                            "absolute_url": "/opinion/9/moody-v-netchoice/",
                        }
                    ]
                },
            )
        )
        result = await repairer.repair("Moody v. NetChoice")

        assert result.status == RESOLVED
        assert result.formatted == "*Moody v. NetChoice*, 603 U.S. 707 (2024)."
        assert result.verify_url.startswith("https://www.courtlistener.com")
        assert result.confidence >= 0.8

    @respx.mock
    async def test_weak_match_is_never_auto_applied(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "caseName": "Roe v. Wade",
                            "citation": ["410 U.S. 113"],
                            "dateFiled": "1973-01-22",
                            "absolute_url": "/opinion/1/roe-v-wade/",
                        }
                    ]
                },
            )
        )
        result = await repairer.repair("Moody v. NetChoice")

        assert result.status != RESOLVED
        assert result.formatted is None

    @respx.mock
    async def test_every_offered_candidate_has_a_verify_url(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "caseName": "Moody v. NetChoice",
                            "citation": ["603 U.S. 707"],
                            "dateFiled": "2024-07-01",
                            "absolute_url": "/opinion/9/moody/",
                        }
                    ]
                },
            )
        )
        result = await repairer.repair("Moody v. NetChoice")
        for candidate in result.candidates:
            assert candidate["verify_url"].startswith("http")

    @respx.mock
    async def test_lookup_failure_still_returns_the_diagnosis(self, repairer):
        respx.get(COURTLISTENER).mock(side_effect=httpx.ConnectError("down"))
        result = await repairer.repair("Moody v. NetChoice")

        assert result.status == INCOMPLETE
        assert set(result.missing) == {"volume", "reporter", "page", "year"}
        assert result.formatted is None

    @respx.mock
    async def test_case_input_never_produces_an_article(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        crossref = respx.get(CROSSREF).mock(
            return_value=httpx.Response(200, json={"message": {"items": []}})
        )
        result = await repairer.repair("Gonzalez v. Google")

        assert not crossref.called
        assert result.citation_type == "case"


class TestRepairEndpoint:
    def test_endpoint_rejects_oversized_input(self):
        from fastapi.testclient import TestClient

        from app.main import MAX_REPAIR_CHARS, app

        with TestClient(app) as client:
            response = client.post(
                "/api/repair", json={"text": "x" * (MAX_REPAIR_CHARS + 1)}
            )
        assert response.status_code == 413

    def test_endpoint_returns_the_full_contract(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/repair",
                json={"text": "Brandenburg v. Ohio, 395 U.S. 444 (1969)"},
            )
        assert response.status_code == 200
        body = response.json()
        for key in (
            "input", "status", "citation_type", "parsed", "missing",
            "missing_labels", "formatted", "confidence", "source",
            "verify_url", "candidates", "notes",
        ):
            assert key in body, f"response is missing {key!r}"
        assert body["status"] == RESOLVED

    def test_endpoint_handles_garbage_without_erroring(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            response = client.post("/api/repair", json={"text": "!!!???"})
        assert response.status_code == 200
        assert response.json()["status"] == UNPARSEABLE


@pytest.mark.asyncio
class TestTemplateAndGuidance:
    """A partial citation should show its finished shape with the gaps marked,
    and name the rule governing each gap. Listing field names teaches nothing."""

    @respx.mock
    async def test_template_marks_only_the_real_gaps(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await repairer.repair("Brandenburg v Ohio 395 US 444")

        # Volume, reporter and page were supplied and must not be called missing.
        assert result.missing == ["year"]
        assert result.template == "*Brandenburg v. Ohio*, 395 US 444 ([year])."

    @respx.mock
    async def test_template_marks_every_gap(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await repairer.repair("Moody v. NetChoice")
        assert result.template == (
            "*Moody v. NetChoice*, [volume number] [reporter] [first page] "
            "([court] [year])."
        )

    @respx.mock
    async def test_every_gap_names_its_governing_rule(self, repairer):
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await repairer.repair("Moody v. NetChoice")

        by_field = {d["field"]: d for d in result.missing_details}
        assert by_field["volume"]["rule"] == "Rule 10.3.2"
        assert by_field["reporter"]["rule"] == "Rule 10.3.2"
        assert by_field["page"]["rule"] == "Rule 10.3.2"
        assert by_field["year"]["rule"] == "Rule 10.5"
        for detail in result.missing_details:
            assert detail["label"] and detail["why"]
            assert detail["rule"].startswith("Rule ")

    async def test_complete_citation_has_no_gaps(self, repairer):
        result = await repairer.repair("Brandenburg v. Ohio, 395 U.S. 444 (1969)")
        assert result.missing_details == []

    @respx.mock
    async def test_scotus_reporter_drops_the_court_slot(self, repairer):
        """Rule 10.4: no court identifier for the U.S. Supreme Court, so it is
        not presented as a gap the reader must fill."""
        respx.get(COURTLISTENER).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await repairer.repair("Brandenburg v Ohio 395 U.S. 444")
        assert "[court]" not in result.template


class TestDigitLeadingPartyNames:
    def test_volume_is_not_absorbed_into_the_defendant(self, ):
        from app.services.extractor import CitationExtractor

        cites = CitationExtractor().extract_all("Brandenburg v Ohio 395 US 444")
        assert cites[0].parties == ["Brandenburg", "Ohio"]
        assert cites[0].volume == "395"
        assert cites[0].page == "444"

    def test_a_party_may_begin_with_a_digit(self):
        from app.services.extractor import CitationExtractor

        cites = CitationExtractor().extract_all("3M Company v. Browner")
        assert "3M" in cites[0].parties[0]
