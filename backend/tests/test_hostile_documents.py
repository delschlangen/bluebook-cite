"""Hostile and extreme uploads, through the real thing: the endpoint, the child process, the real
reader. Every case is generated here (tests/hostile.py), none is checked in, and each is a shape
that took the server down or froze it before documents were read in a child:

* an 862-byte PDF whose form XObject draws itself (pdfium allocates until it aborts)
* ten million "q" operators; a flate stream that expands a thousandfold
* one million characters on a single page; two million, over the text limit
* an unbroken run of 64,000 letters, digits, a URL, dots or hyphens (a regular expression that
  holds the interpreter lock: 49 seconds frozen for a 664-byte file)
* a page of scattered words that quotes "(cid:12)" (pdfminer: two minutes)
* a flate bomb with no /Root, so that the fallback reader meets it
* a PDF whose /Count lies in either direction
* Word: 44 KB of unclosed tags, 60 KB of empty paragraphs, tables nested to any depth, a zip with
  thousands of entries

For each: the right status and a message that says what to do, within a few seconds, with the
server still answering /health afterwards, its own memory still small, and no child left behind.
"""

import os
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import limits
from tests.hostile import (
    cid_scattered_pdf,
    empty_paragraph_docx,
    flate_bomb_pdf,
    form_recursion_pdf,
    many_entries_zip,
    many_ops_pdf,
    missing_root_bomb_pdf,
    nested_tables_docx,
    one_page_pdf,
    pages_pdf,
    run_pdf,
    unclosed_tag_docx,
)

ORIGIN = "https://delschlangen.com"


@pytest.fixture(scope="module")
def http():
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def upload(client, name: str, data: bytes):
    started = time.monotonic()
    response = client.post(
        "/api/upload", files={"file": (name, data, "application/octet-stream")}, headers={"Origin": ORIGIN}
    )
    return response, time.monotonic() - started


def children() -> list[int]:
    """Document-reader processes that are children of this one and still exist."""
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmdline = handle.read()
            with open(f"/proc/{entry}/stat") as handle:
                ppid = int(handle.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        if b"parse_worker" in cmdline and ppid == os.getpid():
            found.append(int(entry))
    return found


def rss_mb() -> float:
    with open("/proc/self/status") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("no VmRSS")


TOO_COMPLEX = "too complex to read within this server's limits"

LONG = {"app.services.pdf_text.MAX_PDF_PAGES": 400}

# (name, how to build it, the statuses that are right, a fragment of the message, the most seconds it
# may take, limits to set for this case)
CASES = [
    ("form XObject that draws itself (862 B)", form_recursion_pdf, (413,), TOO_COMPLEX, 20, {}),
    ("ten million q operators (20 KB)", many_ops_pdf, (413,), TOO_COMPLEX, 12, {}),
    ("flate bomb: 50 MB of spaces, 128 MB allowed", lambda: flate_bomb_pdf(50), (413,), TOO_COMPLEX, 12, {"app.limits.PARSE_CHILD_MEM_MB": 128}),
    ("flate bomb: 1.2 GB of spaces (1.2 MB file), default limits", lambda: flate_bomb_pdf(1200), (413,), TOO_COMPLEX, 20, {}),
    ("one page of two million characters", lambda: one_page_pdf(2_000_000), (413,), "1,500,000-character limit", 20, {}),
    ("one page of one million characters", lambda: one_page_pdf(1_000_000), (200,), "", 20, {}),
    ("64,000 letters in one run (664 B)", lambda: run_pdf("letters"), (200,), "", 8, {}),
    ("64,000 capitals", lambda: run_pdf("capitals"), (200,), "", 8, {}),
    ("64,000 letters of mixed case", lambda: run_pdf("mixed"), (200,), "", 8, {}),
    ("64,000 digits", lambda: run_pdf("digits"), (200,), "", 8, {}),
    ("a URL-like run", lambda: run_pdf("url"), (200,), "", 8, {}),
    ("64,000 dots", lambda: run_pdf("dots"), (200,), "", 8, {}),
    ("64,000 hyphens", lambda: run_pdf("hyphens"), (200,), "", 8, {}),
    ("2,000 scattered words and a quoted (cid:", lambda: cid_scattered_pdf(2000), (200,), "", 15, {}),
    ("flate bomb with no /Root (the fallback reader's)", lambda: missing_root_bomb_pdf(200), (400, 413, 415), "", 25, {}),
    ("/Count of 5 on a file of 60 pages, limit 40", lambda: pages_pdf(60, 5), (413,), "more than 40 pages", 15, {"app.services.pdf_text.MAX_PDF_PAGES": 40}),
    ("/Count of 450 on a file of 3 pages", lambda: pages_pdf(3, 450), (200,), "", 8, {}),
    ("44 KB of unclosed <w:b> tags", unclosed_tag_docx, (413,), "nested more than 200 levels deep", 15, {}),
    ("60 KB of empty paragraphs", empty_paragraph_docx, (413,), "more than 4,000,000 elements", 20, {}),
    ("tables nested 300 deep", lambda: nested_tables_docx(300), (413,), "nested more than 200 levels deep", 15, {}),
    ("tables nested 20 deep", lambda: nested_tables_docx(20), (200,), "", 8, {}),
    ("a zip with 3,000 entries", many_entries_zip, (415,), "too many parts", 8, {}),
]


def test_the_corpus_is_refused_or_read_cleanly_and_the_server_is_unharmed(http, monkeypatch):
    boot = http.get("/health").json()["boot_id"]
    upload(http, "warmup.txt", b"warm up the reader and the allocator")
    baseline = rss_mb()
    failures = []
    for name, build, statuses, fragment, seconds, overrides in CASES:
        with monkeypatch.context() as case:
            for target, value in overrides.items():
                case.setattr(target, value)
            data = build()
            response, took = upload(http, "hostile.bin", data)
        detail = str(response.json().get("detail", ""))
        problems = []
        if response.status_code not in statuses:
            problems.append(f"status {response.status_code}, wanted {statuses}: {detail[:120]}")
        if fragment and fragment not in detail:
            problems.append(f"message {detail[:140]!r} lacks {fragment!r}")
        if took > seconds:
            problems.append(f"took {took:.1f}s, over {seconds}s")
        if response.status_code >= 400 and response.headers.get("access-control-allow-origin") != ORIGIN:
            problems.append("the refusal carries no CORS header, so the page could not read it")
        health = http.get("/health")
        if health.status_code != 200 or health.json()["boot_id"] != boot:
            problems.append("the server did not answer /health, or restarted")
        if problems:
            failures.append(f"{name}: " + "; ".join(problems))
    assert not failures, "\n" + "\n".join(failures)
    growth = rss_mb() - baseline
    assert growth < 60, f"the server grew by {growth:.0f} MB over {len(CASES)} hostile uploads"
    assert children() == [], "a document reader was left running"


def test_a_pdf_that_says_5_pages_and_holds_401_is_refused_not_read_as_5(http):
    """The default limit (400): a silent truncation to 5 pages was the bug."""
    response, took = upload(http, "lies.pdf", pages_pdf(401, 5))
    assert response.status_code == 413
    assert "more than 400 pages" in response.json()["detail"]
    assert took < 15


def test_a_pdf_that_says_450_pages_and_holds_3_is_read_and_says_so(http):
    response, _ = upload(http, "lies.pdf", pages_pdf(3, 450))
    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == ["This PDF says it has 450 pages but the file holds 3. All 3 were read."]
    assert body["full_text"].count("A page of ordinary text") == 3


def test_a_30_kb_run_of_digits_in_a_text_file_uploads_and_is_not_a_problem_here(http):
    """The upload only reads it (the analysis of such text is another matter): no quadratic step."""
    response, took = upload(http, "digits.txt", b"7" * 30_000)
    assert response.status_code == 200 and took < 5


def test_hostile_uploads_in_a_row_do_not_starve_a_normal_one(http):
    """Two slow children at a time, a queue of three, and a normal document in between: the normal
    one is read, or told the server is busy, within seconds. It is never the slow ones' problem."""
    import concurrent.futures

    monkey = limits.PARSE_MAX_CONCURRENT
    assert monkey >= 1
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        bad = [pool.submit(upload, http, "loop.pdf", form_recursion_pdf()) for _ in range(3)]
        time.sleep(0.5)
        good = pool.submit(upload, http, "ok.txt", b"See Brown v. Board of Education, 347 U.S. 483 (1954).")
        response, took = good.result(timeout=60)
        results = [f.result(timeout=90) for f in bad]
    assert response.status_code in (200, 503), response.text
    if response.status_code == 503:
        assert "busy" in response.json()["detail"] and response.headers["retry-after"]
    assert took < 40
    assert all(r.status_code in (413, 503) for r, _ in results)
    assert children() == []
