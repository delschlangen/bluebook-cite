"""The small endpoints (one citation, a case name, a search phrase) refuse text longer than a
citation can be, and read what they accept in linear time.

A reviewer froze the server with a 3 KB request: POST /api/lookup/case with "1", 3,000 spaces and
"!" ran a cubic regular expression on the event loop for 45 seconds, after which the watchdog
ended the process and every request in flight was lost. /api/search and /api/complete-from-text
had a quadratic one (60,000 digits), and /api/format read a 20 KB title for 9 seconds. The body
limit for these endpoints was 1 MB, so nothing else stood in the way.
"""

import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import limits

ORIGIN = "https://delschlangen.com"


class _Lookup:
    """Stands in for the outside lookups: these tests are about what happens before them."""

    client = object()

    def __init__(self):
        self.seen = []

    async def lookup_citation(self, citation):
        self.seen.append(citation)
        return {"found": False, "data": None, "suggestions": []}

    async def search_by_text(self, query, search_type):
        self.seen.append(query)
        return {"found": False, "data": None, "suggestions": []}

    async def smart_complete(self, citation):
        return {"found": False, "data": None, "suggestions": []}

    async def close(self):
        pass


@pytest.fixture
def lookup(monkeypatch):
    stub = _Lookup()
    monkeypatch.setattr(main, "get_lookup_service", lambda: stub)
    return stub


@pytest.fixture
def client(lookup):
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _timed(call):
    began = time.perf_counter()
    response = call()
    return response, time.perf_counter() - began


class TestTheFreezesThatWereFound:
    def test_one_digit_and_three_thousand_spaces_is_answered_at_once(self, client, lookup):
        # 3,000 characters is over the field limit; 1,900 is inside it and took 13 s before.
        response, seconds = _timed(
            lambda: client.post("/api/lookup/case", json={"citation": "1" + " " * 1900 + "!"})
        )

        assert response.status_code == 200
        assert seconds < 1.0, f"took {seconds:.1f} s"
        assert lookup.seen[0].volume is None, "it is not a citation, so nothing is parsed from it"

    def test_a_long_run_of_digits_in_a_statute_search_is_answered_at_once(self, client):
        response, seconds = _timed(
            lambda: client.post("/api/search", json={"query": "1" * 1900, "search_type": "statute"})
        )

        assert response.status_code == 200
        assert seconds < 1.0, f"took {seconds:.1f} s"

    def test_a_real_citation_is_still_parsed(self, client, lookup):
        response = client.post("/api/lookup/case", json={"citation": "410 U.S. 113"})

        assert response.status_code == 200
        sent = lookup.seen[0]
        assert (sent.volume, sent.reporter, sent.page) == ("410", "U.S.", "113")

    def test_parties_are_still_split(self, client, lookup):
        client.post("/api/lookup/case", json={"parties": "Roe v. Wade"})

        assert lookup.seen[0].parties == ["Roe", "Wade"]


class TestTextLongerThanACitationIsRefused:
    LONG = "x" * (main.MAX_FIELD_CHARS + 1)

    @pytest.mark.parametrize(
        ("path", "body", "field"),
        [
            ("/api/lookup/case", {"citation": "LONG"}, "citation"),
            ("/api/lookup/case", {"parties": "LONG"}, "parties"),
            ("/api/search", {"query": "LONG", "search_type": "case"}, "query"),
            ("/api/complete-from-text", {"text": "LONG"}, "text"),
            ("/api/format", {"type": "book", "status": "complete", "raw_text": "x",
                             "position_start": 0, "position_end": 1, "title": "LONG"}, "title"),
            ("/api/lookup", {"type": "case", "status": "incomplete", "raw_text": "LONG",
                             "position_start": 0, "position_end": 1}, "raw_text"),
            ("/api/format", {"type": "case", "status": "complete", "raw_text": "x",
                             "position_start": 0, "position_end": 1, "parties": ["A", "LONG"]}, "parties"),
        ],
    )
    def test_a_413_that_names_the_field_and_the_limit(self, client, path, body, field):
        def fill(value):
            if value == "LONG":
                return self.LONG
            if isinstance(value, list):
                return [fill(v) for v in value]
            return value

        response = client.post(path, json={k: fill(v) for k, v in body.items()}, headers={"Origin": ORIGIN})

        assert response.status_code == 413, response.text
        detail = response.json()["detail"]
        assert field in detail and f"{main.MAX_FIELD_CHARS:,}" in detail
        assert response.headers["access-control-allow-origin"] == ORIGIN

    def test_text_at_the_limit_is_accepted(self, client):
        response = client.post("/api/search", json={"query": "x" * main.MAX_FIELD_CHARS, "search_type": "case"})

        assert response.status_code == 200

    def test_a_list_with_hundreds_of_entries_is_refused(self, client):
        response = client.post("/api/format", json={
            "type": "case", "status": "complete", "raw_text": "x", "position_start": 0,
            "position_end": 1, "parties": ["A"] * 51,
        })

        assert response.status_code == 413

    def test_an_ordinary_citation_is_formatted_as_before(self, client):
        response = client.post("/api/format", json={
            "type": "case", "status": "complete", "raw_text": "Roe v. Wade, 410 U.S. 113 (1973)",
            "position_start": 0, "position_end": 32, "parties": ["Roe", "Wade"], "volume": "410",
            "reporter": "U.S.", "page": "113", "year": 1973,
        })

        assert response.status_code == 200
        assert "410 U.S. 113 (1973)" in response.json()["formatted"]


class TestTheBodyLimitForSmallEndpoints:
    def test_it_is_tens_of_kilobytes_not_a_megabyte(self):
        """One citation is a few kilobytes of JSON. A megabyte only gave a slow pattern room."""
        assert limits.MAX_SMALL_BODY_BYTES <= 128 * 1024

    def test_a_body_over_it_is_refused_before_it_is_parsed(self, client):
        response = client.post(
            "/api/search",
            content=b'{"query": "' + b"x" * (limits.MAX_SMALL_BODY_BYTES + 10) + b'"}',
            headers={"Content-Type": "application/json", "Origin": ORIGIN},
        )

        assert response.status_code == 413
        assert response.headers["access-control-allow-origin"] == ORIGIN


class TestHeadIsAnswered:
    """Uptime monitors and load balancers probe with HEAD; a 405 there reads as "down"."""

    @pytest.mark.parametrize("path", ["/health", "/"])
    def test_head_is_200_like_get(self, client, path):
        assert client.head(path).status_code == 200
        assert client.get(path).status_code == 200


class TestAnEmptyFileIsDescribedAsWhatItIs:
    """"If this is a scanned PDF it needs OCR first" was shown for Word and text files too."""

    def _upload(self, client, monkeypatch, fmt):
        from app.services.parser import ParsedDocument

        async def parsed(content, filename, **kw):
            return ParsedDocument(text="   ", format=fmt, footnote_count=0, endnote_count=0, warnings=[])

        monkeypatch.setattr(main, "parse_isolated", parsed)
        return client.post("/api/upload", files={"file": ("a.bin", b"x", "application/octet-stream")})

    def test_a_pdf_is_told_about_scans(self, client, monkeypatch):
        response = self._upload(client, monkeypatch, "pdf")
        assert response.status_code == 400 and "OCR" in response.json()["detail"]

    @pytest.mark.parametrize("fmt", ["docx", "txt"])
    def test_other_files_are_not_told_to_run_ocr(self, client, monkeypatch, fmt):
        response = self._upload(client, monkeypatch, fmt)
        assert response.status_code == 400
        assert "OCR" not in response.json()["detail"] and "PDF" not in response.json()["detail"]
