"""What the PDF reader makes of a page's layout: where footnotes start and end, which lines are
running heads, a page range broken at a line end, a page count that lies, a locked file.

Every document is written here, a few text runs at chosen positions and sizes, so a test shows the
layout it is about. The shapes come from one real 58-page paper exported from Word (footnotes with
an indented first line, footnotes in the body's own size, a four-line letterhead on every page)
and from reviewers' documents (pages that are mostly footnotes, two columns, alternating heads).
"""

import struct
import zlib

import pytest

import app.services.pdf_text as P
from app.services.pdf_text import strip_running_lines

EN_DASH = chr(0x2013)


@pytest.fixture(autouse=True)
def the_reader_lock_is_never_left_held():
    yield
    if P._PDFIUM_LOCK.locked():
        P._PDFIUM_LOCK.release()
        pytest.fail("this test left the PDF reader's lock held")


# --- a PDF writer with positions and sizes -----------------------------------------------------


def _escape(text: str) -> bytes:
    # StandardEncoding has the en dash at 0xB1
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text.replace(EN_DASH, "\xb1").encode("latin-1")


def layout_pdf(pages: list[list[tuple[float, float, float, str]]]) -> bytes:
    """One page per item; a page is a list of runs (x, y, size, text), drawn in that order."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(len(pages))) + b"] /Count %d >>" % len(pages),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, runs in enumerate(pages):
        stream = b"BT " + b" ".join(b"/F1 %g Tf 1 0 0 1 %g %g Tm (%s) Tj" % (size, x, y, _escape(text)) for x, y, size, text in runs) + b" ET"
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 3 0 R >> >> >>" % (5 + 2 * i))
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


BODY = "The court held that the statute does not reach the conduct at issue in this case."
NOTE = "Smith v. Jones, 5 U.S. 137, 140 (1803); see also Doe v. Roe, 456 F.2d 789, 791 (2d Cir. 1972)."


def block(x: float, top: float, size: float, lines: list[str], leading: float | None = None) -> list[tuple[float, float, float, str]]:
    leading = leading or size * 1.25
    return [(x, top - i * leading, size, line) for i, line in enumerate(lines)]


def note(x: float, top: float, number: int, text: str = NOTE, *, size: float = 9, more: int = 1, indent: float = 0, raised: bool = False):
    """A footnote: its number and first line, then `more` lines of the same text at the margin.
    `raised` draws the number as a superscript, as Word and LibreOffice do."""
    runs = []
    if raised:
        runs.append((x + indent, top + size * 0.35, size * 0.6, str(number)))
        runs.append((x + indent + size * 0.4 * len(str(number)) + 1, top, size, " " + text))
    else:
        runs.append((x + indent, top, size, f"{number} {text}"))
    runs += [(x, top - (k + 1) * size * 1.25, size, text) for k in range(more)]
    return runs


def text_of(pages) -> str:
    return P.read_pdf(layout_pdf(pages)).text


def marks(text: str) -> list[str]:
    import re

    return re.findall(r"(?m)^\[\^(\d+)\]", text)


# --- footnotes: where they start ---------------------------------------------------------------


class TestWhereFootnotesStart:
    def test_on_a_page_that_is_mostly_footnotes(self):
        """Four lines of body and twelve of footnotes: the middle character of the page is in a
        footnote, so the median line height was the footnotes' own and none of them was "small"."""
        page = block(72, 720, 12, [BODY] * 4)
        for k in range(4):
            page += note(72, 600 - k * 40, k + 1, more=2)
        assert marks(text_of([page])) == ["1", "2", "3", "4"]

    def test_when_the_first_line_of_a_footnote_is_indented(self):
        page = block(72, 720, 12, [BODY] * 12)
        page += note(72, 300, 1, indent=18) + note(72, 260, 2, indent=18) + note(72, 220, 3, indent=18)
        assert marks(text_of([page])) == ["1", "2", "3"]

    def test_in_both_columns_of_a_two_column_page(self):
        short, small = BODY[:38], NOTE[:38]
        page = block(72, 720, 11, [short] * 20) + note(72, 300, 1, small, more=2) + note(72, 250, 2, small, more=2)
        page += block(320, 720, 11, [short] * 20) + note(320, 300, 3, small, more=2) + note(320, 250, 4, small, more=2)
        assert marks(text_of([page])) == ["1", "2", "3", "4"]

    def test_footnotes_set_in_the_size_of_the_body_are_known_by_their_superscript_number(self):
        first = block(72, 720, 11, [BODY] * 14) + note(72, 300, 1, raised=True) + note(72, 260, 2, raised=True)
        second = block(72, 720, 11, [BODY] * 20)
        second += note(72, 180, 3, size=11, more=0, raised=True) + note(72, 166, 4, size=11, more=0, raised=True)
        text = text_of([first, second])
        assert marks(text) == ["1", "2", "3", "4"]
        assert "[^3] Smith v. Jones" in text and "[^4] Smith v. Jones" in text

    def test_a_line_of_body_size_that_only_starts_with_the_next_number_is_not_a_footnote(self):
        first = block(72, 720, 11, [BODY] * 14) + note(72, 300, 1, raised=True) + note(72, 260, 2, raised=True)
        second = block(72, 720, 11, [BODY] * 20) + [(72, 180, 11, "3 U.S.C. sections are cited in the next line of this paragraph.")]
        assert marks(text_of([first, second])) == ["1", "2"]

    def test_on_a_page_that_holds_nothing_but_footnotes(self):
        """A long run of notes spills onto a page of its own: nothing there is body-sized, and the
        notes start at the top of the page. What says they are footnotes is the pages before."""
        first = block(72, 720, 12, [BODY] * 30) + note(72, 200, 1) + note(72, 160, 2)
        spill = []
        for k in range(8):
            spill += note(72, 720 - k * 40, k + 3, more=2)
        assert marks(text_of([first, spill])) == [str(n) for n in range(1, 11)]

    def test_small_print_with_numbered_lines_is_not_footnotes_when_the_count_does_not_go_on(self):
        """A page of small type (an appendix, a table) after the body: only the number that is
        expected next can start a footnote there."""
        first = block(72, 720, 12, [BODY] * 30) + note(72, 200, 1) + note(72, 160, 2)
        appendix = []
        for k in range(8):
            appendix += [(72, 720 - k * 40, 9, f"{k + 1} Item of the schedule, in small type, with enough words to be a line.")]
            appendix += [(72, 708 - k * 40, 9, "and a second line of the same item, which carries on for a while longer.")]
        assert marks(text_of([first, appendix])) == ["1", "2"]

    def test_the_count_goes_past_999(self, monkeypatch):
        pages = []
        for start in (998, 1000):
            pages.append(block(72, 720, 12, [BODY] * 20) + note(72, 300, start) + note(72, 260, start + 1))
        raws = []
        state = {"next": 998}
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(layout_pdf(pages))
        for i in range(2):
            page = pdf[i]
            tp = page.get_textpage()
            raws.append(P._page_text(page, tp, state))
        assert marks("\n".join(raws)) == ["998", "999", "1000", "1001"]

    def test_a_year_at_the_start_of_a_line_does_not_start_a_count(self):
        page = block(72, 720, 12, [BODY] * 20)
        page += [(72, 300, 9, "2019 Annual Report of the Office, at 14, on which the court relied."), (72, 288, 9, "2020 Annual Report of the Office, at 9, which says the same thing again.")]
        assert marks(text_of([page])) == []


# --- footnotes: where they end -----------------------------------------------------------------


class TestWhereFootnotesEnd:
    """The extractor gives a citation the number of the last "[^N]" before it, so it has to be told
    where a footnote stops. The reader's promise: a footnote ends at the next "[^N]" or at the next
    blank line, whichever comes first, and nothing else puts a blank line inside a page."""

    def test_a_blank_line_closes_the_footnotes_when_the_next_column_follows(self):
        short, small = BODY[:38], NOTE[:38]
        page = block(72, 720, 11, [short] * 20) + note(72, 300, 1, small, more=2) + note(72, 250, 2, small, more=2)
        page += block(320, 720, 11, ["Second column: " + short[:22]] * 20)
        text = text_of([page])
        first_note, _, rest = text.partition("[^1]")
        notes, blank, after = rest.partition("\n\n")
        assert "[^2]" in notes and blank and after.startswith("Second column:")
        assert "\n\n" not in first_note and "\n\n" not in after

    def test_the_blank_line_between_pages_closes_the_last_footnote_of_a_page(self):
        first = block(72, 720, 12, [BODY] * 12) + note(72, 300, 1) + note(72, 260, 2)
        second = block(72, 720, 12, ["Next page. " + BODY[:60]] * 12)
        text = text_of([first, second])
        assert text.count("\n\n") == 1
        assert text.split("\n\n")[0].rstrip().endswith(NOTE) and text.split("\n\n")[1].startswith("Next page.")

    def test_consecutive_footnotes_have_no_blank_line_between_them(self):
        page = block(72, 720, 12, [BODY] * 12) + note(72, 300, 1) + note(72, 260, 2) + note(72, 220, 3)
        assert "\n\n" not in text_of([page])


# --- running heads -----------------------------------------------------------------------------


NAMES = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa".split()


def numbered(n: int, top: list[str] | None = None, bottom: list[str] | None = None) -> list[str]:
    """`n` pages of body lines that no two pages share (and with no digits in them, which would
    make them look like a page counter), with the same lines above and below each."""
    return ["\n".join((top or []) + [f"Body line {NAMES[k]} of page {NAMES[i]}, which no other page has." for k in range(8)] + (bottom or [])) for i in range(n)]


class TestRunningLines:
    LETTERHEAD = ["August 24, 2026 | Firearms Research Center", "www.example.org | office@example.org", "1000 East University Avenue | Laramie", "Working Paper"]

    def test_the_fourth_line_of_a_letterhead_goes_with_the_first_three(self):
        out = strip_running_lines(numbered(8, top=self.LETTERHEAD))
        assert not any(line in page for page in out for line in self.LETTERHEAD)
        assert all(page.startswith("Body line alpha") and page.count("\n") == 7 for page in out)

    def test_what_comes_to_the_edge_next_stays_unless_it_is_on_nine_pages_in_ten(self):
        """Under a three-line head, six pages of ten open with the same sentence. It is body text."""
        head = self.LETTERHEAD[:3]
        opening = "The same opening sentence, which six of the ten pages share."
        pages = numbered(10, top=head)
        pages = ["\n".join(head + [opening]) + p[len("\n".join(head)):] if i < 6 else p for i, p in enumerate(pages)]
        out = strip_running_lines(pages)
        assert sum(page.startswith(opening) for page in out) == 6
        assert not any(line in page for page in out for line in head)

    def test_a_document_of_one_paragraph_repeated_loses_no_more_than_it_did(self):
        sentences = [f"Sentence number {k} of the one paragraph this document repeats on every page." for k in range(5)]
        pages = ["\n".join(sentences[(i + k) % 5] for k in range(14)) for i in range(10)]
        assert strip_running_lines(pages) == P._strip_running_lines_once(pages)[0]

    def test_heads_that_alternate_between_left_and_right_pages_are_removed(self):
        """A law review: no head on the first page, then the author on one side and the title on
        the other. Neither is on half of all the pages."""
        pages = numbered(9)
        for i in range(1, 9):
            pages[i] = ("JANE Q. SCHOLAR" if i % 2 else "THE LIMITS OF DEFERENCE") + "\n" + pages[i]
        out = strip_running_lines(pages)
        assert not any("SCHOLAR" in page or "LIMITS OF DEFERENCE" in page for page in out)
        assert all(page.startswith("Body line alpha") for page in out)

    def test_a_line_on_a_few_pages_of_both_kinds_is_not_an_alternating_head(self):
        pages = numbered(12)
        for i in (1, 4, 6, 9):
            pages[i] = "A heading that four sections share" + "\n" + pages[i]
        assert strip_running_lines(pages) == pages

    def test_a_line_on_too_few_pages_of_one_kind_stays(self):
        pages = numbered(14)
        for i in (2, 6):
            pages[i] = "A heading that two sections share" + "\n" + pages[i]
        assert strip_running_lines(pages) == pages

    def test_a_citation_that_repeats_on_every_other_page_is_still_a_citation(self):
        pages = numbered(10)
        for i in range(0, 10, 2):
            pages[i] = pages[i] + "\nSee Smith v. Jones, 5 U.S. 137 (1803)."
        assert strip_running_lines(pages, veto=P._citation_veto) == pages

    def test_through_the_reader_a_four_line_letterhead_is_gone_and_the_body_is_whole(self):
        pages = []
        for i in range(6):
            head = [(300, 60, 9, self.LETTERHEAD[1]), (300, 48, 9, self.LETTERHEAD[2]), (300, 36, 9, "Working Paper"), (400, 760, 9, f"August 24, 2026 | {i + 1}")]
            pages.append(head + block(72, 720, 12, [f"Page {NAMES[i]} line {NAMES[k]}: {BODY[:50]}" for k in range(10)]))
        text = text_of(pages)
        assert "Working Paper" not in text and "example.org" not in text and "August 24" not in text
        assert all(f"Page {NAMES[i]} line {NAMES[k]}:" in text for i in range(6) for k in range(10))


# --- a page range broken after its en dash ------------------------------------------------------


def test_a_page_range_broken_after_an_en_dash_is_read_whole_from_a_pdf():
    page = block(72, 720, 12, [f"See Roe v. Wade, 410 U.S. 113, 152{EN_DASH}", "53 (1973), and the cases it cites."])
    text = text_of([page])
    assert f"410 U.S. 113, 152{EN_DASH}53 (1973), and the cases it cites." in text


# --- a page count that is too small, in a file that keeps its objects in object streams ----------


def object_stream_pdf(pages: int, declared: int) -> bytes:
    """A PDF 1.5 file as modern producers write it: catalog, page tree and page dictionaries inside
    one compressed object stream, located by a cross-reference stream. `declared` is its /Count."""
    page_numbers = list(range(4, 4 + pages))
    content_numbers = list(range(4 + pages, 4 + 2 * pages))
    stream_number, xref_number = 4 + 2 * pages, 5 + 2 * pages
    packed = {
        1: b"<</Type/Catalog/Pages 2 0 R>>",
        2: b"<</Type/Pages/Kids[" + b" ".join(b"%d 0 R" % n for n in page_numbers) + b"]/Count %d>>" % declared,
        3: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    }
    for page, content in zip(page_numbers, content_numbers, strict=True):
        packed[page] = b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents %d 0 R/Resources<</Font<</F1 3 0 R>>>>>>" % content
    plain = {}
    for i, content in enumerate(content_numbers):
        drawn = b"BT /F1 11 Tf 72 720 Td (The %s page of an ordinary document, with one line of text on it.) Tj ET" % f"{NAMES[i % 16]}-{NAMES[i // 16]}".encode()
        plain[content] = b"<</Length %d>>\nstream\n" % len(drawn) + drawn + b"\nendstream"
    index, body = b"", b""
    for number in sorted(packed):
        index += b"%d %d " % (number, len(body))
        body += packed[number] + b" "
    data = zlib.compress(index + body)
    plain[stream_number] = b"<</Type/ObjStm/N %d/First %d/Filter/FlateDecode/Length %d>>\nstream\n" % (len(packed), len(index), len(data)) + data + b"\nendstream"
    out = bytearray(b"%PDF-1.5\n")
    offsets = {}
    for number in sorted(plain):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + plain[number] + b"\nendobj\n"
    xref_at = len(out)
    position = {number: i for i, number in enumerate(sorted(packed))}
    rows = b""
    for number in range(xref_number + 1):
        if number == 0:
            rows += struct.pack(">BIH", 0, 0, 65535)
        elif number in packed:
            rows += struct.pack(">BIH", 2, stream_number, position[number])
        else:
            rows += struct.pack(">BIH", 1, xref_at if number == xref_number else offsets[number], 0)
    rows = zlib.compress(rows)
    out += b"%d 0 obj\n<</Type/XRef/Size %d/W[1 4 2]/Root 1 0 R/Filter/FlateDecode/Length %d>>\nstream\n" % (xref_number, xref_number + 1, len(rows))
    out += rows + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


class TestPageCountInsideObjectStreams:
    """The quick check for a /Count that is too small counts page objects in the file's bytes. In a
    file that keeps them in a compressed object stream there are none to count, so twelve pages
    that said five were read as five, with no warning."""

    def test_the_file_is_what_it_is_meant_to_be(self):
        content = object_stream_pdf(12, 12)
        assert b"/ObjStm" in content and P._count_page_objects(content, 0) == 0
        result = P.read_pdf(content)
        assert result.pages == 12 and result.warnings == [] and result.engine == "pdfium"

    def test_too_small_a_count_reads_the_rest_and_says_so(self):
        result = P.read_pdf(object_stream_pdf(12, 5), max_pages=40)
        assert result.pages == 12 and result.text.count("of an ordinary document") == 12
        assert result.warnings == ["This PDF says it has 5 pages but the file holds 12. All of them were read, the extra ones with a slower reader."]

    def test_too_small_a_count_cannot_get_a_long_file_past_the_page_limit(self):
        with pytest.raises(P.PdfTooLongError, match="more than 40 pages"):
            P.read_pdf(object_stream_pdf(60, 5), max_pages=40)


# --- a file that is locked against copying, not against reading ---------------------------------


class TestEncryptionIsMentionedOnlyWhenSomethingIsMissing:
    """The reader looks for "/Encrypt" in the file's bytes. These files carry the word in a comment
    at the end, which is all the check sees, so the two cases can be written without a cipher."""

    FULL = block(72, 720, 12, [BODY] * 6)

    def test_every_page_read_then_nothing_is_said(self):
        result = P.read_pdf(layout_pdf([self.FULL, self.FULL]) + b"\n% /Encrypt\n")
        assert result.warnings == [] and result.text.count(BODY) == 12

    def test_a_page_with_nothing_on_it_then_it_is_said(self):
        result = P.read_pdf(layout_pdf([self.FULL, [], self.FULL]) + b"\n% /Encrypt\n")
        assert "This PDF is encrypted, so some text may be missing." in result.warnings
        assert "This PDF is encrypted, so some text may be missing." not in P.read_pdf(layout_pdf([self.FULL, [], self.FULL])).warnings
