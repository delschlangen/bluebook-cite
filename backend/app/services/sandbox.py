"""Reading an uploaded document in a short-lived child process.

    parsed = await parse_isolated(content, filename, max_text_chars=...)   # ParsedDocument

The parent never parses an upload. It starts `python -m app.services.parse_worker`, sends a small
JSON header and the file on stdin, and reads one JSON object from stdout. Why: see limits.py and
parse_worker.py. A native library that aborts, a regular expression that holds the interpreter
lock and a memory bomb each end only the child.

What the parent does, and why each part is here:

* asyncio.create_subprocess_exec, not a thread pool: an upload waiting on or running a child
  occupies no worker thread, so uploads cannot starve the analysis (which runs on the default
  thread pool).
* At most PARSE_MAX_CONCURRENT children at once and PARSE_MAX_QUEUE uploads waiting for one.
  Beyond that, or after waiting PARSE_QUEUE_WAIT_S, ParseBusyError (the endpoint answers 503 with
  Retry-After). The wait is not part of the child's own budget: the clock starts at the spawn.
* A wall-clock timeout that kills the child's whole process group and reaps it, and a cap on how
  much the child may write to stdout.
* The result is mapped to the exceptions the endpoint already understands (413 too long or too
  complex, 415 unreadable), with a message that says what to do. A child killed by a signal is
  told apart by the signal.

What this does not do. It does not make the container's memory safe: PARSE_MAX_CONCURRENT x
PARSE_CHILD_MEM_MB of address space can still be asked for at once (see limits.py), and
RLIMIT_AS is a ceiling on virtual memory, not resident memory. The child is started with a
reduced environment (no API keys) but it is not in a container, a jail or a different user, so
it is a guard against crashes and exhaustion, not a security boundary against code execution.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .. import limits
from . import parse_worker, pdf_text
from . import parser as parser_module
from .parser import (
    DocumentTooComplexError,
    DocumentTooLongError,
    ParsedDocument,
    UnsupportedDocumentError,
)

log = logging.getLogger("bluebook.sandbox")

# The directory that contains the `app` package: the child's working directory, so that
# `-m app.services.parse_worker` finds it. (-I would also drop the working directory from the
# import path, and with it the package.)
_ROOT = Path(__file__).resolve().parents[2]

# The module the child runs. A constant so that the tests can start a stand-in that hangs,
# crashes or floods stdout, to prove what the parent does about each.
_WORKER_MODULE = "app.services.parse_worker"

# What the child may inherit. No API keys, no tokens: nothing that a document could reach if
# the reader were ever exploited.
_ENV_KEEP = ("PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "TMPDIR")

# glibc gives every thread its own 64 MB arena of address space; under an address-space limit
# that is waste. The child is single-threaded.
_ENV_FORCE = {"MALLOC_ARENA_MAX": "2"}

_STDERR_KEPT = 4096
_UNREADABLE = "This file could not be read. It may be damaged."


class ParseBusyError(Exception):
    """Too many documents are being read. Not a fault in the file; try again shortly."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class ParseUnavailableError(Exception):
    """The reader process could not be started (out of processes or memory on the host)."""


# --- admission: at most N running, M waiting ---------------------------------------------------

_state: dict = {}


def _admission() -> dict:
    """One semaphore per running event loop (asyncio primitives belong to the loop that first
    waits on them, and the tests create a new loop for each client), rebuilt if a limit changes."""
    loop = asyncio.get_running_loop()
    key = (max(1, limits.PARSE_MAX_CONCURRENT), max(0, limits.PARSE_MAX_QUEUE))
    if _state.get("loop") is not loop or _state.get("key") != key:
        _state.clear()
        _state.update(loop=loop, key=key, sem=asyncio.Semaphore(key[0]), waiting=0, running=0)
    return _state


def stats() -> dict:
    """Children running and uploads waiting, for tests and diagnostics."""
    return {"running": _state.get("running", 0), "waiting": _state.get("waiting", 0)}


def _busy() -> ParseBusyError:
    return ParseBusyError(
        "The server is busy reading other documents. Please try again in a few seconds.",
        retry_after=limits.PARSE_RETRY_AFTER_S,
    )


class _Slot:
    def __init__(self, st: dict, sem: asyncio.Semaphore):
        self._st, self._sem, self._released = st, sem, False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._st["running"] -= 1
            self._sem.release()


async def _acquire() -> _Slot:
    st = _admission()
    sem: asyncio.Semaphore = st["sem"]
    if sem.locked():
        if st["waiting"] >= st["key"][1]:
            raise _busy()
        st["waiting"] += 1
        try:
            await asyncio.wait_for(sem.acquire(), limits.PARSE_QUEUE_WAIT_S)
        except TimeoutError:
            raise _busy() from None
        finally:
            st["waiting"] -= 1
    else:
        await sem.acquire()  # a free slot: returns without yielding
    st["running"] += 1
    return _Slot(st, sem)


# --- the child ---------------------------------------------------------------------------------


@dataclass
class _Outcome:
    payload: dict | None = None      # the child's JSON object, if it wrote a valid one
    returncode: int | None = None
    timed_out: bool = False
    overflow: bool = False           # it wrote more than the cap allows
    elapsed: float = 0.0
    stderr: bytes = b""


def _child_env() -> dict:
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.setdefault("PATH", os.defpath)
    env.update(_ENV_FORCE)
    return env


def _header(content: bytes, filename: str | None, max_text_chars: int) -> bytes:
    paths: list[str] = []
    room = 8 * 1024
    for entry in sys.path:
        if entry and os.path.isdir(entry) and room - len(entry) > 0:
            paths.append(entry)
            room -= len(entry) + 4
    header = {
        "v": parse_worker.PROTOCOL,
        "size": len(content),
        "filename": (filename or "")[:255] or None,
        "mem_mb": limits.PARSE_CHILD_MEM_MB,
        "cpu_s": limits.PARSE_CHILD_CPU_S,
        # The child ends itself a little after the parent would have killed it.
        "alarm_s": int(limits.PARSE_WALL_S) + 5,
        "sys_path": paths,
        "max_text_chars": max_text_chars,
        # The limits as the parent's modules hold them now, so that changing one here (an
        # operator's setting, or a test) changes it in the child as well.
        "pdf": {n: getattr(pdf_text, n) for n in parse_worker._PDF_LIMITS if hasattr(pdf_text, n)},
        "docx": {n: getattr(parser_module, n) for n in parse_worker._DOCX_LIMITS if hasattr(parser_module, n)},
    }
    return json.dumps(header).encode("utf-8") + b"\n"


def _kill(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the child's process group (it leads its own, see start_new_session)."""
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


async def _drain(reader: asyncio.StreamReader) -> None:
    with contextlib.suppress(Exception):
        while await reader.read(1 << 16):
            pass


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Kill the child if it is still running and wait until it is gone.

    Waiting is not enough on its own. asyncio finishes `wait()` only once the child's pipes have
    been closed as well, and a pipe whose reader stopped reading (flow control pauses it) is never
    closed, so a child killed in the middle of writing a flood would leave `wait()` hanging for
    ever. The pipes are read to the end first; the child is dead, so there is little left in them."""
    _kill(proc)
    try:
        await asyncio.wait_for(asyncio.gather(_drain(proc.stdout), _drain(proc.stderr), proc.wait()), 10)
    except TimeoutError:
        log.error("document reader process %s did not exit after SIGKILL", proc.pid)


async def _send(proc: asyncio.subprocess.Process, data: bytes) -> None:
    try:
        proc.stdin.write(data)
        await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the child ended before reading it all; its exit status says why
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()


async def _collect(proc: asyncio.subprocess.Process, cap: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await proc.stdout.read(1 << 16)
        if not chunk:
            return b"".join(chunks), False
        total += len(chunk)
        if total > cap:
            return b"", True
        chunks.append(chunk)


async def _collect_stderr(proc: asyncio.subprocess.Process) -> bytes:
    kept = b""
    while True:
        chunk = await proc.stderr.read(1 << 14)
        if not chunk:
            return kept
        if len(kept) < _STDERR_KEPT:
            kept += chunk[: _STDERR_KEPT - len(kept)]  # the rest is drained so the child never blocks on a full pipe


async def _talk(proc: asyncio.subprocess.Process, data: bytes, cap: int, out: _Outcome) -> None:
    sender = asyncio.ensure_future(_send(proc, data))
    errors = asyncio.ensure_future(_collect_stderr(proc))
    try:
        raw, out.overflow = await _collect(proc, cap)
        if out.overflow:
            return
        await proc.wait()
        out.stderr = await errors
        out.returncode = proc.returncode
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get("v") == parse_worker.PROTOCOL:
                    out.payload = payload
            except ValueError:
                pass
    finally:
        sender.cancel()
        errors.cancel()


async def _run_child(content: bytes, filename: str | None, max_text_chars: int) -> _Outcome:
    out = _Outcome()
    # Worst case a character takes 6 bytes of JSON (a control character as \u00XX), plus the
    # envelope. A child that writes more than this is not returning a document.
    cap = max_text_chars * 6 + (1 << 20)
    payload = _header(content, filename, max_text_chars) + content
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-E", "-s", "-m", _WORKER_MODULE,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(_ROOT), env=_child_env(), start_new_session=True,
        )
    except OSError as exc:
        raise ParseUnavailableError("the document reader could not be started") from exc

    started = time.monotonic()
    try:
        await asyncio.wait_for(_talk(proc, payload, cap, out), limits.PARSE_WALL_S)
    except TimeoutError:
        out.timed_out = True
    finally:
        # Whatever happened (finished, timed out, too much output, the request was cancelled):
        # the child does not outlive this call.
        await _reap(proc)
        out.elapsed = time.monotonic() - started
        if out.returncode is None:
            out.returncode = proc.returncode
    return out


# --- from the child's answer to what the endpoint raises ---------------------------------------

_CRASH = {signal.SIGSEGV, signal.SIGBUS, signal.SIGILL, signal.SIGFPE}
_TIME = {signal.SIGXCPU, signal.SIGALRM}


def _interpret(out: _Outcome, wall_s: float) -> ParsedDocument:
    p = out.payload
    if p is not None:
        if p.get("ok"):
            return ParsedDocument(
                text=p.get("text") or "",
                format=p.get("format") or "txt",
                footnote_count=int(p.get("footnote_count") or 0),
                endnote_count=int(p.get("endnote_count") or 0),
                warnings=[str(w) for w in (p.get("warnings") or [])],
            )
        message = str(p.get("message") or "")
        kind = p.get("kind")
        if kind == "too_long":
            raise DocumentTooLongError(message)
        if kind == "complex":
            raise DocumentTooComplexError(message)
        if kind == "unsupported":
            raise UnsupportedDocumentError(message)
        raise UnsupportedDocumentError(_UNREADABLE)

    if out.timed_out:
        raise DocumentTooComplexError(limits.complex_message(
            f"reading it took longer than the {wall_s:g} seconds one upload is allowed"))
    if out.overflow:
        raise DocumentTooComplexError(limits.complex_message(
            "the text it holds is larger than one upload is allowed to produce"))
    rc = out.returncode
    if rc is not None and rc < 0:
        sig = -rc
        if sig in _CRASH:
            return _raise_unreadable(out)
        if sig in _TIME:
            raise DocumentTooComplexError(limits.complex_message(
                "reading it used more processor time than one upload is allowed"))
        # SIGABRT is what pdfium does when it cannot allocate; SIGKILL is the kernel's own
        # out-of-memory kill or the CPU limit's hard stop.
        raise DocumentTooComplexError(limits.complex_message(
            "it needed more memory or time than one upload is allowed"))
    return _raise_unreadable(out)


def _raise_unreadable(out: _Outcome):
    log.warning("document reader ended without a result (exit %s, %.1fs): %s",
                out.returncode, out.elapsed, out.stderr[-300:].decode("utf-8", "replace").strip())
    raise UnsupportedDocumentError(_UNREADABLE)


async def parse_isolated(content: bytes, filename: str | None = None, *, max_text_chars: int | None = None) -> ParsedDocument:
    """Parse `content` in a child process. Raises what DocumentParser.parse_document raises
    (UnsupportedDocumentError, DocumentTooLongError), DocumentTooComplexError when the child
    was stopped for memory, time or output size, ParseBusyError when there is no room, and
    ParseUnavailableError when the child could not be started."""
    max_text = max_text_chars if max_text_chars else limits.MAX_TEXT_CHARS
    slot = await _acquire()
    try:
        wall = limits.PARSE_WALL_S
        out = await _run_child(content, filename, max_text)
    finally:
        slot.release()
    if out.payload is None and out.returncode not in (0, None):
        log.info("document reader stopped: exit %s after %.1fs (%d bytes in, timed_out=%s)",
                 out.returncode, out.elapsed, len(content), out.timed_out)
    return _interpret(out, wall)
