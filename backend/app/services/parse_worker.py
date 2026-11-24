"""The child process that reads one uploaded document. Started by services/sandbox.py:

    python -E -s -m app.services.parse_worker

stdin   one header line (JSON, ends with a newline, at most HEADER_MAX bytes), then exactly
        header["size"] bytes: the file.
stdout  exactly one JSON object, written once at the end. Never pickle: the parent does not
        trust this process's output any more than it trusts the file.
stderr  free text for the log (a traceback, a native library's complaint); the parent keeps
        only the first few kilobytes.

Why a separate process at all: see limits.py. In short, pdfium aborts instead of raising when it
cannot allocate, and a regular expression that holds the interpreter lock cannot be interrupted
by a thread, a deadline or a timeout. A process can be killed.

This module imports only the standard library at the top. The limits go on before anything
heavy (pypdfium2, pdfminer, zipfile and the XML parser) is imported, and before the file is
read, so the file never meets code that is not yet bounded.
"""
from __future__ import annotations

import json
import os
import signal
import sys

PROTOCOL = 1
HEADER_MAX = 16 * 1024

# Names the header may set on the reader modules. An allowlist, because the header is built by
# the parent from its own module attributes (so a test or an operator that changes a limit in the
# server process changes it in the child too) and the child should accept nothing else.
_PDF_LIMITS = frozenset({
    "MAX_PDF_PAGES", "MAX_TEXT_CHARS", "PDF_TIME_BUDGET_S", "PDF_MAX_PAGE_CHARS",
    "PDF_SECOND_OPINION_MAX_CHARS", "PDF_SECOND_OPINION_BUDGET_S", "MAX_PDF_FALLBACK_PAGES",
})
_DOCX_LIMITS = frozenset({
    "MAX_ZIP_ENTRIES", "MAX_EXPANDED_BYTES", "MAX_PART_BYTES", "DOCX_MAX_ELEMENTS", "DOCX_MAX_DEPTH",
})


def _limit_resources(mem_mb: int, cpu_s: int) -> None:
    """Address space, CPU time and core dumps. A limit the platform will not accept is skipped,
    not fatal: the parent's wall-clock kill does not depend on these.

    RLIMIT_AS counts virtual address space (mapped libraries and reserved ranges included),
    not resident memory, and a native library that cannot allocate may abort (SIGABRT) rather
    than raise MemoryError; both end the child, which is the point."""
    try:
        import resource
    except ImportError:  # not POSIX: only the parent's wall-clock kill applies
        return

    def lower(which: int, value: int, grace: int = 0) -> None:
        try:
            _soft, hard = resource.getrlimit(which)
            hard_value = value + grace
            if hard != resource.RLIM_INFINITY:
                value, hard_value = min(value, hard), min(hard_value, hard)
            resource.setrlimit(which, (value, hard_value))
        except (ValueError, OSError):
            pass

    if mem_mb > 0:
        lower(resource.RLIMIT_AS, mem_mb * 1024 * 1024)
    if cpu_s > 0:
        # SIGXCPU at the soft limit (the parent can tell it was the processor time), SIGKILL a
        # few seconds later at the hard limit if the process somehow carries on.
        lower(resource.RLIMIT_CPU, cpu_s, grace=5)
    lower(resource.RLIMIT_CORE, 0)


def _emit(fd: int, payload: dict) -> None:
    # "replace": a lone surrogate (a PDF can produce one) would make the text impossible to
    # encode later, when the page's response is written.
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8", "replace")
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _fail(fd: int, kind: str, message: str) -> None:
    _emit(fd, {"v": PROTOCOL, "ok": False, "kind": kind, "message": message})


def _read_exactly(stream, size: int) -> bytes:
    data = stream.read(size)
    return data if data is not None else b""


def main() -> int:
    # Keep the result channel clean: a native library or a stray print that writes to stdout
    # must not be able to corrupt the one JSON object. The real stdout becomes `out`, and file
    # descriptor 1 now points at stderr.
    out = os.dup(1)
    os.dup2(2, 1)

    stdin = sys.stdin.buffer
    line = stdin.readline(HEADER_MAX + 1)
    try:
        if len(line) > HEADER_MAX or not line.endswith(b"\n"):
            raise ValueError("header too long or unterminated")
        header = json.loads(line)
        if header.get("v") != PROTOCOL:
            raise ValueError("protocol version")
        size = int(header["size"])
        if size < 0:
            raise ValueError("size")
    except (ValueError, KeyError, TypeError):
        _fail(out, "failed", "bad request")
        return 2

    _limit_resources(int(header.get("mem_mb") or 0), int(header.get("cpu_s") or 0))
    if hasattr(signal, "alarm") and header.get("alarm_s"):
        # SIGALRM's default action ends the process. It does not need the interpreter, so it
        # also works when a regular expression is holding it, and it ends a child whose parent
        # has vanished.
        signal.alarm(int(header["alarm_s"]))

    data = _read_exactly(stdin, size)
    if len(data) != size:
        _fail(out, "failed", "the upload was cut short")
        return 2

    # The package root is the working directory, so `-m` found this module. The parent's own
    # import path is passed on for anything it installed somewhere else (a vendored directory,
    # a platform that sets sys.path in code rather than the environment, which -E ignores).
    for entry in reversed(header.get("sys_path") or []):
        if isinstance(entry, str) and entry not in sys.path:
            sys.path.insert(1, entry)

    return _run(out, header, data)


def _run(out: int, header: dict, data: bytes) -> int:
    from .. import limits
    from . import parser as parser_module
    from . import pdf_text

    for name, value in (header.get("pdf") or {}).items():
        if name in _PDF_LIMITS:
            setattr(pdf_text, name, value)
    for name, value in (header.get("docx") or {}).items():
        if name in _DOCX_LIMITS:
            setattr(parser_module, name, value)
    max_text = int(header.get("max_text_chars") or limits.MAX_TEXT_CHARS)

    try:
        parsed = parser_module.DocumentParser(max_text_chars=max_text).parse_document(data, header.get("filename"))
    except parser_module.DocumentTooComplexError as exc:
        _fail(out, "complex", str(exc))
    except parser_module.DocumentTooLongError as exc:
        _fail(out, "too_long", str(exc))
    except parser_module.UnsupportedDocumentError as exc:
        _fail(out, "unsupported", str(exc))
    except MemoryError:
        _fail(out, "complex", limits.complex_message("it needed more memory than one upload is allowed"))
    except BaseException as exc:  # noqa: BLE001 - nothing the file does may leave this process silent
        import traceback

        traceback.print_exc()
        _fail(out, "failed", type(exc).__name__)
    else:
        if len(parsed.text) > max_text:
            _fail(out, "too_long", limits.too_long_message(len(parsed.text), max_text))
        else:
            _emit(out, {
                "v": PROTOCOL, "ok": True, "format": parsed.format, "text": parsed.text,
                "footnote_count": parsed.footnote_count, "endnote_count": parsed.endnote_count,
                "warnings": list(parsed.warnings),
            })
    sys.stderr.flush()
    # Skip interpreter teardown: it can only run native finalizers that might misbehave on a
    # hostile file, and the result is already written.
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
