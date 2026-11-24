"""Middleware written directly against the ASGI interface.

They replace `@app.middleware("http")` functions, which Starlette wraps in a class that streams
the request through a second task. That wrapper has two faults that matter here:

* a client that disconnects mid-request makes it raise "No response returned" after the work has
  already been done, so every abandoned request left a stack trace in the log and, worse, no way
  for the handler to find out that nobody was waiting any more;
* it cannot stop reading a request body half way: the body limit was only a check of the
  declared Content-Length, so a chunked upload, which declares none, was spooled to disk or held
  in memory in full (300 MB written to disk, 659 MB of memory) before any limit applied.

Order, outermost first: gzip, CORS, boot id, JSON errors, body limit, the application. The
errors are answered inside CORS so that the page can read them.
"""

import asyncio
import logging
import uuid

from starlette.responses import JSONResponse

from . import limits

log = logging.getLogger("bluebook")

_BODY_METHODS = {"POST", "PUT", "PATCH"}

# After a body passes its limit the rest of it is read and thrown away, up to this much and this
# long, before the 413 is sent. A client that is still sending when the server answers and closes
# gets its connection reset, and the browser then reports a network error instead of the 413. The
# bound is what keeps this from becoming the problem it solves: a client that keeps sending past it
# is cut off and may not see the answer.
_DRAIN_BYTES = 8 * 1024 * 1024
_DRAIN_SECONDS = 3.0


def body_limit(path: str) -> int:
    """The most bytes of request body each endpoint will read."""
    if path == "/api/upload":
        return limits.MAX_UPLOAD_BYTES + limits.UPLOAD_ENVELOPE_BYTES
    if path in ("/api/analyze", "/api/analyze-comprehensive", "/api/find-sources"):
        return limits.MAX_ANALYZE_BODY_BYTES
    # Every other endpoint takes a small JSON object.
    return limits.MAX_SMALL_BODY_BYTES


def too_large_message(path: str, declared: int | None) -> str:
    """What to tell the person. `declared` is the Content-Length when there was one; without it
    (a chunked body) the size is not known, only that it passed the limit."""
    if path == "/api/upload":
        if declared is not None:
            mb = declared / (1024 * 1024)
            return f"This file is {mb:.1f} MB. The limit is {limits.MAX_UPLOAD_MB} MB."
        return f"This file is larger than the {limits.MAX_UPLOAD_MB} MB limit."
    if path in ("/api/analyze", "/api/analyze-comprehensive", "/api/find-sources"):
        if declared is not None:
            mb = declared / (1024 * 1024)
            return (
                f"This document's text is {mb:.1f} MB, which is too large to analyze. "
                f"The text limit is {limits.MAX_TEXT_CHARS:,} characters."
            )
        return (
            "This document's text is too large to analyze. "
            f"The text limit is {limits.MAX_TEXT_CHARS:,} characters."
        )
    return "This request is larger than the server accepts."


class _BodyTooLarge(Exception):
    """Raised inside the application's read of the request, to stop it reading further."""


class BodyLimit:
    """Refuse a request body that is too large, counting the bytes that actually arrive.

    A declared Content-Length over the limit is refused without reading anything. A body with no
    declared length, or one that lies, is cut off the moment the count passes the limit. In both
    cases the answer is a JSON 413 that the page can read.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        limit = body_limit(path)

        declared: int | None = None
        for name, value in scope["headers"]:
            if name == b"content-length":
                # Bytes of ASCII digits only: anything else is the server's business, not ours.
                if value.isdigit() and len(value) <= 15:
                    declared = int(value)
                break

        if declared is not None and declared > limit:
            await JSONResponse(
                {"detail": too_large_message(path, declared)}, status_code=413
            )(scope, receive, send)
            return

        state = {"seen": 0, "over": False, "started": False}

        async def counting_receive():
            message = await receive()
            if message["type"] == "http.request":
                state["seen"] += len(message.get("body", b""))
                if state["seen"] > limit:
                    state["over"] = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message):
            if state["over"]:
                # The framework answers the read it saw fail with an error of its own (FastAPI
                # makes it a 400). The answer here is the 413 below, so drop that one.
                return
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            pass
        except Exception:
            if not state["over"]:
                raise
            # An exception that came out of the framework after our own cut-off: the cut-off is
            # the cause, so it is answered as one.

        if state["over"] and not state["started"]:
            await _drain(receive)
            await JSONResponse(
                {"detail": too_large_message(path, None)}, status_code=413
            )(scope, receive, send)


async def _drain(receive) -> None:
    """Read and discard what remains of a refused body, within a bound."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _DRAIN_SECONDS
    drained = 0
    while drained < _DRAIN_BYTES:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            message = await asyncio.wait_for(receive(), remaining)
        except TimeoutError:
            return
        if message["type"] != "http.request":
            return  # the client went away
        drained += len(message.get("body", b""))
        if not message.get("more_body"):
            return


class JsonErrors:
    """Turn an exception nobody handled into a JSON 500 that the page can read.

    Without this, Starlette's outermost handler answers a bare text 500 with no CORS headers. A
    browser hides such a response entirely, so the page could only say "could not reach the
    server" for what was really a bug with a stack trace. The error id is in the log line and in
    the message, so a report from a person can be matched to the trace.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # noqa: BLE001 - this is the last line of defence by design
            error_id = uuid.uuid4().hex[:8]
            log.exception("unhandled error %s on %s", error_id, scope.get("path"))
            if started:
                # The status line has gone out, so a JSON error can no longer be sent. Let the
                # server close the connection; the page sees a failed request and says so.
                raise
            if isinstance(exc, MemoryError):
                what = "The server ran out of memory while processing this document."
            else:
                what = "The server hit an unexpected error while processing this request."
            await JSONResponse(
                {"detail": f"{what} (error {error_id})", "error_id": error_id},
                status_code=500,
            )(scope, receive, send)


class BootIdHeader:
    """Put this process's id on every response (`X-Boot-Id`).

    A page that saw one id and, after a failed request, a different one knows the server
    restarted in between (a crash, an out-of-memory kill, a deploy) and can say so. Reading it
    from every response, not only from /health, keeps the last id seen right up to the request
    that failed.
    """

    def __init__(self, app, boot_id: str):
        self.app = app
        self._header = (b"x-boot-id", boot_id.encode("ascii"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), self._header]}
            await send(message)

        await self.app(scope, receive, send_with_id)
