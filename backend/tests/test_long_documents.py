"""What happens as documents get long.

A short document hides every problem in this file. The failures here were found by
building real long documents and measuring, not by reading the code.
"""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.services.pdf_text as pdf_text
from app.models.citation import Citation, CitationStatus, CitationType
from tests.docfactory import make_docx, make_pdf_pages

ORIGIN = "https://delschlangen.com"


def _incomplete_case(n: int, kind: str | None = None) -> Citation:
    return Citation(
        type=CitationType.CASE,
        status=CitationStatus.INCOMPLETE,
        raw_text=f"Party{n} v. Other{n}",
        position_start=n * 100,
        position_end=n * 100 + 20,
        parties=[f"Party{n}", f"Other{n}"],
        kind=kind,
    )


class _FakeCompleter:
    """Stands in for the network. `slow` names the citations that never finish in time."""

    calls: list[str] = []
    slow: set[str] = set()
    fail: set[str] = set()

    def __init__(self, lookup_service):
        pass

    async def complete_citation(self, citation):
        type(self).calls.append(citation.raw_text)
        if citation.raw_text in type(self).fail:
            raise RuntimeError("upstream exploded")
        if citation.raw_text in type(self).slow:
            await asyncio.sleep(60)
        await asyncio.sleep(0.01)
        citation.confidence_score = 0.99  # the visible sign that a lookup "found" something
        return citation


@pytest.fixture
def fake_lookup(monkeypatch):
    _FakeCompleter.calls = []
    _FakeCompleter.slow = set()
    _FakeCompleter.fail = set()
    monkeypatch.setattr(main, "CitationCompleter", _FakeCompleter)
    monkeypatch.setattr(main, "get_lookup_service", lambda: object())
    return _FakeCompleter


class _CopyingCompleter(_FakeCompleter):
    """Returns a NEW object instead of editing its argument.

    The production completer happens to edit in place, which means a finished lookup would
    survive a timeout even if the result list were thrown away. That is an accident of one
    implementation, not a guarantee, so the contract is tested against a completer that
    returns a copy: the only way a finished result reaches the response is if it is kept.
    """

    async def complete_citation(self, citation):
        type(self).calls.append(citation.raw_text)
        if citation.raw_text in type(self).slow:
            await asyncio.sleep(60)
        await asyncio.sleep(0.01)
        return citation.model_copy(update={"confidence_score": 0.99})


class TestLookupPhaseKeepsFinishedWork:
    @pytest.mark.asyncio
    async def test_finished_results_are_kept_even_when_the_completer_returns_a_copy(
        self, monkeypatch
    ):
        _CopyingCompleter.calls = []
        _CopyingCompleter.slow = set()
        monkeypatch.setattr(main, "CitationCompleter", _CopyingCompleter)
        monkeypatch.setattr(main, "get_lookup_service", lambda: object())
        monkeypatch.setattr(main, "COMPLETION_BUDGET_SECONDS", 0.3)
        citations = [_incomplete_case(i) for i in range(10)]
        _CopyingCompleter.slow = {c.raw_text for c in citations[6:]}

        completed, summary = await main._complete_citations(citations)

        assert [c.confidence_score for c in completed] == [0.99] * 6 + [0.0] * 4
        assert [c.raw_text for c in completed] == [c.raw_text for c in citations]
        assert summary.completed == 6 and summary.skipped == 4

    @pytest.mark.asyncio
    async def test_lookups_that_finished_survive_when_the_budget_runs_out(
        self, fake_lookup, monkeypatch
    ):
        """The old code wrapped everything in one wait_for and, on timeout, threw away
        every result including the ones that had already come back. The longer the
        document, the more likely it was to get no enrichment at all."""
        monkeypatch.setattr(main, "COMPLETION_BUDGET_SECONDS", 0.3)
        citations = [_incomplete_case(i) for i in range(10)]
        fake_lookup.slow = {c.raw_text for c in citations[6:]}

        completed, summary = await main._complete_citations(citations)

        enriched = [c for c in completed if c.confidence_score == 0.99]
        assert len(enriched) == 6
        assert {c.raw_text for c in enriched} == {c.raw_text for c in citations[:6]}
        assert summary.eligible == 10
        assert summary.completed == 6
        assert summary.skipped == 4
        assert summary.budget_exhausted is True

    @pytest.mark.asyncio
    async def test_unfinished_citations_come_back_untouched_not_dropped(
        self, fake_lookup, monkeypatch
    ):
        monkeypatch.setattr(main, "COMPLETION_BUDGET_SECONDS", 0.2)
        citations = [_incomplete_case(i) for i in range(4)]
        fake_lookup.slow = {citations[3].raw_text}

        completed, _ = await main._complete_citations(citations)

        assert [c.raw_text for c in completed] == [c.raw_text for c in citations]
        assert completed[3].confidence_score == 0.0

    @pytest.mark.asyncio
    async def test_unfinished_lookups_are_cancelled_not_left_running(
        self, fake_lookup, monkeypatch
    ):
        """Abandoned lookups holding connections open would pile up across requests."""
        monkeypatch.setattr(main, "COMPLETION_BUDGET_SECONDS", 0.2)
        citations = [_incomplete_case(i) for i in range(3)]
        fake_lookup.slow = {c.raw_text for c in citations}
        before = len(asyncio.all_tasks())

        await main._complete_citations(citations)
        await asyncio.sleep(0)

        assert len(asyncio.all_tasks()) == before

    @pytest.mark.asyncio
    async def test_when_everything_finishes_the_budget_is_not_reported_exhausted(
        self, fake_lookup
    ):
        citations = [_incomplete_case(i) for i in range(5)]

        _, summary = await main._complete_citations(citations)

        assert (summary.eligible, summary.completed, summary.skipped) == (5, 5, 0)
        assert summary.budget_exhausted is False

    @pytest.mark.asyncio
    async def test_one_failing_lookup_does_not_fail_the_document_or_its_neighbours(
        self, fake_lookup
    ):
        citations = [_incomplete_case(i) for i in range(3)]
        fake_lookup.fail = {citations[1].raw_text}

        completed, summary = await main._complete_citations(citations)

        assert len(completed) == 3
        assert completed[0].confidence_score == 0.99
        assert completed[1].confidence_score == 0.0
        assert completed[2].confidence_score == 0.99
        assert summary.skipped == 0

    @pytest.mark.asyncio
    async def test_the_number_of_lookups_is_capped_whatever_the_time(
        self, fake_lookup, monkeypatch
    ):
        """Time alone is not a bound: fast upstreams would still let a huge document
        queue thousands of requests against free public APIs."""
        monkeypatch.setattr(main, "MAX_LOOKUPS_PER_DOCUMENT", 3)
        citations = [_incomplete_case(i) for i in range(10)]

        _, summary = await main._complete_citations(citations)

        assert len(fake_lookup.calls) == 3
        assert fake_lookup.calls == [c.raw_text for c in citations[:3]]  # document order
        assert (summary.eligible, summary.completed, summary.skipped) == (10, 3, 7)
        assert summary.budget_exhausted is False

    @pytest.mark.asyncio
    async def test_engine_recognised_kinds_are_never_sent_to_a_lookup(self, fake_lookup):
        citations = [_incomplete_case(0, kind="agency_report"), _incomplete_case(1)]

        _, summary = await main._complete_citations(citations)

        assert fake_lookup.calls == [citations[1].raw_text]
        assert summary.eligible == 1

    @pytest.mark.asyncio
    async def test_no_citations_needing_a_lookup_means_no_lookup_at_all(self, fake_lookup):
        _, summary = await main._complete_citations([])

        assert fake_lookup.calls == []
        assert (summary.eligible, summary.completed, summary.skipped) == (0, 0, 0)


# --- long PDFs through the real endpoints ------------------------------------------------------

FOOTER = "https://orionpolicy.org/how-congress-should-regulate-autonomous-agentic-ai-cyber-risk/"


def _pdf(pages: int, footer: str | None = None, cite_every: int = 1) -> bytes:
    out = []
    for p in range(pages):
        page = [
            (720 - 16 * i, f"Body text of page {p + 1}, paragraph {i}, written to be unremarkable.")
            for i in range(20)
        ]
        if p % cite_every == 0:
            page.append((400, f"See Brown v. Board of Education, 347 U.S. {483 + p} (1954)."))
        if footer:
            page.append((40, footer))
        out.append(page)
    return make_pdf_pages(out)


@pytest.fixture
def http():
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


class TestLongPdfsThroughTheEndpoints:
    def test_a_long_pdf_uploads_and_its_citations_are_found(self, http):
        data = _pdf(250)
        started = time.monotonic()
        r = http.post(
            "/api/upload", files={"file": ("long.pdf", data, "application/pdf")},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 200, r.text
        assert time.monotonic() - started < 30
        body = r.json()
        assert body["format"] == "pdf"
        assert "page 250" in body["full_text"]

        a = http.post(
            "/api/analyze",
            json={"document_id": body["document_id"], "text": body["full_text"], "filename": "long.pdf"},
            headers={"Origin": ORIGIN},
        )
        assert a.status_code == 200, a.text
        assert a.json()["stats"]["total_citations"] >= 250

    def test_a_repeated_footer_url_does_not_become_a_citation_on_every_page(self, http):
        """The reported case: a 4-page PDF with the page's URL in every footer produced four
        'Website' citations, all needing review. In a 300-page document it would be 300."""
        data = _pdf(8, footer=FOOTER, cite_every=100)
        r = http.post("/api/upload", files={"file": ("p.pdf", data, "application/pdf")})
        text = r.json()["full_text"]
        assert FOOTER not in text

        a = http.post("/api/analyze", json={"document_id": "d", "text": text, "filename": "p.pdf"})
        websites = [c for c in a.json()["analysis"]["citations"] if c["type"] == "website"]
        assert websites == []

    def test_a_pdf_over_the_page_limit_is_refused_with_the_limit_stated(self, http, monkeypatch):
        monkeypatch.setattr(pdf_text, "MAX_PDF_PAGES", 25)
        r = http.post(
            "/api/upload", files={"file": ("long.pdf", _pdf(40), "application/pdf")},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 413
        assert "40 pages" in r.json()["detail"]
        assert "25-page limit" in r.json()["detail"]
        # 413 must be readable by the page, not an opaque network error
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_pdf_over_the_text_limit_is_refused_with_the_limit_stated(self, http, monkeypatch):
        monkeypatch.setattr(pdf_text, "MAX_TEXT_CHARS", 5000)
        r = http.post(
            "/api/upload", files={"file": ("dense.pdf", _pdf(60), "application/pdf")},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 413
        assert "5,000-character limit" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_an_unreadable_pdf_is_a_415_with_advice_not_a_500(self, http):
        r = http.post(
            "/api/upload", files={"file": ("bad.pdf", b"%PDF-1.4\nnot really a pdf", "application/pdf")},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 415
        assert "damaged" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_long_word_file_with_hundreds_of_footnotes_uploads(self, http):
        paragraphs = [(f"Paragraph {i} of the argument.", [100 + i]) for i in range(300)]
        notes = {100 + i: f"Brown v. Board of Education, 347 U.S. {i + 1} (1954)." for i in range(300)}
        data = make_docx(paragraphs, footnotes=notes)
        r = http.post("/api/upload", files={"file": ("long.docx", data, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["footnote_count"] == 300


class TestRealPdfsEndToEnd:
    """Real footnoted PDFs written by Chromium and reportlab, uploaded and analysed through the
    endpoints. The footnote numbers come from the PDF reader marking each footnote in the same
    syntax the Word reader writes, which the extractor then trusts over its digit heuristic."""

    FIXTURES = Path(__file__).parent / "fixtures" / "pdf"

    @staticmethod
    def _squash(s: str) -> str:
        return re.sub(r"[^0-9a-z]", "", s.lower())

    @pytest.mark.parametrize("name", ["a_lawreview_chromium", "a2_lawreview_reportlab"])
    def test_footnote_numbers_are_right_for_real_law_review_pdfs(self, http, name):
        truth = json.loads((self.FIXTURES / f"{name}.truth.json").read_text())
        up = http.post(
            "/api/upload",
            files={"file": (f"{name}.pdf", (self.FIXTURES / f"{name}.pdf").read_bytes(), "application/pdf")},
        ).json()
        found = http.post(
            "/api/analyze", json={"document_id": "d", "text": up["full_text"], "filename": name}
        ).json()["analysis"]["citations"]

        expected = [c for c in truth["cites"] if c["kind"] != "id" and c.get("footnote")]
        assert len(expected) > 30
        right = 0
        for want in expected:
            wanted = self._squash(want["text"])
            for got in found:
                have = self._squash(got["raw_text"])
                if have and (have in wanted or wanted in have) and got["footnote_number"] == want["footnote"]:
                    right += 1
                    break
        assert right / len(expected) >= 0.95, f"{right} of {len(expected)} footnote numbers right"

    def test_a_policy_paper_with_a_footer_on_every_page_yields_only_its_real_citations(self, http):
        name = "b_policy_chrome_hf"
        up = http.post(
            "/api/upload",
            files={"file": (f"{name}.pdf", (self.FIXTURES / f"{name}.pdf").read_bytes(), "application/pdf")},
        ).json()
        found = http.post(
            "/api/analyze", json={"document_id": "d", "text": up["full_text"], "filename": name}
        ).json()["analysis"]["citations"]

        # The footer URL ("orionpolicy.org/...") repeats on every page and is not a source.
        assert not any("orionpolicy.org" in c["raw_text"] for c in found)
        truth = json.loads((self.FIXTURES / f"{name}.truth.json").read_text())
        real_websites = [c for c in truth["cites"] if c["kind"] == "website"]
        assert sum(1 for c in found if c["type"] == "website") <= len(real_websites)
