"""What happens as documents get long.

A short document hides every problem in this file. The failures here were found by
building real long documents and measuring, not by reading the code.
"""

import asyncio

import pytest

import app.main as main
from app.models.citation import Citation, CitationStatus, CitationType


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
