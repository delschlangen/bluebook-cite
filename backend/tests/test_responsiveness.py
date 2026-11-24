"""The server keeps answering while it analyses a long document, and says so plainly when it
cannot.

The analysis is CPU work. Run on the single event loop it blocked every other request,
/health included, for as long as it took (measured at 7 s, twice, for a 1,000-page document),
so a long upload made the whole service look down to everyone, including the page's own
health probe. These tests use real threads and real waiting, with margins several times larger
than the effects they check.
"""

import asyncio
import threading
import time

import httpx
import pytest

import app.main as main

ORIGIN = "https://delschlangen.com"


@pytest.fixture
def api():
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _slow_extract(seconds: float):
    """A stand-in for extraction that takes a while WITHOUT holding the interpreter lock, so a
    thread can run beside the event loop. Run inline it would block the loop for `seconds`."""

    def slow(self, text):
        time.sleep(seconds)
        return []

    return slow


async def _ticker(stop: asyncio.Event, gaps: list[float]) -> None:
    last = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(0.01)
        now = time.monotonic()
        gaps.append(now - last)
        last = now


class TestCpuWorkIsOffTheEventLoop:
    @pytest.mark.asyncio
    async def test_the_loop_keeps_ticking_while_a_job_runs(self):
        stop, gaps = asyncio.Event(), []
        ticking = asyncio.create_task(_ticker(stop, gaps))
        await asyncio.sleep(0.05)

        await main._cpu(time.sleep, 0.5)

        stop.set()
        await ticking
        assert max(gaps) < 0.2, f"the event loop stalled for {max(gaps):.2f}s"

    @pytest.mark.asyncio
    async def test_the_same_job_run_inline_does_stall_the_loop(self):
        """The control: this is what the offload prevents, so the test above means something."""
        stop, gaps = asyncio.Event(), []
        ticking = asyncio.create_task(_ticker(stop, gaps))
        await asyncio.sleep(0.05)

        time.sleep(0.5)  # inline, on the loop
        await asyncio.sleep(0.05)

        stop.set()
        await ticking
        assert max(gaps) > 0.4

    @pytest.mark.asyncio
    async def test_jobs_run_one_at_a_time(self):
        spans, lock = [], threading.Lock()

        def job():
            start = time.monotonic()
            time.sleep(0.15)
            with lock:
                spans.append((start, time.monotonic()))

        await asyncio.gather(main._cpu(job), main._cpu(job), main._cpu(job))

        spans.sort()
        assert len(spans) == 3
        for (_, first_end), (second_start, _) in zip(spans, spans[1:], strict=False):
            assert second_start >= first_end - 0.005

    @pytest.mark.asyncio
    async def test_the_slot_is_held_until_a_timed_out_thread_really_finishes(self):
        """A thread cannot be killed. If the request gives up, the next job must still wait
        for the abandoned thread, or two large documents end up fighting for the CPU."""
        record = {}

        def abandoned():
            time.sleep(0.4)
            record["first_ended"] = time.monotonic()

        def next_job():
            record["second_started"] = time.monotonic()

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(main._cpu(abandoned), timeout=0.1)
        await main._cpu(next_job)

        assert record["second_started"] >= record["first_ended"] - 0.005

    @pytest.mark.asyncio
    async def test_a_job_that_raises_reports_it_and_frees_the_slot(self):
        def boom():
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError, match="kaboom"):
            await main._cpu(boom)

        assert await asyncio.wait_for(main._cpu(lambda: "fine"), timeout=2) == "fine"

    @pytest.mark.asyncio
    async def test_a_job_is_not_started_if_the_wait_for_the_slot_is_cancelled(self):
        started = []
        holder = asyncio.create_task(main._cpu(time.sleep, 0.3))
        await asyncio.sleep(0.05)

        waiting = asyncio.create_task(main._cpu(lambda: started.append(1)))
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        await holder
        await asyncio.sleep(0.1)

        assert started == []
        # and the slot was not lost along the way
        assert await asyncio.wait_for(main._cpu(lambda: "ok"), timeout=2) == "ok"


class TestTheServerStaysUpDuringAnAnalysis:
    @pytest.mark.asyncio
    async def test_health_answers_promptly_while_a_long_analysis_runs(self, api, monkeypatch):
        monkeypatch.setattr(main.CitationExtractor, "extract_all", _slow_extract(0.8))
        body = {"document_id": "d", "text": "Some document text.", "filename": "x.txt"}

        analysis = asyncio.create_task(api.post("/api/analyze", json=body))
        await asyncio.sleep(0.2)

        started = time.monotonic()
        health = await api.get("/health")
        answered_in = time.monotonic() - started

        assert health.status_code == 200
        assert answered_in < 0.3, f"/health took {answered_in:.2f}s during an analysis"
        assert not analysis.done(), "the analysis should still have been running"
        assert (await analysis).status_code == 200


class TestDeadlineAndBusy:
    @pytest.mark.asyncio
    async def test_an_analysis_past_its_deadline_is_a_readable_504(self, api, monkeypatch):
        monkeypatch.setattr(main, "ANALYSIS_DEADLINE_SECONDS", 0.2)
        monkeypatch.setattr(main.CitationExtractor, "extract_all", _slow_extract(0.8))

        r = await api.post(
            "/api/analyze",
            json={"document_id": "d", "text": "Some text.", "filename": "x.txt"},
            headers={"Origin": ORIGIN},
        )

        assert r.status_code == 504
        assert "0.2-second limit" in r.json()["detail"]
        assert "split" in r.json()["detail"].lower()
        assert r.headers["access-control-allow-origin"] == ORIGIN
        assert main._active_analyses == 0
        await asyncio.sleep(0.9)  # let the abandoned thread finish before the next test

    @pytest.mark.asyncio
    async def test_a_busy_server_says_so_and_when_to_retry(self, api, monkeypatch):
        monkeypatch.setattr(main, "MAX_QUEUED_ANALYSES", 0)
        monkeypatch.setattr(main.CitationExtractor, "extract_all", _slow_extract(0.6))
        body = {"document_id": "d", "text": "Some text.", "filename": "x.txt"}

        first = asyncio.create_task(api.post("/api/analyze", json=body))
        await asyncio.sleep(0.15)
        second = await api.post("/api/analyze", json=body, headers={"Origin": ORIGIN})

        assert second.status_code == 503
        assert "busy" in second.json()["detail"]
        assert second.headers["retry-after"] == "30"
        assert second.headers["access-control-allow-origin"] == ORIGIN
        assert (await first).status_code == 200
        assert main._active_analyses == 0

    @pytest.mark.asyncio
    async def test_waiting_in_the_queue_is_allowed_up_to_the_limit(self, api, monkeypatch):
        monkeypatch.setattr(main, "MAX_QUEUED_ANALYSES", 1)
        monkeypatch.setattr(main.CitationExtractor, "extract_all", _slow_extract(0.3))
        body = {"document_id": "d", "text": "Some text.", "filename": "x.txt"}

        first = asyncio.create_task(api.post("/api/analyze", json=body))
        await asyncio.sleep(0.1)
        queued = asyncio.create_task(api.post("/api/analyze", json=body))
        await asyncio.sleep(0.1)
        refused = await api.post("/api/analyze", json=body)

        assert refused.status_code == 503
        assert (await first).status_code == 200
        assert (await queued).status_code == 200

    @pytest.mark.asyncio
    async def test_the_count_of_running_analyses_returns_to_zero_after_an_error(
        self, api, monkeypatch
    ):
        def boom(self, text):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(main.CitationExtractor, "extract_all", boom)

        r = await api.post(
            "/api/analyze", json={"document_id": "d", "text": "Some text.", "filename": "x.txt"}
        )

        assert r.status_code == 500
        assert main._active_analyses == 0
        # and a later request is not refused as busy
        monkeypatch.undo()
        # fail fast if the failed job left the CPU slot taken: the request would wait for ever
        ok = await asyncio.wait_for(
            api.post(
                "/api/analyze",
                json={"document_id": "d", "text": "Some text.", "filename": "x.txt"},
            ),
            timeout=5,
        )
        assert ok.status_code == 200
