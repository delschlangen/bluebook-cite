"""The limits are enforced, they are the numbers the page is told, and every refusal is a
response the page can read (a 413 with the limit stated, carrying CORS headers) rather than an
opaque network failure."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import limits
from tests.docfactory import make_docx

ORIGIN = "https://delschlangen.com"


@pytest.fixture
def http():
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _cases(n: int) -> str:
    return " ".join(
        f"See Brown v. Board of Education, 347 U.S. {100 + i} (1954)." for i in range(n)
    )


# --- the limits are published, and are the ones enforced ------------------------------------


class TestHealthPublishesTheLimits:
    def test_the_limits_are_those_in_force(self, http):
        body = http.get("/health").json()
        assert body["limits"] == limits.as_dict()
        assert body["limits"]["max_upload_mb"] == limits.MAX_UPLOAD_MB
        assert body["limits"]["max_text_chars"] == limits.MAX_TEXT_CHARS
        assert body["limits"]["max_pdf_pages"] == limits.MAX_PDF_PAGES

    def test_the_page_count_in_the_message_is_computed_from_the_text_limit(self):
        assert limits.approx_pages(1_500_000) == 348
        assert limits.approx_words(1_500_000) == 250_000

    def test_boot_id_is_stable_within_a_process_so_a_restart_is_visible(self, http):
        first = http.get("/health").json()
        second = http.get("/health").json()
        assert first["boot_id"] == second["boot_id"]
        assert len(first["boot_id"]) >= 8
        assert second["uptime_s"] >= first["uptime_s"] >= 0


# --- the text limit applies to every format ---------------------------------------------------


class TestTextLimit:
    def test_a_long_text_file_is_refused_with_the_limit_stated(self, http, monkeypatch):
        monkeypatch.setattr(main, "MAX_TEXT_CHARS", 10_000)
        r = http.post(
            "/api/upload",
            files={"file": ("long.txt", (_cases(400)).encode(), "text/plain")},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 413
        assert "10,000 characters" in r.json()["detail"]
        assert "Split it" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_long_word_file_is_refused_too(self, http, monkeypatch):
        monkeypatch.setattr(main, "MAX_TEXT_CHARS", 10_000)
        data = make_docx([_cases(40) for _ in range(20)])
        r = http.post(
            "/api/upload", files={"file": ("long.docx", data, "application/octet-stream")}
        )
        assert r.status_code == 413
        assert "10,000 characters" in r.json()["detail"]

    def test_a_document_just_under_the_limit_is_accepted(self, http, monkeypatch):
        text = _cases(5)
        monkeypatch.setattr(main, "MAX_TEXT_CHARS", len(text) + 10)
        r = http.post("/api/upload", files={"file": ("ok.txt", text.encode(), "text/plain")})
        assert r.status_code == 200

    def test_analyze_enforces_it_too_because_it_takes_the_text_directly(self, http, monkeypatch):
        monkeypatch.setattr(main, "MAX_TEXT_CHARS", 1000)
        r = http.post(
            "/api/analyze",
            json={"document_id": "d", "text": _cases(100), "filename": "x.txt"},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 413
        assert "1,000 characters" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_the_message_names_the_size_in_words_and_pages(self):
        message = limits.too_long_message(4_255_083, 1_500_000)
        assert "709,180 words" in message
        assert "4,255,083 characters" in message
        assert "limit is 1,500,000 characters" in message
        assert "250,000 words" in message
        assert "348 pages" in message

    def test_the_number_in_the_message_is_the_number_that_was_passed_in(self):
        assert "limit is 7,000 characters" in limits.too_long_message(9_000, 7_000)


# --- oversized requests are refused before the body is read --------------------------------


class TestDeclaredSizeIsCheckedBeforeReadingTheBody:
    def test_an_upload_declaring_too_many_bytes_is_refused_unread(self, http):
        too_big = limits.MAX_UPLOAD_BYTES + limits.UPLOAD_ENVELOPE_BYTES + 1
        r = http.post(
            "/api/upload",
            content=b"tiny",  # nothing is read, so the real body does not matter
            headers={
                "Content-Length": str(too_big),
                "Content-Type": "multipart/form-data; boundary=x",
                "Origin": ORIGIN,
            },
        )
        assert r.status_code == 413
        assert f"The limit is {limits.MAX_UPLOAD_MB} MB" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_an_analyze_body_declaring_too_many_bytes_is_refused_unread(self, http):
        r = http.post(
            "/api/analyze",
            content=b"{}",
            headers={
                "Content-Length": str(limits.MAX_ANALYZE_BODY_BYTES + 1),
                "Content-Type": "application/json",
                "Origin": ORIGIN,
            },
        )
        assert r.status_code == 413
        assert "too large" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_file_at_the_limit_is_not_refused_by_this_gate(self, http):
        r = http.post(
            "/api/upload",
            content=b"x",
            headers={
                "Content-Length": str(limits.MAX_UPLOAD_BYTES),
                "Content-Type": "multipart/form-data; boundary=x",
            },
        )
        assert r.status_code != 413 or "MB" not in r.json().get("detail", "")

    def test_an_endpoint_that_takes_a_small_object_refuses_a_large_declared_body(self, http):
        r = http.post(
            "/api/format",
            content=b"{}",
            headers={
                "Content-Length": str(limits.MAX_SMALL_BODY_BYTES + 1),
                "Content-Type": "application/json",
                "Origin": ORIGIN,
            },
        )
        assert r.status_code == 413
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_small_body_to_the_same_endpoint_is_not_refused(self, http):
        r = http.post(
            "/api/format",
            content=b"{}",
            headers={
                "Content-Length": "2",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code != 413


# --- what a response carries is capped, but the totals are true -----------------------------


class TestResponseCaps:
    def _analyze(self, http, text):
        r = http.post("/api/analyze", json={"document_id": "d", "text": text, "filename": "x.txt"})
        assert r.status_code == 200, r.text
        return r.json()

    def test_citations_beyond_the_cap_are_counted_but_not_sent(self, http, monkeypatch):
        monkeypatch.setattr(main, "MAX_CITATIONS_RETURNED", 5)
        body = self._analyze(http, _cases(12))

        assert body["stats"]["total_citations"] == 12
        assert body["stats"]["citations_shown"] == 5
        assert len(body["analysis"]["citations"]) == 5

    def test_the_citations_sent_are_the_first_in_document_order(self, http, monkeypatch):
        monkeypatch.setattr(main, "MAX_CITATIONS_RETURNED", 3)
        body = self._analyze(http, _cases(8))
        pages = [c["page"] for c in body["analysis"]["citations"]]
        assert pages == ["100", "101", "102"]

    def test_the_status_counts_cover_the_whole_document_not_just_what_is_sent(
        self, http, monkeypatch
    ):
        monkeypatch.setattr(main, "MAX_CITATIONS_RETURNED", 2)
        stats = self._analyze(http, _cases(10))["stats"]
        assert stats["complete"] + stats["incomplete"] + stats["needs_verification"] == 10

    def test_short_form_suggestions_refer_only_to_citations_that_were_sent(
        self, http, monkeypatch
    ):
        monkeypatch.setattr(main, "MAX_CITATIONS_RETURNED", 3)
        text = (
            "Brown v. Board of Education, 347 U.S. 483 (1954). Id. at 495. "
            "Marbury v. Madison, 5 U.S. 137 (1803). Id. at 177. "
            + _cases(6)
            + " Brown v. Board of Education, 347 U.S. 483 (1954)."
        )
        body = self._analyze(http, text)
        sent = {c["id"] for c in body["analysis"]["citations"]}
        for suggestion in body["short_form_suggestions"]:
            assert suggestion["citation_id"] in sent

    def test_claims_beyond_the_cap_keep_the_most_likely_in_document_order(
        self, http, monkeypatch
    ):
        from app.services.source_finder import ClaimDetector

        monkeypatch.setattr(main, "MAX_CLAIMS_RETURNED", 4)
        legal = [f"Courts have consistently ruled against agency number {i}." for i in range(5)]
        stats = [f"Studies show that {30 + i}% of voters were undecided." for i in range(3)]
        quotes = [f'The senator said "we will never surrender position {i} to them."' for i in range(2)]
        text = " ".join(legal + stats + quotes)

        # What the detector finds, and which of those four should survive, worked out here
        # independently of the endpoint: the four with the highest confidence.
        found = ClaimDetector().detect_unsourced_claims(text, [])
        assert len(found) > 4, "the sample must have more claims than the cap"
        floor = sorted((c.confidence for c in found), reverse=True)[3]
        assert any(c.confidence < floor for c in found), "the sample must have claims to drop"

        body = self._analyze(http, text)
        claims = body["analysis"]["unsourced_claims"]
        assert body["stats"]["unsourced_claims"] == len(found)
        assert body["stats"]["claims_shown"] == 4 == len(claims)
        assert all(c["confidence"] >= floor for c in claims)
        starts = [c["position_start"] for c in claims]
        assert starts == sorted(starts)  # back in document order

    def test_a_document_under_the_caps_is_sent_whole(self, http):
        body = self._analyze(http, _cases(4))
        assert body["stats"]["total_citations"] == body["stats"]["citations_shown"] == 4


# --- responses are compressed -----------------------------------------------------------------


class TestCompression:
    def test_a_large_response_is_gzipped_and_still_readable_cross_origin(self, http):
        text = _cases(200)
        r = http.post(
            "/api/analyze",
            json={"document_id": "d", "text": text, "filename": "x.txt"},
            headers={"Origin": ORIGIN, "Accept-Encoding": "gzip"},
        )
        assert r.status_code == 200
        assert r.headers["content-encoding"] == "gzip"
        assert r.headers["access-control-allow-origin"] == ORIGIN
        assert r.json()["stats"]["total_citations"] == 200

    def test_the_compressed_body_is_much_smaller_on_the_wire(self, http):
        """The test client decompresses for us, so the bytes actually sent are counted from
        the raw stream."""
        body = {"document_id": "d", "text": _cases(200), "filename": "x.txt"}

        def wire_bytes(accept: str) -> tuple[int, str | None]:
            with http.stream(
                "POST", "/api/analyze", json=body, headers={"Accept-Encoding": accept}
            ) as r:
                raw = b"".join(r.iter_raw())
                return len(raw), r.headers.get("content-encoding")

        plain_size, plain_encoding = wire_bytes("identity")
        zipped_size, zipped_encoding = wire_bytes("gzip")

        assert plain_encoding is None
        assert zipped_encoding == "gzip"
        assert zipped_size * 4 < plain_size, f"{zipped_size} vs {plain_size} bytes"
