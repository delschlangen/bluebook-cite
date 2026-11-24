"""The page must never be left guessing.

A bare "Id." used to raise inside the extractor. The server then answered a bare-text 500
with no CORS headers, which a browser hides completely, so the page could only say
"Could not reach the citation server" about a bug that has a stack trace. Two layers of
defence are tested here: the bug itself, and the guarantee that any future bug of the
same kind is still readable by the page.
"""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.asgi import JsonErrors
from app.main import app

ORIGIN = "https://delschlangen.com"


@pytest.fixture
def client():
    # raise_server_exceptions=False so an unhandled error is returned as the HTTP
    # response a browser would actually receive, instead of being re-raised in the test.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --- the bug -----------------------------------------------------------------


BARE_ID_TEXTS = [
    "See Foo. Id.",
    "Smith v. Jones, 1 U.S. 1 (1990). Id.",
    "The court agreed. Id. The end.",
    "Id.",
    "Id. at 5.",
    "Id. at 5-7.",
    "id.",  # lower case is not a short form here, but must not crash either
    "Id. Id. Id.",
    "(Id.)",
    "foo Id.\nbar Id. at 12\nbaz Id.",
    "See id.",
    "Id.\n\nId. at 3",
]


class TestBareIdDoesNotCrash:
    @pytest.mark.parametrize("text", BARE_ID_TEXTS)
    def test_extraction_does_not_raise(self, extractor, text):
        extractor.extract_all(text)  # must not raise

    def test_a_bare_id_is_a_short_form_with_no_pincite(self, extractor):
        found = [c for c in extractor.extract_all("The court agreed. Id.") if c.short_form_type == "id"]
        assert len(found) == 1
        assert found[0].pincite is None

    def test_an_id_with_a_pincite_keeps_it(self, extractor):
        found = [c for c in extractor.extract_all("Id. at 447-49.") if c.short_form_type == "id"]
        assert [c.pincite for c in found] == ["447-49"]

    def test_mixed_bare_and_pinpointed_ids_are_each_read_correctly(self, extractor):
        found = [
            c.pincite
            for c in extractor.extract_all("First. Id. Second. Id. at 9. Third. Id.")
            if c.short_form_type == "id"
        ]
        assert found == [None, "9", None]

    def test_a_document_with_a_bare_id_is_analysed_over_http(self, client):
        text = "Brown v. Board of Education, 347 U.S. 483 (1954). Id. Marbury v. Madison. Id. at 177."
        r = client.post(
            "/api/analyze",
            json={"document_id": "d", "text": text, "filename": "x.txt"},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 200, r.text
        assert r.headers["access-control-allow-origin"] == ORIGIN
        assert r.json()["stats"]["total_citations"] >= 3

    def test_every_golden_citation_survives_a_trailing_and_leading_id(self, extractor):
        """The known-good corpus, each with a bare Id. attached both sides. Any pattern
        interaction that raises shows up here rather than in a user's document."""
        corpus = json.loads(
            (Path(__file__).resolve().parents[2] / "shared" / "spec_golden.json").read_text()
        )
        texts = [c["input"] for c in corpus["cases"]]
        assert len(texts) > 40
        for text in texts:
            for wrapped in (f"{text}. Id.", f"Id. {text}", f"See {text}. Id. Id."):
                extractor.extract_all(wrapped)


class TestIdIsNeverPartOfAPartyName:
    """Documents with a bare "Id." could not be analysed at all until the crash above was
    fixed, so the way "Id." sits beside a case name had never been exercised. It was being
    swallowed into the name: formatting "Id. Brown v. Board of Education" would print it."""

    def _cases(self, extractor, text):
        return [c for c in extractor.extract_all(text) if c.type.value == "case"]

    def _ids(self, extractor, text):
        return [c for c in extractor.extract_all(text) if c.short_form_type == "id"]

    def test_an_id_before_a_case_does_not_become_part_of_the_first_party(self, extractor):
        text = "Marbury v. Madison, 5 U.S. 137 (1803). Id. Brown v. Board of Education, 347 U.S. 483 (1954)."
        brown = [c for c in self._cases(extractor, text) if "Brown" in c.raw_text][0]
        assert brown.parties == ["Brown", "Board of Education"]
        assert brown.raw_text.startswith("Brown")
        assert len(self._ids(extractor, text)) == 1

    def test_an_id_after_a_case_without_a_reporter_is_not_its_second_party(self, extractor):
        text = "Marbury v. Madison. Id. at 177."
        ids = self._ids(extractor, text)
        assert [c.pincite for c in ids] == ["177"]
        assert self._cases(extractor, text)[0].parties[0] == "Marbury"
        assert "Id" not in self._cases(extractor, text)[0].parties[1]

    def test_an_id_followed_by_a_signal_and_a_case_finds_both(self, extractor):
        text = "Brown v. Board of Education, 347 U.S. 483 (1954). Id. See also Marbury v. Madison, 5 U.S. 137 (1803)."
        assert len(self._ids(extractor, text)) == 1
        assert [c.parties for c in self._cases(extractor, text)] == [
            ["Brown", "Board of Education"],
            ["Marbury", "Madison"],
        ]

    def test_an_id_at_the_start_of_a_note_before_a_case(self, extractor):
        text = "Id. Smith v. Jones, 1 U.S. 1 (1990)."
        assert len(self._ids(extractor, text)) == 1
        assert self._cases(extractor, text)[0].parties == ["Smith", "Jones"]

    @pytest.mark.parametrize("name", ["Idaho", "Ida. Mining", "Idle Hour", "IDEC"])
    def test_names_that_merely_begin_with_id_are_unaffected(self, extractor, name):
        text = f"{name} v. Jones, 1 U.S. 1 (1990)."
        assert self._cases(extractor, text)[0].parties[0] == name

    def test_the_formatted_output_never_contains_a_stray_id(self, extractor, formatter):
        text = "Marbury v. Madison, 5 U.S. 137 (1803). Id. Brown v. Board of Education, 347 U.S. 483 (1954)."
        for c in self._cases(extractor, text):
            assert "Id." not in formatter.format_citation(c)


# --- the safety net ----------------------------------------------------------


class TestUnexpectedErrorsAreReadableByThePage:
    def _boom(self, monkeypatch, exc):
        def raiser(self, text):
            raise exc

        monkeypatch.setattr(main.CitationExtractor, "extract_all", raiser)

    def test_an_unexpected_error_is_json_that_carries_the_cors_header(self, client, monkeypatch):
        self._boom(monkeypatch, RuntimeError("kaboom"))

        r = client.post(
            "/api/analyze",
            json={"document_id": "d", "text": "x", "filename": "x.txt"},
            headers={"Origin": ORIGIN},
        )

        assert r.status_code == 500
        assert r.headers["content-type"].startswith("application/json")
        # Without this header the browser discards the response and reports an
        # unreachable server.
        assert r.headers["access-control-allow-origin"] == ORIGIN
        body = r.json()
        assert "unexpected error" in body["detail"]
        assert body["error_id"] in body["detail"]
        assert "kaboom" not in r.text  # internals are logged, not shown

    def test_the_error_id_is_logged_so_it_can_be_found(self, client, monkeypatch, caplog):
        self._boom(monkeypatch, RuntimeError("kaboom"))

        with caplog.at_level("ERROR", logger="bluebook"):
            r = client.post(
                "/api/analyze",
                json={"document_id": "d", "text": "x", "filename": "x.txt"},
            )

        error_id = r.json()["error_id"]
        assert any(error_id in rec.getMessage() for rec in caplog.records)
        assert any(rec.exc_info for rec in caplog.records)  # the stack trace is kept

    def test_running_out_of_memory_says_so(self, client, monkeypatch):
        self._boom(monkeypatch, MemoryError())

        r = client.post(
            "/api/analyze",
            json={"document_id": "d", "text": "x", "filename": "x.txt"},
            headers={"Origin": ORIGIN},
        )

        assert r.status_code == 500
        assert "out of memory" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_deliberate_errors_keep_their_own_status_and_message(self, client):
        """The net is for the unexpected; a 413 or 415 must not be turned into a 500."""
        r = client.post(
            "/api/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 400
        assert "empty" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_disallowed_origin_still_gets_no_cors_header(self, client, monkeypatch):
        """The net sits inside CORS, so it must not widen who may read a response."""
        self._boom(monkeypatch, RuntimeError("kaboom"))

        r = client.post(
            "/api/analyze",
            json={"document_id": "d", "text": "x", "filename": "x.txt"},
            headers={"Origin": "https://evil.example"},
        )

        assert r.status_code == 500
        assert "access-control-allow-origin" not in r.headers

    @pytest.mark.asyncio
    async def test_cancellation_is_not_swallowed(self):
        """A phone that disconnects mid-request cancels the task. Turning that into a
        500 response would hide the cancellation from the server."""

        async def application(scope, receive, send):
            raise asyncio.CancelledError()

        sent = []

        async def send(message):
            sent.append(message)

        with pytest.raises(asyncio.CancelledError):
            await JsonErrors(application)({"type": "http", "path": "/x"}, None, send)
        assert sent == []  # no response was made up for a request that was cancelled
