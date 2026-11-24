"""The HTTP layer under hostile or careless clients.

Four reviewers attacked the long-document work. These are the things they found that a request
alone could do to the server, each pinned by a test that fails without the fix:

* a body with no declared length (chunked) was read in full before any limit applied, to memory or
  to disk, because the limit only looked at the Content-Length header;
* a 190-byte Content-Type header froze the whole server for a minute or more (a regular
  expression in the pinned python-multipart);
* an abandoned request ran to the end and kept its place in the queue, so a phone that reset twice
  was told the server was busy with other people's documents;
* two public endpoints had none of the limits;
* every lookup failure was reported as "looked up", so an outage of the outside sources read as
  success;
* a stuck process was never restarted.

Where a real socket matters (chunked bodies, a frozen parser) the tests start the real server in a
subprocess. A hung server must fail a test, not hang the suite, so every wait has a deadline.
"""

import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import app.main as main
from app import limits
from app.asgi import BodyLimit, body_limit
from app.services.lookup_service import (
    CitationCompleter,
    LegalLookupService,
    page_metadata,
    tally_lookups,
)

BACKEND = Path(__file__).resolve().parents[1]
ORIGIN = "https://delschlangen.com"


# --- a real server in a subprocess ----------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RealServer:
    def __init__(self, tmp_path: Path, **env):
        self.port = _free_port()
        self.tmp = tmp_path / "server-tmp"
        self.tmp.mkdir()
        self.log = tmp_path / "server.log"
        full_env = {
            **os.environ,
            "TMPDIR": str(self.tmp),
            "EVENT_LOOP_STALL_EXIT_S": "0",
            **{k: str(v) for k, v in env.items()},
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(self.port),
             "--host", "127.0.0.1", "--log-level", "warning"],
            cwd=BACKEND, env=full_env,
            stdout=self.log.open("wb"), stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(self.url("/health"), timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"server did not start: {self.log.read_text()[-2000:]}")

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def peak_rss_mb(self) -> float:
        for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
        raise RuntimeError("no VmHWM")

    def tmp_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.tmp.rglob("*") if p.is_file())

    def stop(self):
        self.proc.kill()
        self.proc.wait(timeout=10)


@pytest.fixture
def server(tmp_path):
    srv = RealServer(tmp_path, MAX_UPLOAD_MB=2, MAX_ANALYZE_BODY_MB=1)
    yield srv
    srv.stop()


def _send_chunked(port: int, path: str, headers: dict, total: int, chunk: int = 256 * 1024,
                  prefix: bytes = b"", on_chunk=None) -> bytes:
    """POST `total` bytes with Transfer-Encoding: chunked (no Content-Length). Returns whatever
    the server answered. A server that answers early and closes makes later sends fail; the
    answer is read anyway."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=20)
    head = f"POST {path} HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    sock.sendall(head.encode())
    sent = 0
    try:
        first = True
        while sent < total:
            body = (prefix if first else b"") + b"a" * min(chunk, total - sent)
            first = False
            sock.sendall(f"{len(body):x}\r\n".encode() + body + b"\r\n")
            sent += len(body)
            if on_chunk:
                on_chunk(sent)
        sock.sendall(b"0\r\n\r\n")
    except OSError:
        pass
    sock.settimeout(20)
    data = b""
    try:
        while b"\r\n\r\n" not in data or not data.rstrip().endswith(b"}"):
            piece = sock.recv(65536)
            if not piece:
                break
            data += piece
    except OSError:
        pass
    sock.close()
    return data


class TestChunkedBodiesAreCountedNotTrusted:
    """The old gate read the Content-Length header. A chunked body declares none."""

    def test_a_chunked_analyze_body_is_cut_off_at_the_limit_instead_of_held_in_memory(
        self, server
    ):
        before = server.peak_rss_mb()
        answer = _send_chunked(
            server.port, "/api/analyze",
            {"Content-Type": "application/json", "Origin": ORIGIN},
            total=60 * 1024 * 1024, prefix=b'{"document_id":"d","filename":"x","text":"',
        )
        growth = server.peak_rss_mb() - before

        # Whether the client can still read the answer once the server stops reading is up to the
        # network stack; what must hold is that the body was NOT held. 60 MB read in full costs
        # several times that in memory.
        assert growth < 40, f"the server's memory grew by {growth:.0f} MB for a refused body"
        if answer:
            assert b" 413 " in answer.split(b"\r\n", 1)[0]
        assert httpx.get(server.url("/health"), timeout=5).status_code == 200

    def test_a_chunked_upload_is_cut_off_at_the_limit_instead_of_written_to_disk(self, server):
        peak = {"bytes": 0, "stop": False}

        def watch():
            while not peak["stop"]:
                peak["bytes"] = max(peak["bytes"], server.tmp_bytes())
                time.sleep(0.01)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        boundary = "BOUNDARY"
        prefix = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        _send_chunked(
            server.port, "/api/upload",
            {"Content-Type": f"multipart/form-data; boundary={boundary}", "Origin": ORIGIN},
            total=40 * 1024 * 1024, prefix=prefix,
        )
        time.sleep(0.2)
        peak["stop"] = True
        watcher.join(timeout=2)

        # The limit here is 2 MB (+ envelope). 40 MB written would show as tens of MB on disk.
        assert peak["bytes"] < 6 * 1024 * 1024, f"{peak['bytes'] / 1e6:.0f} MB reached the disk"
        assert httpx.get(server.url("/health"), timeout=5).status_code == 200

    def test_a_modest_overshoot_is_answered_with_a_readable_413(self, server):
        answer = _send_chunked(
            server.port, "/api/analyze",
            {"Content-Type": "application/json", "Origin": ORIGIN},
            total=1024 * 1024 + 1,  # the analyze limit in this server is 1 MB
            prefix=b'{"document_id":"d","filename":"x","text":"',
        )
        head, _, body = answer.partition(b"\r\n\r\n")
        assert b" 413 " in head.split(b"\r\n", 1)[0], answer[:300]
        assert b"access-control-allow-origin: " + ORIGIN.encode() in head.lower()
        assert b"too large" in body


class TestTheBodyLimitMiddleware:
    """The same logic without a socket, so the exact boundary can be tested."""

    @staticmethod
    async def _run(limit_path, chunks, declared=None):
        read = []

        async def application(scope, receive, send):
            while True:
                message = await receive()
                read.append(len(message.get("body", b"")))
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        queue = [
            {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
            for i, c in enumerate(chunks)
        ]

        async def receive():
            return queue.pop(0) if queue else {"type": "http.disconnect"}

        sent = []

        async def send(message):
            sent.append(message)

        headers = [(b"content-length", str(declared).encode())] if declared is not None else []
        scope = {"type": "http", "method": "POST", "path": limit_path, "headers": headers}
        await BodyLimit(application)(scope, receive, send)
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        return status, sum(read), sent

    @pytest.mark.asyncio
    async def test_a_body_exactly_at_the_limit_is_read_and_one_byte_over_is_not(self):
        limit = body_limit("/api/analyze")
        status, _, _ = await self._run("/api/analyze", [b"x" * limit])
        assert status == 200
        status, _, _ = await self._run("/api/analyze", [b"x" * limit, b"x"])
        assert status == 413

    @pytest.mark.asyncio
    async def test_reading_stops_at_the_limit_not_at_the_end_of_the_body(self):
        limit = body_limit("/api/format")
        chunks = [b"x" * (limit // 4)] * 40  # ten times the limit
        status, read_bytes, _ = await self._run("/api/format", chunks)
        assert status == 413
        assert read_bytes < limit * 1.5, "the application kept reading a refused body"

    @pytest.mark.asyncio
    async def test_a_declared_length_over_the_limit_is_refused_without_reading_anything(self):
        status, read_bytes, _ = await self._run(
            "/api/upload", [b"x"], declared=limits.MAX_UPLOAD_BYTES * 10
        )
        assert status == 413
        assert read_bytes == 0

    @pytest.mark.asyncio
    async def test_an_untrustworthy_length_header_is_ignored_not_crashed_on(self):
        async def application(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        for bogus in (b"abc", b"-5", b"9" * 40, b""):
            queue = [{"type": "http.request", "body": b"{}", "more_body": False}]
            sent = []

            async def receive(q=queue):
                return q.pop(0) if q else {"type": "http.disconnect"}

            async def send(message, out=sent):
                out.append(message)

            scope = {
                "type": "http", "method": "POST", "path": "/api/format",
                "headers": [(b"content-length", bogus)],
            }
            await BodyLimit(application)(scope, receive, send)
            assert sent[0]["status"] == 200, bogus

    @pytest.mark.asyncio
    async def test_a_get_is_never_counted(self):
        sent = []

        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "GET", "path": "/health", "headers": []}
        await BodyLimit(application)(scope, None, send)
        assert sent[0]["status"] == 200

    def test_every_text_taking_endpoint_has_the_analyze_limit(self):
        for path in ("/api/analyze", "/api/analyze-comprehensive", "/api/find-sources"):
            assert body_limit(path) == limits.MAX_ANALYZE_BODY_BYTES
        assert body_limit("/api/upload") == limits.MAX_UPLOAD_BYTES + limits.UPLOAD_ENVELOPE_BYTES
        assert body_limit("/api/format") == limits.MAX_SMALL_BODY_BYTES
        assert body_limit("/anything/else") == limits.MAX_SMALL_BODY_BYTES


# --- the multipart parser's pattern that froze the server ------------------------------------


class TestAHostileContentTypeHeaderDoesNotFreezeTheServer:
    """python-multipart 0.0.6 ran a quadratic regular expression on the Content-Type header. 38
    backslashes (about 190 bytes) took 14 seconds with the whole server frozen, 60 never finished.
    The pin is now a release without it."""

    @pytest.mark.parametrize("backslashes", [42, 80])
    def test_the_server_answers_promptly_and_keeps_answering(self, server, backslashes):
        header = 'multipart/form-data; boundary="' + "\\" * backslashes
        started = time.monotonic()
        try:
            response = httpx.post(
                server.url("/api/upload"),
                content=b"--x\r\n\r\n",
                headers={"Content-Type": header},
                timeout=8,
            )
            answered_in = time.monotonic() - started
            assert response.status_code in (400, 422)
        except httpx.TimeoutException:
            pytest.fail("the server did not answer a 190-byte request within 8 seconds")
        assert answered_in < 3
        started = time.monotonic()
        assert httpx.get(server.url("/health"), timeout=5).status_code == 200
        assert time.monotonic() - started < 1


# --- headers ----------------------------------------------------------------------------------


class TestBootIdIsOnEveryResponse:
    def test_success_error_refusal_and_exposure_to_scripts(self):
        # main.app, not an imported name: test_cors reloads the module, which makes a new app
        # (and a new boot id) and leaves any earlier reference pointing at the old one.
        client = TestClient(main.app, raise_server_exceptions=False)
        headers = {"Origin": ORIGIN}

        ok = client.get("/health", headers=headers)
        missing = client.get("/no/such/path", headers=headers)
        refused = client.post(
            "/api/format", content=b"{}", headers={
                **headers, "Content-Length": str(limits.MAX_SMALL_BODY_BYTES + 1),
                "Content-Type": "application/json",
            },
        )
        invalid = client.post("/api/analyze", json={"nope": 1}, headers=headers)

        for response in (ok, missing, refused, invalid):
            assert response.headers["x-boot-id"] == main.BOOT_ID
            exposed = response.headers["access-control-expose-headers"].lower()
            assert "x-boot-id" in exposed and "retry-after" in exposed
        assert (ok.status_code, missing.status_code, refused.status_code, invalid.status_code) == (
            200, 404, 413, 422,
        )
        assert ok.json()["boot_id"] == main.BOOT_ID  # the two ways of learning it agree


# --- abandoned requests -----------------------------------------------------------------------


class TestAnAbandonedRequestStopsCountingAgainstTheQueue:
    """A phone that locks, or a person who presses reset, drops the connection. The analysis used
    to run to the end anyway and hold its place, so a second try was told the server was busy
    with other people's documents."""

    @staticmethod
    async def _post_then_disconnect(body: bytes, after: float):
        sent_body = False
        gone = asyncio.Event()

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        answers = []

        async def send(message):
            answers.append(message)

        scope = {
            "type": "http", "method": "POST", "path": "/api/analyze", "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "query_string": b"", "http_version": "1.1", "scheme": "http",
            "server": ("test", 80), "client": ("1.2.3.4", 1), "root_path": "",
        }
        request = asyncio.ensure_future(main.app(scope, receive, send))
        await asyncio.sleep(after)
        gone.set()
        await asyncio.wait_for(request, timeout=10)
        return next(m["status"] for m in answers if m["type"] == "http.response.start")

    @pytest.mark.asyncio
    async def test_the_place_in_the_queue_is_freed_when_the_client_goes(self, monkeypatch):
        def slow(self, text):
            time.sleep(1.0)  # releases the interpreter lock, as the real work mostly does
            return []

        monkeypatch.setattr(main.CitationExtractor, "extract_all", slow)
        monkeypatch.setattr(main, "MAX_QUEUED_ANALYSES", 0)  # one at a time, nobody waits
        body = b'{"document_id":"d","text":"Some text.","filename":"x.txt"}'

        started = time.monotonic()
        status = await self._post_then_disconnect(body, after=0.2)
        gone_after = time.monotonic() - started

        # 499 (client closed request), not the 504 a deadline would give: nobody is listening, but
        # the log should say which of the two it was.
        assert status == 499
        assert gone_after < 0.9, "the handler kept waiting for work nobody wanted"
        assert main._active_analyses == 0

        # A second try is admitted (queued behind the running thread), not refused as busy.
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            retry = await asyncio.wait_for(
                client.post("/api/analyze", json={
                    "document_id": "d", "text": "Some text.", "filename": "x.txt"}),
                timeout=10,
            )
        assert retry.status_code == 200

    @pytest.mark.asyncio
    async def test_lookups_in_flight_are_cancelled_when_the_client_goes(self, monkeypatch):
        started, cancelled = [], []

        class Completer:
            def __init__(self, service):
                pass

            async def complete_citation(self, citation):
                started.append(1)
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.append(1)
                    raise

        monkeypatch.setattr(main, "CitationCompleter", Completer)
        monkeypatch.setattr(main, "get_lookup_service", lambda: object())
        text = " ".join(_case_text(n) for n in range(8))

        await self._post_then_disconnect(
            ('{"document_id":"d","filename":"x","text":"' + text + '"}').encode(), after=0.5
        )

        assert started, "the test never reached the lookup phase"
        assert len(cancelled) == len(started)
        await asyncio.sleep(0.1)
        assert main._active_analyses == 0

    @pytest.mark.asyncio
    async def test_lookups_are_cancelled_when_the_deadline_passes_during_them(self, monkeypatch):
        """Found by a reviewer: asyncio.wait does not cancel what it waits for when the waiter
        is cancelled, so a 504 left up to 200 outside requests running."""
        started, cancelled = [], []

        class Completer:
            def __init__(self, service):
                pass

            async def complete_citation(self, citation):
                started.append(1)
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.append(1)
                    raise

        monkeypatch.setattr(main, "CitationCompleter", Completer)
        monkeypatch.setattr(main, "get_lookup_service", lambda: object())
        monkeypatch.setattr(main, "ANALYSIS_DEADLINE_SECONDS", 0.6)
        text = " ".join(_case_text(n) for n in range(8))

        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/analyze", json={
                "document_id": "d", "text": text, "filename": "x.txt"})

        assert r.status_code == 504
        assert started and len(cancelled) == len(started)


# --- the two legacy endpoints ------------------------------------------------------------------


class TestLegacyEndpointsHaveTheSameLimits:
    @pytest.fixture
    def client(self):
        return TestClient(main.app, raise_server_exceptions=False)

    @pytest.mark.parametrize("path", ["/api/find-sources", "/api/analyze-comprehensive"])
    def test_text_over_the_limit_is_a_413(self, client, path, monkeypatch):
        monkeypatch.setattr(main, "MAX_TEXT_CHARS", 1000)
        r = client.post(path, json={"document_id": "d", "text": "a" * 1001, "filename": "x"})
        assert r.status_code == 413
        assert "1,000 characters" in r.json()["detail"]

    @pytest.mark.parametrize("path", ["/api/find-sources", "/api/analyze-comprehensive"])
    def test_a_busy_server_says_so(self, client, path, monkeypatch):
        monkeypatch.setattr(main, "_active_analyses", 1 + main.MAX_QUEUED_ANALYSES)
        r = client.post(path, json={"document_id": "d", "text": "Some text.", "filename": "x"})
        assert r.status_code == 503
        assert r.headers["retry-after"] == "30"

    @pytest.mark.parametrize("path", ["/api/find-sources", "/api/analyze-comprehensive"])
    def test_they_have_a_deadline(self, client, path, monkeypatch):
        def slow(self, text, *a, **k):
            time.sleep(0.8)
            return []

        monkeypatch.setattr(main, "ANALYSIS_DEADLINE_SECONDS", 0.2)
        monkeypatch.setattr(main.CitationExtractor, "extract_all", slow)
        monkeypatch.setattr(main.ClaimDetector, "detect_unsourced_claims", slow)
        r = client.post(path, json={"document_id": "d", "text": "Some text.", "filename": "x"})
        assert r.status_code == 504
        time.sleep(0.9)  # let the abandoned thread end before the next test

    def test_the_comprehensive_analysis_still_returns_its_documented_shape(self, client, monkeypatch):
        monkeypatch.setattr(main, "get_lookup_service", lambda: _NoLookups())
        r = client.post("/api/analyze-comprehensive", json={
            "document_id": "d", "filename": "x.txt", "find_sources": False,
            "text": "The rule is old. See Marbury v. Madison, 5 U.S. (1 Cranch) 137, 177 (1803).",
        })
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {
            "analysis", "short_form_suggestions", "stats", "citation_summary", "unsourced_analysis",
        }
        assert body["stats"]["total_citations"] >= 1

    def test_find_sources_searches_a_bounded_number_of_claims(self, client, monkeypatch):
        searched = []

        class Finder:
            def __init__(self, service):
                pass

            async def find_sources_for_claims(self, claims, max_suggestions=3, max_claims=None):
                chosen = claims[:max_claims]
                searched.extend(chosen)
                return [{"claim_id": c.id, "suggested_sources": []} for c in chosen]

        monkeypatch.setattr(main, "SourceFinder", Finder)
        monkeypatch.setattr(main, "get_lookup_service", lambda: _NoLookups())
        monkeypatch.setattr(main, "MAX_CLAIMS_FOR_SOURCES", 3)
        text = " ".join(f"About {n + 10}% of people agreed in study number {n}." for n in range(12))
        r = client.post("/api/find-sources", json={"text": text})
        assert r.status_code == 200
        body = r.json()
        assert body["total_claims"] > 3
        assert body["claims_searched"] == len(searched) == 3


class _NoLookups:
    async def smart_complete(self, citation):
        return {"found": False, "data": None, "suggestions": []}

    async def lookup_citation(self, citation):
        return {"found": False, "data": None, "suggestions": []}

    async def close(self):
        pass


# --- counting what the outside lookups did ------------------------------------------------------


COURTLISTENER = "https://www.courtlistener.com/api/rest/v3/search/"


_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def _case_text(n: int) -> str:
    # Letters only: the extractor does not keep digits in a party name.
    return f"{_NAMES[n]} v. {_NAMES[(n + 3) % 8]}, 5 U.S. ___ (1999)."


class TestLookupOutcomesAreCountedAtTheRequest:
    """Every lookup method turns a failure into "not found", so a source that was down looked
    exactly like a source with no such record, and the page said "looked up 200 of 218"."""

    async def _run(self, citations, route):
        service = LegalLookupService()
        try:
            with respx.mock(assert_all_called=False) as router:
                route(router)
                import app.main as m

                original = (m.get_lookup_service, m.CitationCompleter)
                m.get_lookup_service = lambda: service
                m.CitationCompleter = CitationCompleter
                try:
                    return await m._complete_citations(citations)
                finally:
                    m.get_lookup_service, m.CitationCompleter = original
        finally:
            await service.close()

    @staticmethod
    def _citations(n):
        return main.extractor.extract_all(" ".join(_case_text(i) for i in range(n)))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 429, 500, 503])
    async def test_a_source_that_refuses_or_fails_is_counted_as_failed(self, status):
        citations = self._citations(4)
        assert len(citations) == 4

        _, summary = await self._run(
            citations, lambda r: r.get(url__startswith=COURTLISTENER).respond(status)
        )

        assert summary.eligible == 4 and summary.completed == 4
        assert summary.failed == 4 and summary.matched == 0

    @pytest.mark.asyncio
    async def test_a_dropped_connection_is_counted_as_failed(self):
        citations = self._citations(3)

        _, summary = await self._run(
            citations,
            lambda r: r.get(url__startswith=COURTLISTENER).mock(
                side_effect=httpx.ConnectError("no route")
            ),
        )

        assert summary.failed == 3 and summary.matched == 0

    @pytest.mark.asyncio
    async def test_a_source_that_answers_no_such_record_is_not_a_failure(self):
        citations = self._citations(3)

        _, summary = await self._run(
            citations,
            lambda r: r.get(url__startswith=COURTLISTENER).respond(200, json={"results": []}),
        )

        assert summary.completed == 3
        assert summary.failed == 0 and summary.matched == 0

    @pytest.mark.asyncio
    async def test_a_404_is_an_answer_not_a_failure(self):
        citations = self._citations(2)

        _, summary = await self._run(
            citations, lambda r: r.get(url__startswith=COURTLISTENER).respond(404)
        )

        assert summary.failed == 0

    @pytest.mark.asyncio
    async def test_a_match_is_counted_as_matched(self):
        citations = self._citations(1)
        record = {
            "caseName": "Alpha v. Delta", "citation": ["5 U.S. 100"], "court": "Supreme Court",
            "court_id": "scotus", "dateFiled": "1999-01-01", "docketNumber": "1",
            "absolute_url": "/opinion/1/alpha-v-delta/", "snippet": "", "judge": "",
        }

        _, summary = await self._run(
            citations,
            lambda r: r.get(url__startswith=COURTLISTENER).respond(200, json={"results": [record]}),
        )

        assert summary.matched == 1 and summary.failed == 0

    @pytest.mark.asyncio
    async def test_the_tally_is_per_lookup_not_shared_between_concurrent_ones(self):
        """Concurrent lookups share one client; each must be counted on its own."""
        citations = self._citations(2)
        calls = {"n": 0}

        def respond(request):
            calls["n"] += 1
            return httpx.Response(500) if "Alpha" in str(request.url) else httpx.Response(
                200, json={"results": []}
            )

        _, summary = await self._run(
            citations, lambda r: r.get(url__startswith=COURTLISTENER).mock(side_effect=respond)
        )

        assert calls["n"] >= 2
        assert summary.failed == 1  # only the citation whose source failed

    @pytest.mark.asyncio
    async def test_requests_outside_a_tally_are_not_counted_anywhere(self):
        service = LegalLookupService()
        try:
            with respx.mock() as router:
                router.get("https://example.org/x").respond(500)
                client = await service._get_client()
                await client.get("https://example.org/x")
            with tally_lookups() as tally:
                pass
            assert (tally.ok, tally.failed) == (0, 0)
        finally:
            await service.close()


# --- page metadata from a hostile page ----------------------------------------------------------


class TestPageMetadata:
    PAGE = (
        '<html><head><title> The Title </title>'
        '<meta name="author" content="Jane Roe">'
        '<meta property="article:published_time" content="2021-05-04T10:00:00Z">'
        '<meta property="og:site_name" content="The Site"></head><body></body></html>'
    )

    def test_it_reads_an_ordinary_head(self):
        assert page_metadata(self.PAGE, "https://x.org/a") == (
            "The Title", "Jane Roe", "2021-05-04", "The Site",
        )

    def test_attributes_in_either_order(self):
        page = '<meta content="Joe Doe" name="author">'
        assert page_metadata(page, "https://x.org/a")[1] == "Joe Doe"

    def test_the_site_name_falls_back_to_the_host(self):
        assert page_metadata("<title>t</title>", "https://www.example.org/a")[3] == "www.example.org"

    def test_nothing_found_is_none_not_an_error(self):
        assert page_metadata("", "https://x.org")[:3] == (None, None, None)

    @pytest.mark.parametrize("unit", ["<meta ", '<meta name="author" ', "<title>", "<meta x=\""])
    def test_two_megabytes_of_unclosed_tags_are_read_in_well_under_a_second(self, unit):
        """The patterns scanned to the end of the page from every tag: with 2 MB of '<meta ' that
        was minutes. Run in a subprocess so a regression fails instead of hanging the suite."""
        code = (
            "import time; from app.services.lookup_service import page_metadata;"
            f"html = ({unit!r} * 400000)[:2_000_000]; t = time.perf_counter();"
            "page_metadata(html, 'https://x.org'); print(time.perf_counter() - t)"
        )
        done = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60
        )
        assert done.returncode == 0, done.stderr[-500:]
        assert float(done.stdout) < 1.0

    def test_only_the_head_of_a_long_page_is_read(self):
        padding = "x" * 250_000
        page = f"<title>First</title>{padding}<meta name=\"author\" content=\"Late Author\">"
        assert page_metadata(page, "https://x.org")[1] is None


# --- the watchdog --------------------------------------------------------------------------------


def _python(code: str, timeout: float, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True,
        timeout=timeout, env={**os.environ, **{k: str(v) for k, v in env.items()}},
    )


class TestTheWatchdog:
    def test_a_frozen_event_loop_ends_the_process_and_names_where(self):
        """A regular expression that never returns holds the interpreter lock, so nothing in
        Python can notice. faulthandler's C-level timer can."""
        code = (
            "import asyncio, re, sys\n"
            "from app import watchdog\n"
            "async def main():\n"
            "    asyncio.create_task(watchdog.run(stall_exit_s=1.5, cpu_job_max_s=0))\n"
            "    await asyncio.sleep(0.3)\n"
            "    print('freezing', flush=True)\n"
            "    re.match(r'(a+)+$', 'a' * 60 + 'b')  # catastrophic backtracking\n"
            "    print('not reached', flush=True)\n"
            "asyncio.run(main())\n"
        )
        started = time.monotonic()
        done = _python(code, timeout=30)
        took = time.monotonic() - started

        assert done.returncode == 1, (done.returncode, done.stdout, done.stderr[-500:])
        assert "freezing" in done.stdout and "not reached" not in done.stdout
        assert took < 8
        assert "Timeout" in done.stderr and "most recent call first" in done.stderr

    def test_a_healthy_loop_is_left_alone(self):
        code = (
            "import asyncio\n"
            "from app import watchdog\n"
            "async def main():\n"
            "    task = asyncio.create_task(watchdog.run(stall_exit_s=1.0, cpu_job_max_s=0, tick_s=0.1))\n"
            "    await asyncio.sleep(3.5)\n"  # more than three stall windows
            "    task.cancel()\n"
            "    await asyncio.gather(task, return_exceptions=True)\n"
            "    print('alive')\n"
            "asyncio.run(main())\n"
            "import time; time.sleep(1.5)\n"  # the timer must be disarmed when the task ends
            "print('still alive')\n"
        )
        done = _python(code, timeout=30)
        assert done.returncode == 0, done.stderr[-500:]
        assert "alive" in done.stdout and "still alive" in done.stdout

    def test_a_cpu_job_that_never_ends_ends_the_process(self):
        code = (
            "import asyncio, threading, time\n"
            "from app import watchdog\n"
            "async def main():\n"
            "    asyncio.create_task(watchdog.run(stall_exit_s=0, cpu_job_max_s=1.0, tick_s=0.2))\n"
            "    watchdog.cpu_job_started()\n"
            "    await asyncio.sleep(10)\n"
            "    print('not reached', flush=True)\n"
            "asyncio.run(main())\n"
        )
        started = time.monotonic()
        done = _python(code, timeout=30)
        assert done.returncode == 1, (done.returncode, done.stdout, done.stderr[-500:])
        assert "not reached" not in done.stdout
        assert time.monotonic() - started < 8
        assert "ending the process" in done.stderr

    @pytest.mark.asyncio
    async def test_a_job_that_finishes_in_time_is_never_reported_stuck(self):
        from app import watchdog

        stuck = []
        task = asyncio.create_task(
            watchdog.run(stall_exit_s=0, cpu_job_max_s=0.5, tick_s=0.05,
                         on_cpu_job_stuck=stuck.append)
        )
        watchdog.cpu_job_started()
        await asyncio.sleep(0.2)
        watchdog.cpu_job_finished()
        await asyncio.sleep(0.8)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert stuck == []

    @pytest.mark.asyncio
    async def test_a_long_job_is_reported_once_it_passes_the_limit(self):
        from app import watchdog

        stuck = []
        task = asyncio.create_task(
            watchdog.run(stall_exit_s=0, cpu_job_max_s=0.3, tick_s=0.05,
                         on_cpu_job_stuck=stuck.append)
        )
        watchdog.cpu_job_started()
        await asyncio.sleep(0.8)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        watchdog.cpu_job_finished()
        assert len(stuck) >= 1 and "CPU job" in stuck[0]

    @pytest.mark.asyncio
    async def test_the_cpu_gate_tells_the_watchdog_when_a_job_starts_and_ends(self):
        from app import watchdog

        seen = []

        def job():
            seen.append(watchdog.cpu_job_age())
            time.sleep(0.1)

        await main._cpu(job)
        await asyncio.sleep(0.05)
        assert seen and seen[0] >= 0
        assert watchdog.cpu_job_age() == 0.0


# --- how many citations one analysis builds ---------------------------------------------------


class TestACitationFloodIsRefusedBeforeItIsBuilt:
    """Each citation costs about 2 KB. A text at the size limit can hold 375,000 bare "Id.", about
    800 MB of citations that were then cut to the 2,000 shown. The count is now bounded while
    they are being built."""

    def test_the_span_index_stops_at_its_limit(self):
        from app.services.extractor import SpanIndex, TooManyCitationsError

        index = SpanIndex(limit=3)
        for i in range(3):
            index.append((i * 10, i * 10 + 2))
        with pytest.raises(TooManyCitationsError):
            index.append((100, 102))
        assert len(index) == 3

    def test_no_limit_means_no_error(self):
        from app.services.extractor import SpanIndex

        index = SpanIndex()
        for i in range(500):
            index.append((i * 10, i * 10 + 2))
        assert len(index) == 500

    def test_an_analysis_over_the_limit_is_a_readable_413(self, monkeypatch):
        monkeypatch.setattr(limits, "MAX_CITATIONS_ANALYZED", 20)
        client = TestClient(main.app, raise_server_exceptions=False)

        r = client.post(
            "/api/analyze",
            json={"document_id": "d", "text": "Id. " * 100, "filename": "x.txt"},
            headers={"Origin": ORIGIN},
        )

        assert r.status_code == 413
        assert "more than 20 citations" in r.json()["detail"]
        assert "Split it" in r.json()["detail"]
        assert r.headers["access-control-allow-origin"] == ORIGIN

    def test_a_document_at_the_limit_is_analysed(self, monkeypatch):
        monkeypatch.setattr(limits, "MAX_CITATIONS_ANALYZED", 20)
        client = TestClient(main.app, raise_server_exceptions=False)

        r = client.post(
            "/api/analyze",
            json={"document_id": "d", "text": "Id. " * 20, "filename": "x.txt"},
        )

        assert r.status_code == 200
        assert r.json()["stats"]["total_citations"] == 20

    def test_the_default_limit_keeps_the_worst_case_small(self):
        """375,000 bare "Id." fit in a text at the size limit. Measured in a fresh process, since
        memory that was once used is not given back to the measurement."""
        code = (
            "import resource, sys\n"
            "from app.services.extractor import CitationExtractor, TooManyCitationsError\n"
            "base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024\n"
            "try:\n"
            "    CitationExtractor().extract_all('Id. ' * 375_000)\n"
            "    print('no error')\n"
            "except TooManyCitationsError:\n"
            "    print('refused')\n"
            "print(round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 - base))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=120
        )
        refused, growth = done.stdout.split()
        assert refused == "refused", done.stderr[-300:]
        assert int(growth) < 250, f"{growth} MB were built before the text was refused"
