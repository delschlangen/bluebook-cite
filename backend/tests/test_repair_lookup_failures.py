"""/api/repair must not say "No matching record was found" when nobody could be asked.

The lookup methods turn every failure (a refused request, a timeout, a rate limit) into
"found: false", so the repairer could not tell "the source had no such record" from "the source
could not be reached", and told a lawyer that a real case had no record while the outside
service was down. The document path already counted outcomes where each request is made; the
repair path now does the same. Found by a reviewer on the phone: the same lookup said "could not
be reached" in a document and "No matching record" in Fix a citation.
"""

import asyncio

import httpx
import pytest
import respx

import app.main as main
from app.services.lookup_service import LegalLookupService

COURTLISTENER = "https://www.courtlistener.com/api/rest/v3/search/"
NO_RECORD = "No matching record was found."
NOT_REACHED = "could not be reached"
TEXT = "Moody v. NetChoice"


async def _repair(route, monkeypatch, text=TEXT):
    service = LegalLookupService()
    monkeypatch.setattr(main, "get_lookup_service", lambda: service)
    try:
        with respx.mock(assert_all_called=False) as router:
            route(router)
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                response = await asyncio.wait_for(
                    client.post("/api/repair", json={"text": text}), timeout=20
                )
        assert response.status_code == 200, response.text
        return response.json()
    finally:
        await service.close()


def _notes(body) -> str:
    return " ".join(body["notes"])


class TestAnUnreachableSourceIsNotNoRecord:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 429, 500, 503])
    async def test_a_source_that_refuses_or_fails(self, monkeypatch, status):
        body = await _repair(lambda r: r.get(url__startswith=COURTLISTENER).respond(status), monkeypatch)

        assert NOT_REACHED in _notes(body)
        assert NO_RECORD not in _notes(body)
        assert "does not mean there is no such record" in _notes(body)

    @pytest.mark.asyncio
    async def test_a_dropped_connection(self, monkeypatch):
        body = await _repair(
            lambda r: r.get(url__startswith=COURTLISTENER).mock(side_effect=httpx.ConnectError("no route")),
            monkeypatch,
        )

        assert NOT_REACHED in _notes(body)
        assert NO_RECORD not in _notes(body)

    @pytest.mark.asyncio
    async def test_the_parse_and_the_missing_fields_are_still_returned(self, monkeypatch):
        body = await _repair(lambda r: r.get(url__startswith=COURTLISTENER).respond(503), monkeypatch)

        assert body["status"] == "incomplete"
        assert body["missing_details"], "the page still shows what the citation needs"
        assert body["formatted"] is None, "nothing is invented when nothing was found"


class TestARealAnswerOfNoRecordStillSaysSo:
    @pytest.mark.asyncio
    async def test_an_empty_answer(self, monkeypatch):
        body = await _repair(
            lambda r: r.get(url__startswith=COURTLISTENER).respond(200, json={"results": []}),
            monkeypatch,
        )

        assert NO_RECORD in _notes(body)
        assert NOT_REACHED not in _notes(body)

    @pytest.mark.asyncio
    async def test_a_404_is_an_answer(self, monkeypatch):
        body = await _repair(lambda r: r.get(url__startswith=COURTLISTENER).respond(404), monkeypatch)

        assert NO_RECORD in _notes(body)
        assert NOT_REACHED not in _notes(body)


class TestPartlyReachable:
    @pytest.mark.asyncio
    async def test_some_answered_and_some_did_not(self, monkeypatch):
        calls = {"n": 0}

        def respond(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"results": []})

        body = await _repair(lambda r: r.get(url__startswith=COURTLISTENER).mock(side_effect=respond), monkeypatch)

        if calls["n"] < 2:
            pytest.skip("this input makes only one outside request, so there is no partial case to see")
        notes = _notes(body)
        assert "in the sources that answered" in notes and NOT_REACHED in notes
        assert "does not mean there is no such record" not in notes


class TestATimeoutDoesNotAlsoClaimNoRecord:
    @pytest.mark.asyncio
    async def test_the_offline_fallback_says_only_that_it_timed_out(self, monkeypatch):
        async def never(self, citation):
            await asyncio.sleep(30)

        monkeypatch.setattr(LegalLookupService, "smart_complete", never)
        monkeypatch.setattr(main, "REPAIR_BUDGET_SECONDS", 0.2)
        service = LegalLookupService()
        monkeypatch.setattr(main, "get_lookup_service", lambda: service)
        try:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                response = await asyncio.wait_for(client.post("/api/repair", json={"text": TEXT}), timeout=20)
        finally:
            await service.close()

        notes = _notes(response.json())
        assert "timed out" in notes
        assert NO_RECORD not in notes
        assert NOT_REACHED not in notes
