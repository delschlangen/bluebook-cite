"""Reading uploads in a child process: what the parent does when the child answers, is slow,
hangs, spins inside a regular expression, floods its output, crashes or is not there.

Most of these start tests/fake_worker.py instead of the real reader, so each misbehaviour is
exact and repeatable and does not depend on what pdfium happens to do. A few use the real worker.
A hang in the code under test must FAIL these tests, not hang the run, so every call goes through
`run`, which has its own deadline.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import limits
from app.services import sandbox
from app.services.parser import (
    DocumentTooComplexError,
    DocumentTooLongError,
    UnsupportedDocumentError,
)
from tests.docfactory import make_docx, make_pdf_pages

BACKEND = Path(__file__).resolve().parents[1]
ORIGIN = "https://delschlangen.com"


def run(coro, timeout: float = 30):
    async def guarded():
        return await asyncio.wait_for(coro, timeout)

    return asyncio.run(guarded())


def parse(data: bytes = b"x", name: str = "ok", **kw):
    return run(sandbox.parse_isolated(data, name, **kw))


@pytest.fixture
def fake(monkeypatch):
    """Point the parent at the misbehaving stand-in, with a short wall clock."""
    monkeypatch.setattr(sandbox, "_WORKER_MODULE", "tests.fake_worker")
    monkeypatch.setattr(limits, "PARSE_WALL_S", 3.0)


def alive(pid: int) -> bool:
    """True if the process still exists in any form, a zombie included."""
    return os.path.exists(f"/proc/{pid}")


# --- the child answers -------------------------------------------------------------------------


class TestAnswers:
    def test_each_format_reads_the_same_as_in_process(self):
        from app.services.parser import DocumentParser

        docx = make_docx([("Body one.", [7])], footnotes={7: "See Brown v. Board of Education, 347 U.S. 483 (1954)."})
        pdf = make_pdf_pages([[(700 - 14 * i, f"Line {i}: Brandenburg v. Ohio, 395 U.S. 444 (1969).") for i in range(30)]] * 6)
        for name, data in [("a.txt", "Notes: 47 U.S.C. § 230.\n".encode()), ("a.docx", docx), ("a.pdf", pdf)]:
            direct = DocumentParser().parse_document(data, name)
            isolated = parse(data, name)
            assert (isolated.text, isolated.format, isolated.footnote_count, isolated.endnote_count, isolated.warnings) == (
                direct.text, direct.format, direct.footnote_count, direct.endnote_count, direct.warnings), name

    def test_the_real_worker_refuses_what_the_parser_refuses(self):
        with pytest.raises(UnsupportedDocumentError, match="not supported"):
            parse(bytes(range(256)) * 8, "blob.bin")
        with pytest.raises(UnsupportedDocumentError, match="damaged"):
            parse(b"%PDF-1.4\nnot really a pdf", "bad.pdf")

    def test_a_text_over_the_limit_is_refused_with_the_size_stated(self):
        with pytest.raises(DocumentTooLongError) as caught:
            parse(("word " * 4000).encode(), "long.txt", max_text_chars=10_000)
        assert "10,000 characters" in str(caught.value)
        assert "20,000 characters" in str(caught.value)       # the real size, not just the limit

    def test_the_page_limit_set_in_the_parent_is_the_one_the_child_enforces(self, monkeypatch):
        import app.services.pdf_text as pdf_text

        monkeypatch.setattr(pdf_text, "MAX_PDF_PAGES", 3)
        data = make_pdf_pages([[(700, "A line of text that is long enough to count as text.")]] * 5)
        with pytest.raises(DocumentTooLongError, match="3-page limit"):
            parse(data, "five.pdf")

    def test_refusals_the_child_writes_keep_their_kind_and_message(self, fake):
        with pytest.raises(DocumentTooLongError) as long_:
            parse(name="kind|too_long|Too long, split it.")
        assert str(long_.value) == "Too long, split it." and not isinstance(long_.value, DocumentTooComplexError)
        with pytest.raises(DocumentTooComplexError, match="Too complex"):
            parse(name="kind|complex|Too complex.")
        with pytest.raises(UnsupportedDocumentError) as unsupported:
            parse(name="kind|unsupported|Not a Word file.")
        assert str(unsupported.value) == "Not a Word file." and not isinstance(unsupported.value, DocumentTooLongError)
        with pytest.raises(UnsupportedDocumentError, match="could not be read"):
            parse(name="kind|failed|RuntimeError")


# --- the child misbehaves ----------------------------------------------------------------------


class TestMisbehavingChildren:
    def test_a_child_that_never_answers_is_killed_and_reaped(self, fake, monkeypatch, tmp_path):
        monkeypatch.setattr(limits, "PARSE_WALL_S", 1.0)
        pidfile = tmp_path / "pid"
        started = time.monotonic()
        with pytest.raises(DocumentTooComplexError) as caught:
            parse(name=f"hang|{pidfile}")
        assert time.monotonic() - started < 6
        assert "took longer than the 1 seconds" in str(caught.value)
        assert not alive(int(pidfile.read_text())), "the child outlived the call, as a process or a zombie"

    def test_a_child_stuck_in_a_regular_expression_is_killed_too(self, fake, monkeypatch, tmp_path):
        """The case no thread, deadline or timeout inside the server can stop: the interpreter lock
        is held by C code, so nothing in that process runs until it finishes."""
        monkeypatch.setattr(limits, "PARSE_WALL_S", 1.0)
        pidfile = tmp_path / "pid"
        started = time.monotonic()
        with pytest.raises(DocumentTooComplexError, match="took longer"):
            parse(name=f"spin|{pidfile}")
        assert time.monotonic() - started < 6
        assert not alive(int(pidfile.read_text()))

    def test_the_parent_keeps_answering_while_a_child_spins(self, fake, monkeypatch):
        monkeypatch.setattr(limits, "PARSE_WALL_S", 2.0)

        async def scenario():
            slow = asyncio.ensure_future(sandbox.parse_isolated(b"x", "spin"))
            gaps = []
            last = time.monotonic()
            for _ in range(15):
                await asyncio.sleep(0.05)
                now = time.monotonic()
                gaps.append(now - last)
                last = now
            with pytest.raises(DocumentTooComplexError):
                await slow
            return max(gaps)

        assert run(scenario()) < 0.5, "the event loop stalled while the child was spinning"

    def test_a_child_that_floods_stdout_is_stopped_at_the_cap(self, fake):
        started = time.monotonic()
        with pytest.raises(DocumentTooComplexError, match="larger than one upload"):
            parse(name="flood", max_text_chars=1000)        # cap is 6 x 1000 + 1 MiB; the child writes 64 MiB
        assert time.monotonic() - started < 6

    @pytest.mark.parametrize(
        "mode,exception,fragment",
        [
            ("segv", UnsupportedDocumentError, "could not be read"),
            ("abort", DocumentTooComplexError, "more memory or time"),
            ("exit1", UnsupportedDocumentError, "could not be read"),
            ("junk", UnsupportedDocumentError, "could not be read"),
            ("badversion", UnsupportedDocumentError, "could not be read"),
        ],
    )
    def test_a_crash_or_a_nonsense_answer_becomes_a_message(self, fake, mode, exception, fragment):
        with pytest.raises(exception, match=fragment):
            parse(name=mode)

    def test_a_child_that_never_reads_its_input_does_not_hang_the_parent(self, fake):
        with pytest.raises(UnsupportedDocumentError):
            parse(b"y" * (8 * 1024 * 1024), "noread")

    def test_a_child_that_floods_stderr_is_drained_not_blocked(self, fake):
        assert parse(name="stderr_flood").text == "drained"

    def test_a_child_that_cannot_be_started_is_reported_as_unavailable(self, monkeypatch):
        monkeypatch.setattr(sandbox.sys, "executable", "/nonexistent/python")
        with pytest.raises(sandbox.ParseUnavailableError):
            parse(b"hello")

    def test_cancelling_the_request_kills_the_child(self, fake, tmp_path):
        pidfile = tmp_path / "pid"

        async def scenario():
            task = asyncio.ensure_future(sandbox.parse_isolated(b"x", f"hang|{pidfile}"))
            for _ in range(100):
                await asyncio.sleep(0.05)
                if pidfile.exists() and pidfile.read_text():
                    break
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return int(pidfile.read_text())

        pid = run(scenario())
        deadline = time.monotonic() + 3
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not alive(pid), "a cancelled request left its child running"


# --- what the child can see --------------------------------------------------------------------


class TestTheChildsSurroundings:
    def test_it_is_started_without_the_servers_environment(self, fake, monkeypatch):
        monkeypatch.setenv("COURTLISTENER_API_TOKEN", "hunter2")
        monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
        report = json.loads(parse(name="env").text)
        assert "COURTLISTENER_API_TOKEN" not in report["env_keys"]
        assert "PYTHONPATH" not in report["env_keys"]
        assert report["ignore_environment"] == 1 and report["no_user_site"] == 1
        assert Path(report["cwd"]).resolve() == BACKEND

    def test_resource_limits_are_set_before_anything_else_runs(self):
        code = (
            "import resource;"
            "from app.services.parse_worker import _limit_resources;"
            "_limit_resources(1024, 40);"
            "print(resource.getrlimit(resource.RLIMIT_AS), resource.getrlimit(resource.RLIMIT_CPU),"
            " resource.getrlimit(resource.RLIMIT_CORE))"
        )
        out = subprocess.run([sys.executable, "-E", "-s", "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
        mb = 1024 * 1024
        assert out.stdout.strip() == f"({1024 * mb}, {1024 * mb}) (40, 45) (0, 0)"

    def test_the_cpu_limit_ends_a_busy_loop(self):
        code = (
            "from app.services.parse_worker import _limit_resources;"
            "_limit_resources(0, 1);"
            "\nwhile True: pass"
        )
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-E", "-s", "-c", code], cwd=BACKEND, timeout=20)
        assert done.returncode == -signal.SIGXCPU
        assert time.monotonic() - started < 10

    def test_the_memory_limit_ends_the_real_worker_on_a_memory_bomb(self, monkeypatch):
        """An 862-byte PDF whose form XObject draws itself: pdfium allocates until it aborts."""
        from tests.hostile import form_recursion_pdf

        monkeypatch.setattr(limits, "PARSE_CHILD_MEM_MB", 200)
        started = time.monotonic()
        with pytest.raises(DocumentTooComplexError, match="too complex"):
            parse(form_recursion_pdf(), "loop.pdf")
        assert time.monotonic() - started < 20


# --- how many at once, and what waiting costs --------------------------------------------------


class TestAdmission:
    def test_beyond_the_slots_and_the_queue_the_answer_is_busy_at_once(self, fake, monkeypatch):
        monkeypatch.setattr(limits, "PARSE_MAX_CONCURRENT", 1)
        monkeypatch.setattr(limits, "PARSE_MAX_QUEUE", 1)

        async def scenario():
            first = asyncio.ensure_future(sandbox.parse_isolated(b"x", "sleep|1.0"))
            await asyncio.sleep(0.2)
            second = asyncio.ensure_future(sandbox.parse_isolated(b"x", "sleep|0.2"))
            await asyncio.sleep(0.1)
            seen = sandbox.stats()
            started = time.monotonic()
            with pytest.raises(sandbox.ParseBusyError) as busy:
                await sandbox.parse_isolated(b"x", "sleep|0.2")
            refused_in = time.monotonic() - started
            return seen, busy.value, refused_in, (await first).text, (await second).text

        seen, busy, refused_in, first, second = run(scenario())
        assert seen == {"running": 1, "waiting": 1}
        assert refused_in < 0.2, "a full queue must answer at once, not after waiting"
        assert busy.retry_after == limits.PARSE_RETRY_AFTER_S
        assert "busy" in str(busy)
        assert (first, second) == ("slept", "slept"), "the two that were admitted both finish"

    def test_the_wait_for_a_slot_is_bounded(self, fake, monkeypatch):
        monkeypatch.setattr(limits, "PARSE_MAX_CONCURRENT", 1)
        monkeypatch.setattr(limits, "PARSE_MAX_QUEUE", 5)
        monkeypatch.setattr(limits, "PARSE_QUEUE_WAIT_S", 0.3)

        async def scenario():
            first = asyncio.ensure_future(sandbox.parse_isolated(b"x", "sleep|1.2"))
            await asyncio.sleep(0.1)
            started = time.monotonic()
            with pytest.raises(sandbox.ParseBusyError):
                await sandbox.parse_isolated(b"x", "sleep|0.1")
            waited = time.monotonic() - started
            await first
            return waited, sandbox.stats()

        waited, after = run(scenario())
        assert 0.25 < waited < 1.0
        assert after == {"running": 0, "waiting": 0}, "slots must be returned"

    def test_waiting_in_the_queue_does_not_use_up_the_reading_budget(self, fake, monkeypatch):
        """A document that takes 1 s to read must not fail with a 'took too long' message because
        it waited 1 s for its turn while the wall clock is 1.5 s."""
        monkeypatch.setattr(limits, "PARSE_MAX_CONCURRENT", 1)
        monkeypatch.setattr(limits, "PARSE_MAX_QUEUE", 3)
        monkeypatch.setattr(limits, "PARSE_WALL_S", 1.5)

        async def scenario():
            results = await asyncio.gather(
                *(sandbox.parse_isolated(b"x", "sleep|1.0") for _ in range(3)), return_exceptions=True)
            return results

        started = time.monotonic()
        results = run(scenario())
        assert [getattr(r, "text", r) for r in results] == ["slept"] * 3
        assert time.monotonic() - started > 2.8, "they ran one after another, the later ones waiting longer than the budget"

    def test_a_killed_child_frees_its_slot(self, fake, monkeypatch):
        monkeypatch.setattr(limits, "PARSE_MAX_CONCURRENT", 1)
        monkeypatch.setattr(limits, "PARSE_MAX_QUEUE", 0)
        monkeypatch.setattr(limits, "PARSE_WALL_S", 0.5)
        with pytest.raises(DocumentTooComplexError):
            parse(name="hang")
        assert parse(name="ok").text == "ok"
        assert sandbox.stats() == {"running": 0, "waiting": 0}

    def test_uploads_do_not_use_the_thread_pool(self, fake, monkeypatch):
        """The analysis runs on the default thread pool; a pool full of uploads would starve it. Any
        use of the loop's default executor (asyncio.to_thread uses it) fails this test."""
        monkeypatch.setattr(limits, "PARSE_MAX_CONCURRENT", 2)

        async def scenario():
            loop = asyncio.get_running_loop()

            def forbidden(*args, **kwargs):
                raise AssertionError("an upload used the default thread pool")

            loop.run_in_executor = forbidden
            results = await asyncio.gather(*(sandbox.parse_isolated(b"x", "sleep|0.3") for _ in range(2)))
            return [r.text for r in results]

        assert run(scenario()) == ["slept", "slept"]


# --- through the endpoint ----------------------------------------------------------------------


@pytest.fixture
def http():
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def upload(client, name: str, data: bytes = b"hello world"):
    return client.post("/api/upload", files={"file": (name, data, "application/octet-stream")},
                       headers={"Origin": ORIGIN})


class TestStatusesAndMessages:
    @pytest.mark.parametrize(
        "mode,status,fragment",
        [
            ("kind|too_long|This PDF has 500 pages.", 413, "500 pages"),
            ("kind|complex|It is too complex.", 413, "too complex"),
            ("kind|unsupported|Not a Word file.", 415, "Not a Word file"),
            ("abort", 413, "too complex to read within this server's limits"),
            ("segv", 415, "could not be read"),
            ("flood", 413, "too complex"),
        ],
    )
    def test_every_outcome_is_a_json_response_the_page_can_read(self, http, fake, mode, status, fragment):
        r = upload(http, mode)
        assert r.status_code == status, r.text
        assert fragment in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN
        assert http.get("/health").status_code == 200

    def test_a_timeout_is_a_413_with_the_time_stated_and_advice(self, http, fake, monkeypatch):
        monkeypatch.setattr(limits, "PARSE_WALL_S", 1.0)
        r = upload(http, "hang")
        assert r.status_code == 413
        detail = r.json()["detail"]
        assert "too complex" in detail and "took longer" in detail and "split" in detail
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_busy_is_a_503_with_retry_after_and_not_a_415(self, http, fake, monkeypatch):
        monkeypatch.setattr(limits, "PARSE_MAX_CONCURRENT", 1)
        monkeypatch.setattr(limits, "PARSE_MAX_QUEUE", 0)
        with ThreadPoolExecutor(3) as pool:
            futures = [pool.submit(upload, http, "sleep|1.2") for _ in range(3)]
            responses = [f.result(timeout=30) for f in futures]
        codes = sorted(r.status_code for r in responses)
        assert codes == [200, 503, 503], codes      # one reads, two are turned away at once
        busy = next(r for r in responses if r.status_code == 503)
        assert busy.headers["retry-after"] == str(limits.PARSE_RETRY_AFTER_S)
        assert "busy" in busy.json()["detail"]
        assert busy.headers["access-control-allow-origin"] == ORIGIN

    def test_a_reader_that_cannot_start_is_a_503(self, http, monkeypatch):
        monkeypatch.setattr(sandbox.sys, "executable", "/nonexistent/python")
        r = upload(http, "a.txt")
        assert r.status_code == 503
        assert r.headers["retry-after"]
        assert "document reader" in r.json()["detail"]


# --- the parent stays small --------------------------------------------------------------------


def rss_mb() -> float:
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("no VmRSS")


@pytest.mark.skipif(not os.path.exists("/proc/self/status"), reason="needs /proc")
def test_the_parent_stays_flat_across_many_uploads(http):
    """50 uploads of mixed small documents. The parent never parses one, so what it holds after
    the first few should not grow."""
    docx = make_docx([("Body.", [1])], footnotes={1: "See Brown v. Board of Education, 347 U.S. 483 (1954)."})
    pdf = make_pdf_pages([[(700 - 14 * i, f"Line {i}: Brandenburg v. Ohio, 395 U.S. 444 (1969).") for i in range(30)]] * 5)
    docs = [("a.txt", b"See Brown v. Board of Education, 347 U.S. 483 (1954). " * 50), ("a.docx", docx), ("a.pdf", pdf)]
    for i in range(8):                                   # warm up: imports, allocator arenas
        assert upload(http, *docs[i % 3]).status_code == 200
    before = rss_mb()
    for i in range(50):
        assert upload(http, *docs[i % 3]).status_code == 200
    growth = rss_mb() - before
    assert growth < 15, f"the server grew by {growth:.1f} MB over 50 uploads"
