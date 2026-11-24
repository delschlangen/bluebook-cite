"""The PDF reader: fast, memory-bounded and faithful on realistic legal layouts.

Two kinds of document are used. The fixtures in tests/fixtures/pdf are real PDFs written by
Chromium, reportlab and LibreOffice (law review articles with footnotes, two columns, pleading
paper, hyphenation, ligatures, running footers), each with the list of citations it contains.
Everything long or extreme is generated in code by docfactory.make_pdf_pages, so no large
binary has to be checked in.
"""

import json
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import app.services.pdf_text as P
from app.services.parser import DocumentParser, DocumentTooComplexError
from tests.docfactory import make_pdf_pages
from tests.hostile import cid_scattered_pdf, one_page_pdf, pages_pdf

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


@pytest.fixture(autouse=True)
def the_reader_lock_is_never_left_held():
    """Runs after every test in this module. A leaked lock would otherwise make every later
    test wait on it forever, so one regression would look like a frozen suite. Release it
    and fail the test that leaked it."""
    yield
    if P._PDFIUM_LOCK.locked():
        P._PDFIUM_LOCK.release()
        pytest.fail("this test left the PDF reader's lock held")


def load(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


def truth(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.truth.json").read_text())


def squash(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.lower())


def found_rate(name: str, text: str) -> float:
    expected = [c for c in truth(name)["cites"] if c["kind"] != "id"]
    squashed = squash(text)
    return sum(1 for c in expected if squash(c["text"]) in squashed) / len(expected)


def assert_reader_lock_is_free() -> None:
    """The reader holds one lock while it works. After a limit or a time budget stops a read,
    the lock must be free again.

    Always leaves the lock released, even on failure: a test that found it held and moved on
    would deadlock every later test in the run instead of failing once and clearly."""
    free = P._PDFIUM_LOCK.acquire(blocking=False)
    if not free:
        # Held by a generator that was never closed. Release it so later tests are not poisoned.
        try:
            P._PDFIUM_LOCK.release()
        except RuntimeError:
            pass
    else:
        P._PDFIUM_LOCK.release()
    assert free, "the PDF reader's lock was left held after the read stopped"


def text_pdf(pages: int, lines_per_page: int = 30, footer: str | None = None) -> bytes:
    """A generated PDF of `pages` pages, each with distinct body lines and an optional footer."""
    out = []
    for p in range(pages):
        page = [
            (720 - 14 * i, f"Page {p + 1} line {i}: Brandenburg v. Ohio, 395 U.S. 444 (1969).")
            for i in range(lines_per_page)
        ]
        if footer:
            page.append((40, footer.format(page=p + 1, total=pages)))
        out.append(page)
    return make_pdf_pages(out)


# --- fidelity on real documents ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name,minimum",
    [
        ("a_lawreview_chromium", 1.0),
        ("a2_lawreview_reportlab", 1.0),
        ("b_policy_chrome_hf", 1.0),
        ("b2_ssrn_style_hf", 1.0),
        ("c_two_column_chromium", 0.95),
        ("d_hyphenation_reportlab", 0.97),
        ("d2_softhyphen_chromium", 0.97),
        ("e_typography_chromium", 1.0),
        ("e2_ligature_codepoints_reportlab", 1.0),
        ("f_brief_pleading_chromium", 0.97),
        ("f2_brief_pleading_reportlab", 0.97),
        ("f3_brief_pleading_libreoffice", 0.97),
        ("g_wrap_straddle_chromium", 1.0),
    ],
)
def test_every_citation_in_a_real_document_survives_extraction(name, minimum):
    result = P.read_pdf(load(name))
    assert found_rate(name, result.text) >= minimum


def test_running_footers_urls_and_page_numbers_are_gone_but_citations_are_not():
    result = P.read_pdf(load("b_policy_chrome_hf"))
    assert "orionpolicy.org" not in result.text
    assert "Orion Policy" not in result.text
    assert not re.search(r"(?m)^\d+/\d+$", result.text)
    assert found_rate("b_policy_chrome_hf", result.text) == 1.0


def test_footnotes_are_marked_in_the_syntax_the_word_reader_writes():
    result = P.read_pdf(load("a2_lawreview_reportlab"))
    marks = [int(m) for m in re.findall(r"(?m)^\[\^(\d+)\] ", result.text)]
    assert len(marks) >= 36
    assert marks == list(range(1, len(marks) + 1))


def test_pleading_line_numbers_are_dropped():
    for name in ("f_brief_pleading_chromium", "f2_brief_pleading_reportlab"):
        result = P.read_pdf(load(name))
        lone = [ln for ln in result.text.split("\n") if re.fullmatch(r"\d{1,2}", ln.strip())]
        assert len(lone) <= 2, (name, lone[:5])


def test_two_columns_are_read_column_by_column_not_across():
    result = P.read_pdf(load("c_two_column_chromium"))
    # Reading across the page glues the right column's lines onto the left column's, which
    # breaks every citation that wraps. 0.95 recall above is the evidence; this is the cause.
    assert found_rate("c_two_column_chromium", result.text) >= 0.95


def test_a_recurring_footnote_citation_is_not_mistaken_for_a_running_footer():
    """The last footnote on half the pages is 'Id.' and on the other half a statute. A
    running-line remover that is too eager deletes real footnotes."""
    name = "z_adversarial_recurring_footnotes_chromium"
    result = P.read_pdf(load(name))
    assert found_rate(name, result.text) >= 0.97


def test_ligature_code_points_are_expanded_in_a_real_pdf():
    result = P.read_pdf(load("e2_ligature_codepoints_reportlab"))
    assert not re.search("[ﬀ-ﬆ]", result.text)


# --- length: speed, memory, limits -------------------------------------------------------------


def test_a_three_hundred_page_pdf_reads_in_seconds():
    data = text_pdf(300)
    started = time.monotonic()
    result = P.read_pdf(data)
    assert result.pages == 300
    assert time.monotonic() - started < 15
    assert "Page 300 line 29" in result.text


def test_memory_does_not_grow_with_page_count():
    """The reason this reader replaced pdfplumber, which held about 9 MB per page (2.5 GB for
    273 pages) and killed the server. Peak memory is measured in a fresh process for a short
    and a long document; a reader that keeps pages would differ by hundreds of megabytes."""
    script = textwrap.dedent(
        """
        import resource, sys
        from app.services.pdf_text import read_pdf
        data = open(sys.argv[1], "rb").read()
        read_pdf(data)
        print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
        """
    )

    def peak_mb(pages: int, tmp: Path) -> float:
        path = tmp / f"doc{pages}.pdf"
        path.write_bytes(text_pdf(pages, lines_per_page=45))
        out = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        return float(out.stdout.strip())

    import tempfile

    with tempfile.TemporaryDirectory() as d:
        short, long = peak_mb(30, Path(d)), peak_mb(300, Path(d))
    assert long - short < 80, f"30 pages peaked at {short:.0f} MB, 300 pages at {long:.0f} MB"


def test_the_page_limit_is_enforced_before_any_page_is_read(monkeypatch):
    called = []
    monkeypatch.setattr(P, "iter_pdf_pages", lambda *a, **k: called.append(1) or iter(()))
    with pytest.raises(P.PdfTooLongError) as caught:
        P.read_pdf(text_pdf(40), max_pages=25)
    assert "40 pages" in str(caught.value)
    assert "25-page limit" in str(caught.value)
    assert not called, "pages were read even though the limit was exceeded"


def test_the_text_limit_stops_a_read_part_way():
    with pytest.raises(P.PdfTooLongError) as caught:
        P.read_pdf(text_pdf(60), max_chars=20_000)
    assert "20,000-character limit" in str(caught.value)


def test_page_count_is_instant_even_for_thousands_of_pages():
    data = make_pdf_pages([[] for _ in range(5000)])
    started = time.monotonic()
    assert P.page_count(data) == 5000
    assert time.monotonic() - started < 0.5
    with pytest.raises(P.PdfTooLongError):
        P.read_pdf(data)


def test_a_limit_being_hit_does_not_leave_the_reader_locked():
    """The page generator holds the reader's lock while it is open. A for-loop left by an
    exception does not close it: the traceback keeps the generator, and with it the lock,
    alive for as long as the exception is. Anything that keeps the exception (logging, a
    chained `raise ... from`) would hold the lock and make the next upload wait. The exception
    is deliberately kept alive here, because discarding it would release the lock by accident
    and hide the problem."""
    with pytest.raises(P.PdfTooLongError) as caught:
        P.read_pdf(text_pdf(60), max_chars=20_000)
    assert_reader_lock_is_free()
    assert "limit" in str(caught.value)  # the exception is still referenced here


def test_a_time_budget_stops_a_slow_read_and_frees_the_lock():
    with pytest.raises(P.PdfReadError) as caught:
        P.read_pdf(text_pdf(20), time_budget=0.0)
    assert "too long" in str(caught.value)
    assert_reader_lock_is_free()


def test_waiting_for_the_reader_gives_up_with_a_clear_message(monkeypatch):
    """If the lock is held (a queue of large files, or a bug), an upload must be told to try
    again rather than wait for ever."""
    monkeypatch.setattr(P, "_LOCK_WAIT_S", 0.2)
    P._PDFIUM_LOCK.acquire()
    try:
        started = time.monotonic()
        with pytest.raises(P.PdfReadError) as caught:
            P.read_pdf(text_pdf(2))
        assert time.monotonic() - started < 5
        assert "busy" in str(caught.value)
    finally:
        P._PDFIUM_LOCK.release()


def test_eight_threads_get_identical_results():
    import threading

    data = load("a2_lawreview_reportlab")
    reference = P.read_pdf(data).text
    outcomes, errors = [], []

    def work():
        try:
            for _ in range(5):
                outcomes.append(P.read_pdf(data).text == reference)
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(outcomes) == 40 and all(outcomes)


# --- files that are not ordinary text PDFs -----------------------------------------------------


def test_a_scanned_pdf_returns_no_text_rather_than_an_error():
    scanned = make_pdf_pages([[], [], []])  # pages with no text at all, as an image-only scan has
    result = P.read_pdf(scanned)
    assert result.text.strip() == ""
    assert result.pages == 3


def test_a_pdf_with_no_pages_has_a_clear_message():
    with pytest.raises(P.PdfReadError):
        P.read_pdf(make_pdf_pages([]))


def test_a_password_protected_pdf_has_a_clear_message():
    with pytest.raises(P.PdfReadError) as caught:
        P.read_pdf(load("i_encrypted_userpw"))
    assert "password" in str(caught.value).lower()


def test_an_owner_password_only_pdf_reads_and_warns():
    result = P.read_pdf(load("i_encrypted_ownerpw_only"))
    assert "Brandenburg v. Ohio, 395 U.S. 444" in result.text
    assert any("encrypted" in w for w in result.warnings)


@pytest.mark.parametrize("name", ["i_truncated_55pct", "i_truncated_noeof_trailer"])
def test_a_truncated_pdf_is_a_clear_error(name):
    with pytest.raises(P.PdfReadError) as caught:
        P.read_pdf(load(name))
    assert "damaged or incomplete" in str(caught.value)


def test_not_a_pdf_is_a_clear_error():
    with pytest.raises(P.PdfReadError):
        P.read_pdf(b"%PDF-1.4\nthis is not really a pdf\n")


def test_a_garbled_text_layer_is_rescued_by_the_second_reader():
    # Fonts with no ToUnicode map: pdfium returns shifted letters, pdfminer recovers the text.
    result = P.read_pdf(load("i_no_tounicode_chromium"))
    assert result.engine == "pdfium+pdfminer"
    stop, ctrl, _ = P._quality(result.text)
    assert stop > 0.2 and ctrl < 0.001


def test_an_unrecoverable_text_layer_is_a_clear_error_not_garbage():
    with pytest.raises(P.PdfReadError) as caught:
        P.read_pdf(load("i_no_tounicode_libreoffice"))
    assert "text layer is unreadable" in str(caught.value)


def test_a_pdf_that_claims_more_pages_than_it_has_is_read_whole_and_says_so():
    """A /Count of 9 on a 7-page file. The two pages that do not exist are not 'skipped' and not
    'scanned pages that need OCR': there is nothing to skip or to scan."""
    result = P.read_pdf(load("i_count_lies_9_for_7"))
    assert result.pages == 7
    assert result.warnings == ["This PDF says it has 9 pages but the file holds 7. All 7 were read."]
    assert found_rate("a_lawreview_chromium", result.text) > 0.9


# --- what counts as garbled --------------------------------------------------------------------


def test_a_document_that_is_all_citations_is_not_mistaken_for_garbage():
    """A table of authorities or a works-cited list has almost no ordinary words ("the", "of",
    "and"), so a low word share looked like corruption and the whole file was refused as
    "unreadable". Text that merely lacks prose is not garbled."""
    result = P.read_pdf(text_pdf(12))
    assert result.pages == 12
    assert "Brandenburg v. Ohio" in result.text
    assert not any("unreadable" in w for w in result.warnings)


class TestGarbleEvidence:
    PROSE = "The court held that the statute does not apply to the conduct at issue in this case. " * 4
    CITES = "Brandenburg v. Ohio, 395 U.S. 444 (1969); Marbury v. Madison, 5 U.S. 137 (1803). " * 8

    def test_ordinary_prose_is_fine(self):
        assert P._garble_evidence(self.PROSE) is None

    def test_a_list_of_citations_is_only_weakly_suspicious(self):
        assert P._garble_evidence(self.CITES) == "weak"
        assert P._looks_garbled(self.CITES) is False

    def test_control_characters_are_strong_evidence(self):
        assert P._garble_evidence(self.PROSE + "\x01\x02\x03" * 20) == "strong"

    def test_cid_leakage_is_strong_evidence(self):
        assert P._garble_evidence(self.PROSE + " (cid:123)(cid:45)") == "strong"

    def test_a_short_page_is_never_judged(self):
        assert P._garble_evidence("\x01\x02") is None


# --- the fallback for a file the first reader cannot open --------------------------------------


class TestFallbackReaderHasTheSameCeilings:
    """When pdfium refuses a file, pdfminer reads it. That reader is about ten times slower,
    so it is the one that could run on and on over a large damaged file."""

    @pytest.fixture
    def pdfium_refuses(self, monkeypatch):
        def refuse(content):
            raise P.PdfReadError("This PDF looks damaged or incomplete.")

        monkeypatch.setattr(P, "page_count", refuse)

    def _pages(self, monkeypatch, texts):
        monkeypatch.setattr(P, "_pdfminer_pages", lambda content, page_numbers=None: iter(texts))

    def test_it_reads_the_file_when_pdfium_cannot(self, pdfium_refuses, monkeypatch):
        self._pages(
            monkeypatch,
            ["First page: Brandenburg v. Ohio, 395 U.S. 444 (1969).", "Second page: 42 U.S.C. § 1983 applies."],
        )
        result = P.read_pdf(b"%PDF-1.4 whatever")
        assert result.engine == "pdfminer"
        assert "Brandenburg v. Ohio" in result.text and "42 U.S.C. § 1983" in result.text

    def test_the_page_limit_applies(self, pdfium_refuses, monkeypatch):
        self._pages(monkeypatch, [f"Page {i} has enough text to count." for i in range(50)])
        with pytest.raises(P.PdfTooLongError):
            P.read_pdf(b"%PDF-1.4 whatever", max_pages=10)

    def test_the_text_limit_applies(self, pdfium_refuses, monkeypatch):
        self._pages(monkeypatch, ["x" * 1000 for _ in range(50)])
        with pytest.raises(P.PdfTooLongError):
            P.read_pdf(b"%PDF-1.4 whatever", max_chars=5000)

    def test_the_time_budget_applies(self, pdfium_refuses, monkeypatch):
        self._pages(monkeypatch, ["Some page text that is long enough." for _ in range(5)])
        with pytest.raises(P.PdfReadError) as caught:
            P.read_pdf(b"%PDF-1.4 whatever", time_budget=0.0)
        assert "too long" in str(caught.value)

    def test_a_file_neither_reader_can_open_reports_the_first_error(self, pdfium_refuses, monkeypatch):
        def explode(content, page_numbers=None):
            raise ValueError("not a pdf")
            yield  # pragma: no cover - makes this a generator

        monkeypatch.setattr(P, "_pdfminer_pages", explode)
        with pytest.raises(P.PdfReadError) as caught:
            P.read_pdf(b"%PDF-1.4 whatever")
        assert "damaged or incomplete" in str(caught.value)

    def test_a_slow_page_is_interrupted_inside_the_page_not_only_between_pages(self, pdfium_refuses, monkeypatch):
        """pdfminer's layout of one page can take minutes. The deadline check between pages never
        runs during it; the interval timer does. The stand-in spins in Python (as pdfminer does)
        for at most 10 s, so a regression is a slow failing test, not a hang."""
        def spin(content, page_numbers=None):
            end = time.monotonic() + 10
            while time.monotonic() < end:
                sum(range(1000))
            yield "never reached"

        monkeypatch.setattr(P, "_pdfminer_pages", spin)
        started = time.monotonic()
        with pytest.raises(P.PdfReadError, match="took too long"):
            P.read_pdf(b"%PDF-1.4 whatever", time_budget=0.5)
        assert time.monotonic() - started < 4


# --- the page count in the file is a claim ------------------------------------------------------


class TestPageCountIsCrossChecked:
    """pdfium trusts /Count. A /Count that is too small silently dropped the rest of a document
    (a 401-page file that said 5 gave a clean analysis of 5 pages); one that is too large refused a
    small file with 'this PDF has 450 pages' or told the person to OCR pages that do not exist."""

    def test_too_small_a_count_reads_the_rest_with_the_second_reader_and_says_so(self):
        result = P.read_pdf(pages_pdf(12, declared=5), max_pages=40)
        assert result.pages == 12
        assert result.engine == "pdfium+pdfminer"
        assert result.warnings == [
            "This PDF says it has 5 pages but the file holds 12. All of them were read, the extra ones with a slower reader."
        ]
        assert result.text.count("A page of ordinary text") == 12

    def test_too_small_a_count_cannot_get_a_long_file_past_the_page_limit(self):
        with pytest.raises(P.PdfTooLongError) as caught:
            P.read_pdf(pages_pdf(60, declared=5), max_pages=40)
        assert "more than 40 pages" in str(caught.value)

    @pytest.mark.parametrize("declared", [450, 100_000])
    def test_too_large_a_count_is_not_a_reason_to_refuse_a_small_file(self, declared):
        result = P.read_pdf(pages_pdf(3, declared=declared), max_pages=400)
        assert result.pages == 3
        assert result.warnings == [f"This PDF says it has {declared} pages but the file holds 3. All 3 were read."]

    def test_pages_that_do_not_exist_are_never_called_scanned(self):
        result = P.read_pdf(pages_pdf(3, declared=300), max_pages=400)
        assert not any("OCR" in w or "skipped" in w or "no readable text" in w for w in result.warnings)

    def test_a_count_that_is_right_costs_nothing_and_says_nothing(self, monkeypatch):
        monkeypatch.setattr(P, "_pdfminer_page_total", lambda *a, **k: pytest.fail("the second reader was asked"))
        result = P.read_pdf(pages_pdf(7, declared=7))
        assert result.pages == 7 and result.warnings == []

    def test_a_file_that_is_over_the_limit_says_how_many_pages_it_has(self):
        with pytest.raises(P.PdfTooLongError) as caught:
            P.read_pdf(pages_pdf(60, declared=60), max_pages=40)
        assert "60 pages" in str(caught.value)

    def test_a_count_that_is_too_large_and_over_the_limit_is_judged_by_the_pages_that_load(self):
        with pytest.raises(P.PdfTooLongError) as caught:
            P.read_pdf(pages_pdf(60, declared=5000), max_pages=40)
        assert "60 pages" in str(caught.value)


# --- a second opinion only when there is real evidence of garbling --------------------------------


class TestSecondOpinion:
    def test_a_page_that_merely_contains_the_text_cid_is_not_sent_to_the_slow_reader(self, monkeypatch):
        """A reviewer's page: 2,000 scattered words and the literal text '(cid:12)'. pdfminer's layout
        of it took two minutes, and a page that quotes the string is not garbled."""
        monkeypatch.setattr(P, "_pdfminer_pages", lambda *a, **k: pytest.fail("the second reader ran"))
        started = time.monotonic()
        result = P.read_pdf(cid_scattered_pdf(2000))
        assert time.monotonic() - started < 10
        assert result.engine == "pdfium" and "(cid:12)" in result.text

    def test_codes_that_make_up_the_page_are_evidence(self):
        leaking = "The court held. " + "(cid:12)(cid:45)(cid:7)" * 40
        assert P._garble_evidence(leaking) == "strong"
        assert P._quality(leaking)[2] is True

    def test_two_codes_in_a_page_of_text_are_not(self):
        page = ("The court held that the statute does not apply to the conduct at issue in this case. " * 30) + " (cid:12) (cid:13)"
        assert P._garble_evidence(page) is None
        assert P._quality(page)[2] is False

    def test_one_code_is_never_evidence(self):
        assert P._quality("x" * 500 + " (cid:12)")[2] is False
        assert P._quality("(cid:12)")[2] is False

    def test_the_second_reader_never_runs_while_the_pdfium_lock_is_held(self, monkeypatch):
        seen = []

        def spy(content, page_numbers=None):
            seen.append(P._PDFIUM_LOCK.locked())
            return iter(())

        monkeypatch.setattr(P, "_pdfminer_pages", spy)
        with pytest.raises(P.PdfReadError):          # the stand-in returns nothing, so the text stays unreadable
            P.read_pdf(load("i_no_tounicode_chromium"))
        assert seen and not any(seen), "pdfminer ran with the pdfium lock held, so every other upload waited for it"

    def test_a_page_larger_than_the_limit_is_not_given_a_second_opinion(self, monkeypatch):
        monkeypatch.setattr(P, "PDF_SECOND_OPINION_MAX_CHARS", 100)
        monkeypatch.setattr(P, "_pdfminer_pages", lambda *a, **k: pytest.fail("the second reader ran"))
        with pytest.raises(P.PdfReadError, match="text layer is unreadable"):
            P.read_pdf(load("i_no_tounicode_chromium"))

    def test_a_second_opinion_that_runs_on_is_cut_off_and_the_first_text_is_kept(self, monkeypatch):
        def spin(content, page_numbers=None):
            end = time.monotonic() + 10
            while time.monotonic() < end:
                sum(range(1000))
            yield "never reached"

        monkeypatch.setattr(P, "_pdfminer_pages", spin)
        monkeypatch.setattr(P, "PDF_SECOND_OPINION_BUDGET_S", 0.3)
        started = time.monotonic()
        with pytest.raises(P.PdfReadError, match="text layer is unreadable"):
            P.read_pdf(load("i_no_tounicode_chromium"))
        assert time.monotonic() - started < 5, "the second reader was not interrupted"

    def test_the_second_readers_total_time_is_bounded_across_pages(self, monkeypatch):
        calls = []

        def slow(content, page_numbers=None):
            calls.append(page_numbers)
            time.sleep(0.2)
            return iter(())

        monkeypatch.setattr(P, "_pdfminer_pages", slow)
        monkeypatch.setattr(P, "PDF_SECOND_OPINION_BUDGET_S", 0.5)
        with pytest.raises(P.PdfReadError):
            P.read_pdf(load("i_no_tounicode_chromium"))
        assert 1 <= len(calls) <= 4, f"{len(calls)} second opinions in a half-second budget"


# --- time and size are checked inside a page ------------------------------------------------------


class TestBoundsInsideAPage:
    def test_a_page_with_more_text_than_the_budget_has_left_is_refused_before_any_layout(self, monkeypatch):
        """50,000 characters is under the layout limit, so layout WOULD be built for it; it must not
        be, because the page cannot fit in the 20,000 the text budget allows."""
        monkeypatch.setattr(P, "_build_lines", lambda *a, **k: pytest.fail("layout was built for a page that cannot fit"))
        with pytest.raises(P.PdfTooLongError, match=r"20,000-character limit"):
            P.read_pdf(one_page_pdf(50_000), max_chars=20_000)
        with pytest.raises(P.PdfTooLongError, match=r"100,000-character limit"):
            P.read_pdf(one_page_pdf(300_000), max_chars=100_000)

    def test_a_page_over_the_layout_limit_is_read_without_layout_and_the_person_is_told(self, monkeypatch):
        monkeypatch.setattr(P, "_build_lines", lambda *a, **k: pytest.fail("layout was built for an enormous page"))
        result = P.read_pdf(one_page_pdf(120_000))
        assert len(result.text) > 119_000
        assert result.warnings == [
            "1 page(s) hold an unusually large amount of text and were read without layout analysis, so footnote marks may be missing there."
        ]

    def test_an_ordinary_page_still_gets_its_layout(self):
        result = P.read_pdf(load("a2_lawreview_reportlab"))
        assert "[^1]" in result.text and not result.warnings

    def test_the_layout_loop_checks_the_deadline_every_couple_of_thousand_characters(self):
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(one_page_pdf(50_000))
        try:
            page = pdf[0]
            tp = page.get_textpage()
            whole = tp.get_text_range()
            width, height = page.get_size()
            with pytest.raises(P.PdfReadError, match="took too long"):
                P._build_lines(tp, whole, width, height, deadline=time.monotonic() - 1)
            lines = P._build_lines(tp, whole, width, height, deadline=time.monotonic() + 60)
            assert lines
            tp.close()
            page.close()
        finally:
            pdf.close()

    def test_a_page_that_takes_longer_than_the_budget_stops_the_read(self, monkeypatch):
        """The budget is enforced in the middle of a page, not after it: a page whose layout never
        ends must not hold the read for ever. The stand-in stops only when the deadline passes."""
        def endless(tp, whole, w, h, deadline=None):
            end = time.monotonic() + 10
            while time.monotonic() < end:
                if deadline is not None and time.monotonic() > deadline:
                    raise P.PdfReadError(P._TOO_SLOW)
            return []

        monkeypatch.setattr(P, "_build_lines", endless)
        started = time.monotonic()
        with pytest.raises(P.PdfReadError, match="took too long"):
            P.read_pdf(load("a_lawreview_chromium"), time_budget=0.3)
        assert time.monotonic() - started < 5


def test_the_time_budget_starts_when_the_reader_lock_is_held_not_when_the_upload_arrives(monkeypatch):
    """A fine file queued behind another read used to fail with 'took too long': its 25 seconds
    began before it had the lock. Here the lock is held for 0.8 s and the budget is 0.5 s."""
    import threading

    data = text_pdf(3)
    P._PDFIUM_LOCK.acquire()
    outcome = {}

    def reader():
        try:
            outcome["result"] = P.read_pdf(data, time_budget=0.5)
        except Exception as exc:  # pragma: no cover - only on failure
            outcome["error"] = exc

    thread = threading.Thread(target=reader)
    thread.start()
    time.sleep(0.8)
    P._PDFIUM_LOCK.release()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert outcome["result"].pages == 3


def test_the_readers_time_budget_is_answered_like_any_other_limit_the_document_exceeds(monkeypatch):
    """Run out of time inside the reader and run out of time in the child are the same answer for the
    person: 413, too complex to read within this server's limits, with the time stated."""
    monkeypatch.setattr(P, "PDF_TIME_BUDGET_S", 0.0)
    with pytest.raises(DocumentTooComplexError, match=r"too complex to read within this server's limits \(reading it took longer than the 0 seconds"):
        DocumentParser().parse_document(text_pdf(5), "a.pdf")
