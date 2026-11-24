"""Hostile and extreme documents, generated when a test runs, so that nothing large or dangerous
is checked in. Each one is tiny on the wire. They are the shapes that took the server down or
froze it, found by four independent reviewers of the long-document work:

    form_recursion_pdf()       862 bytes: a form XObject whose content draws itself twice
    many_ops_pdf()             20 KB: ten million "q" operators
    flate_bomb_pdf()           about 50 KB: 50 MB of spaces deflated into one content stream
    one_page_pdf()             a few KB: one million characters on a single page
    run_pdf("letters")         664 bytes: an unbroken run of 64,000 letters (a quadratic regex)
    cid_scattered_pdf()        a page of scattered words whose text contains the literal "(cid:"
    missing_root_bomb_pdf()    a flate bomb with no /Root, so pdfium refuses it and pdfminer reads it
    unclosed_tag_docx()        a Word part of unclosed <w:b> tags nested millions deep
    empty_paragraph_docx()     a Word part of millions of <w:p/>
    nested_tables_docx(depth)  tables inside table cells
    many_entries_zip()         a zip with thousands of entries

Nothing here runs the reader. Run them through the real isolation path (see test_hostile_documents).
"""
import io
import zipfile
import zlib

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# --- a raw PDF writer --------------------------------------------------------------------------


def pdf_bytes(objects: dict[int, bytes], *, root: int | None = 1, count_in_trailer: bool = True) -> bytes:
    """A PDF with a correct cross-reference table. `root=None` leaves /Root out of the trailer."""
    out = bytearray(b"%PDF-1.7\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += str(number).encode() + b" 0 obj\n" + objects[number] + b"\nendobj\n"
    size = max(objects) + 1
    xref = len(out)
    out += b"xref\n0 " + str(size).encode() + b"\n0000000000 65535 f \n"
    for number in range(1, size):
        if number in offsets:
            out += b"%010d 00000 n \n" % offsets[number]
        else:
            out += b"0000000000 65535 f \n"
    trailer = b"<< /Size " + str(size).encode()
    if root is not None:
        trailer += b" /Root " + str(root).encode() + b" 0 R"
    out += b"trailer\n" + trailer + b" >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
    return bytes(out)


def flate_stream(extra: bytes, data: bytes) -> bytes:
    z = zlib.compress(data, 9)
    return b"<< " + extra + b" /Filter /FlateDecode /Length " + str(len(z)).encode() + b" >>\nstream\n" + z + b"\nendstream"


def deflate_repeated(unit: bytes, total: int) -> bytes:
    """`total` bytes made of `unit` repeated, deflated without ever holding them in memory."""
    compressor = zlib.compressobj(9)
    block = (unit * ((1 << 20) // len(unit) + 1))[: 1 << 20]
    pieces, done = [], 0
    while done < total:
        take = min(len(block), total - done)
        pieces.append(compressor.compress(block[:take]))
        done += take
    pieces.append(compressor.flush())
    return b"".join(pieces)


def _page_objects(content_stream: bytes, resources: bytes = b"<< /Font << /F1 5 0 R >> >>", extra: dict | None = None) -> dict[int, bytes]:
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources " + resources + b" /Contents 4 0 R >>",
        4: content_stream,
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    objects.update(extra or {})
    return objects


def text_content(strings: list[str], *, scale: float = 0.02, size: int = 6) -> bytes:
    """One TJ array of the given strings, squeezed to a hundredth of their width so that they all
    stay on the page. Deflated, so a million characters cost a few kilobytes."""
    segments = " ".join("(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")" for s in strings)
    return f"BT /F1 {size} Tf {scale} Tz 10 780 Td [{segments}] TJ ET".encode("latin-1")


# --- PDFs --------------------------------------------------------------------------------------


def form_recursion_pdf() -> bytes:
    """862 bytes. pdfium follows the form into itself twice at every level and allocates until it
    is stopped; with an address-space limit it aborts (SIGABRT) instead of raising."""
    objects = _page_objects(
        flate_stream(b"", b"BT /F1 12 Tf 72 700 Td (A) Tj ET /X Do"),
        resources=b"<< /Font << /F1 5 0 R >> /XObject << /X 7 0 R >> >>",
        extra={7: flate_stream(
            b"/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << /XObject << /X 7 0 R >> >>",
            b"/X Do /X Do")},
    )
    return pdf_bytes(objects)


def many_ops_pdf(n: int = 10_000_000, op: bytes = b"q\n") -> bytes:
    """About 160 bytes of memory for each operator in pdfium: ten million is 1.6 GB."""
    return pdf_bytes(_page_objects(_stream_of(deflate_repeated(op, n * len(op)))))


def _stream_of(deflated: bytes) -> bytes:
    return b"<< /Filter /FlateDecode /Length " + str(len(deflated)).encode() + b" >>\nstream\n" + deflated + b"\nendstream"


def flate_bomb_pdf(mb: int = 50) -> bytes:
    """`mb` MiB of spaces in one deflated content stream (about a thousand to one). pdfium has no
    cap on what a stream expands to."""
    return pdf_bytes(_page_objects(_stream_of(deflate_repeated(b" ", mb * 1024 * 1024))))


def one_page_pdf(chars: int = 1_000_000, unit: str = "word ") -> bytes:
    """A single page holding `chars` characters of ordinary-looking text."""
    segment = (unit * (32_000 // len(unit) + 1))[:32_000]
    full, rest = divmod(chars, 32_000)
    strings = [segment] * full + ([segment[:rest]] if rest else [])
    return pdf_bytes(_page_objects(_stream_of(zlib.compress(text_content(strings), 9))))


def run_pdf(kind: str = "letters", total: int = 64_000) -> bytes:
    """One unbroken run (two strings of total/2 characters) on a page. 664 bytes for 64,000 letters."""
    unit = {
        "letters": "a",
        "capitals": "A",
        "mixed": "aA",
        "digits": "7",
        "url": "http://aaaaaaaa",
        "dots": ".",
        "hyphens": "-",
        "spaces": " ",
        "hyphen_newline": "a-\n",
    }[kind]
    half = (unit * (total // 2 // len(unit) + 1))[: total // 2]
    return pdf_bytes(_page_objects(_stream_of(zlib.compress(text_content([half, half]), 9))))


def cid_scattered_pdf(words: int = 2000) -> bytes:
    """Many words placed at scattered positions on one page, among them the literal text
    "(cid:12)". The page is not garbled, but it contains what a naive check takes for evidence of
    it, and pdfminer's layout analysis of this many separate words takes minutes."""
    import random

    rng = random.Random(1)
    parts = ["BT /F1 6 Tf", "20 780 Td ((cid:12) (cid:13) padding padding padding padding padding padding padding) Tj"]
    for i in range(words):
        parts.append(f"1 0 0 1 {rng.uniform(10, 580):.1f} {rng.uniform(20, 760):.1f} Tm (w{i}x) Tj")
    parts.append("ET")
    return pdf_bytes(_page_objects(_stream_of(zlib.compress("\n".join(parts).encode(), 9))))


def missing_root_bomb_pdf(mb: int = 200) -> bytes:
    """A flate bomb whose trailer has no /Root: pdfium refuses the file, so the whole-file
    fallback (pdfminer) is the reader that meets the bomb."""
    return pdf_bytes(_page_objects(_stream_of(deflate_repeated(b" ", mb * 1024 * 1024))), root=None)


_WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike",
          "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu"]


def pages_pdf(real_pages: int, declared: int) -> bytes:
    """`real_pages` pages, each with a line of its own ("A page of ordinary text: ..."), whose
    /Count says `declared`."""
    kids = " ".join(f"{6 + 2 * i} 0 R" for i in range(real_pages))
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {declared} >>".encode(),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i in range(real_pages):
        w = _WORDS
        line = f"A page of ordinary text: the {w[i % 26]} panel held that the {w[(i * 3 + 1) % 26]} rule governs the {w[(i * 7 + 2) % 26]} claim in count {i}."
        objects[6 + 2 * i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                              f"/Resources << /Font << /F1 5 0 R >> >> /Contents {7 + 2 * i} 0 R >>").encode()
        objects[7 + 2 * i] = flate_stream(b"", f"BT /F1 12 Tf 72 700 Td ({line}) Tj ET".encode())
    return pdf_bytes(objects)


# --- Word --------------------------------------------------------------------------------------

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)
_HEAD = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}"><w:body>'.encode()
_TAIL = b"</w:body></w:document>"


def _zip_with_streamed_part(name: str, pieces) -> bytes:
    """A docx whose `name` part is written piece by piece, so a 30 MB part never sits in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        with archive.open(name, "w", force_zip64=True) as part:
            for piece in pieces:
                part.write(piece)
    return buffer.getvalue()


def _repeat(unit: bytes, times: int, block: int = 1 << 20):
    chunk = unit * max(1, block // len(unit))
    full, rest = divmod(times, max(1, block // len(unit)))
    for _ in range(full):
        yield chunk
    if rest:
        yield unit * rest


def unclosed_tag_docx(mb: int = 30) -> bytes:
    """`mb` MiB of an opening <w:b> that is never closed: a tree that is millions of levels deep
    if it is built, 44 KB on the wire. (Measured by a reviewer: 1.8 GB of memory.)"""
    unit = b"<w:b>"
    return _zip_with_streamed_part("word/document.xml", [_HEAD, *_repeat(unit, mb * 1024 * 1024 // len(unit))])


def empty_paragraph_docx(mb: int = 39) -> bytes:
    """`mb` MiB of <w:p/>: millions of elements and no text."""
    unit = b"<w:p/>"
    return _zip_with_streamed_part("word/document.xml", [_HEAD, *_repeat(unit, mb * 1024 * 1024 // len(unit)), _TAIL])


def nested_tables_docx(depth: int, text: str = "Brown v. Board of Education, 347 U.S. 483 (1954).") -> bytes:
    """A paragraph inside `depth` tables, each inside the previous one's cell."""
    body = (b"<w:tbl><w:tr><w:tc>" * depth
            + f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>".encode()
            + b"</w:tc></w:tr></w:tbl>" * depth)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("word/document.xml", _HEAD + body + _TAIL)
    return buffer.getvalue()


def many_entries_zip(entries: int = 3000) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", _HEAD + b"<w:p><w:r><w:t>Hello.</w:t></w:r></w:p>" + _TAIL)
        for i in range(entries):
            archive.writestr(f"word/media/p{i}.xml", b"<x/>")
    return buffer.getvalue()


def big_word_docx(chars: int, per_paragraph: int = 400) -> bytes:
    """A realistic long document: `chars` characters of ordinary paragraphs with citations,
    each paragraph a few runs the way Word writes them (so about 250,000 words at 1.5M)."""
    sentence = "The court in Brown v. Board of Education, 347 U.S. 483 (1954), held that segregation is unconstitutional. "
    paragraph = (sentence * (per_paragraph // len(sentence) + 1))[:per_paragraph]
    third = len(paragraph) // 3
    runs = "".join(
        f'<w:r><w:rPr><w:rFonts w:ascii="Times New Roman"/><w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">{piece}</w:t></w:r>'
        for piece in (paragraph[:third], paragraph[third: 2 * third], paragraph[2 * third:])
    )
    unit = f'<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>{runs}</w:p>'.encode()
    count = max(1, chars // per_paragraph)
    return _zip_with_streamed_part("word/document.xml", [_HEAD, *_repeat(unit, count), _TAIL])


# --- running code with a hard stop ---------------------------------------------------------------


def run_python(code: str, timeout: float = 90.0):
    """Run `code` in a fresh interpreter (cwd: the backend) and return the finished process.

    An in-process time assertion cannot catch code that holds the interpreter lock (a regular
    expression stuck in backtracking never lets the assertion run), so each hostile case that could
    do that runs here, where a regression becomes a failed test after `timeout` seconds instead of
    a run that never ends."""
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    try:
        return subprocess.run(
            [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"did not finish within {timeout:.0f} s (the code under test was probably stuck in a regular expression)")
