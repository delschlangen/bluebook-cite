"""The Word reader streams each XML part (no tree), counts text once, and stops at its limits.

The tree-building reader cost about 60 bytes of memory per byte of XML (a 44 KB file of unclosed
<w:b> tags took 1.8 GB), visited a table's rows once for every level of nesting (so a 3 KB file of
nested tables became a million characters), and applied the text limit only after the whole part had
been walked. These tests pin what replaced it.
"""

import io
import zipfile

import pytest

import app.services.parser as parser_module
from app.services.parser import (
    DocumentParser,
    DocumentTooComplexError,
    DocumentTooLongError,
    UnsupportedDocumentError,
)
from tests.docfactory import W
from tests.hostile import (
    big_word_docx,
    empty_paragraph_docx,
    nested_tables_docx,
    run_python,
    unclosed_tag_docx,
)

CITE = "Brown v. Board of Education, 347 U.S. 483 (1954)."


def docx_with(body_xml: str, **parts: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body_xml}</w:body></w:document>',
        )
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return buffer.getvalue()


def read(data: bytes, **kw):
    return DocumentParser(**kw).parse_document(data, "a.docx")


def para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


# --- text is counted once --------------------------------------------------------------------


@pytest.mark.parametrize("depth", [0, 1, 2, 3, 5, 10])
def test_a_table_nested_to_any_depth_yields_its_text_once(depth):
    assert read(nested_tables_docx(depth)).text.count("Brown v. Board") == 1


def test_a_nested_tables_text_belongs_to_the_cell_that_holds_it():
    outer = (
        "<w:tbl><w:tr>"
        f"<w:tc>{para('Left cell.')}<w:tbl><w:tr><w:tc>{para('Inside.')}</w:tc><w:tc>{para('Also inside.')}</w:tc></w:tr></w:tbl></w:tc>"
        f"<w:tc>{para('Right cell.')}</w:tc>"
        "</w:tr></w:tbl>"
    )
    text = read(docx_with(outer)).text
    assert text == "Left cell. Inside. Also inside. | Right cell."


def test_a_nested_table_in_a_later_cell_does_not_disturb_the_cells_before_it():
    outer = (
        "<w:tbl><w:tr>"
        f"<w:tc>{para('First.')}</w:tc>"
        f"<w:tc>{para('Second.')}<w:tbl><w:tr><w:tc>{para('Inside.')}</w:tc></w:tr></w:tbl></w:tc>"
        f"<w:tc>{para('Third.')}</w:tc>"
        "</w:tr></w:tbl>"
    )
    assert read(docx_with(outer)).text == "First. | Second. Inside. | Third."


def test_ordinary_tables_read_as_rows_of_cells_as_before():
    body = (
        para("Before.")
        + "<w:tbl>"
        + f"<w:tr><w:tc>{para('A1')}</w:tc><w:tc>{para('B1')}{para('B1 second')}</w:tc></w:tr>"
        + f"<w:tr><w:tc>{para('A2')}</w:tc><w:tc><w:p/></w:tc></w:tr>"
        + "</w:tbl>"
        + para("After.")
    )
    assert read(docx_with(body)).text == "Before.\n\nA1 | B1 B1 second\n\nA2\n\nAfter."


def test_tabs_breaks_and_no_break_hyphens_and_tracked_changes():
    body = (
        "<w:p><w:r><w:t>one</w:t><w:tab/><w:t>two</w:t><w:br/><w:t>three</w:t><w:noBreakHyphen/><w:t>four</w:t></w:r>"
        "<w:ins><w:r><w:t> inserted</w:t></w:r></w:ins>"
        "<w:del><w:r><w:delText> deleted</w:delText></w:r></w:del></w:p>"
    )
    assert read(docx_with(body)).text == "one two three-four inserted"


def test_only_body_level_paragraphs_and_tables_are_read_as_before():
    """Content inside a content control (w:sdt) was never read: pinned so a change is deliberate."""
    body = para("Kept.") + f"<w:sdt><w:sdtContent>{para('Inside a content control.')}</w:sdtContent></w:sdt>"
    assert read(docx_with(body)).text == "Kept."


def test_footnotes_and_endnotes_keep_their_numbers_and_skip_separators():
    notes = (
        f'<w:footnotes {W}>'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        f'<w:footnote w:id="5"><w:p><w:r><w:t>See {CITE}</w:t></w:r></w:p></w:footnote></w:footnotes>'
    )
    body = '<w:p><w:r><w:t>Text.</w:t></w:r><w:r><w:footnoteReference w:id="5"/></w:r></w:p>'
    parsed = read(docx_with(body, **{"word/footnotes.xml": notes}))
    assert parsed.footnote_count == 1
    assert parsed.text == f"Text.\n\n[^1] See {CITE}"


# --- bounds -------------------------------------------------------------------------------------


def test_the_text_limit_stops_the_read_part_way_not_after_the_whole_part():
    """A million paragraphs and a limit of 1,000 characters: the walk must end near the start."""
    budget = parser_module._TextBudget(1000)
    part = parser_module._WordPart(budget)
    unit = "<w:p><w:r><w:t>" + "x" * 100 + "</w:t></w:r></w:p>"
    xml = f'<?xml version="1.0"?><w:document {W}><w:body>{unit * 100_000}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive, pytest.raises(DocumentTooLongError) as caught:
        DocumentParser._scan(archive, "word/document.xml", part)
    assert "more than 1,000 characters" in str(caught.value)
    assert part.elements < 20_000, f"{part.elements} elements were read before the limit stopped it"


def test_a_document_just_over_the_limit_is_refused_with_its_true_size():
    """Over the limit by less than the reader's slack: read to the end, refused by the exact check."""
    import asyncio

    from app.services.sandbox import parse_isolated

    data = docx_with(para("x" * 600) + para("y" * 600))
    with pytest.raises(DocumentTooLongError) as caught:
        asyncio.run(parse_isolated(data, "a.docx", max_text_chars=1000))
    assert "1,000 characters" in str(caught.value) and "1,202 characters" in str(caught.value)


def test_the_element_cap_refuses_a_part_of_empty_paragraphs(monkeypatch):
    monkeypatch.setattr(parser_module, "DOCX_MAX_ELEMENTS", 100)
    with pytest.raises(DocumentTooComplexError, match=r"too complex to read within this server's limits \(it has more than 100 elements\)"):
        read(docx_with("<w:p/>" * 1000))
    read(docx_with("<w:p/>" * 90))                      # under the cap: fine


def test_the_depth_cap_refuses_deep_nesting(monkeypatch):
    monkeypatch.setattr(parser_module, "DOCX_MAX_DEPTH", 10)
    with pytest.raises(DocumentTooComplexError, match=r"nested more than 10 levels deep"):
        read(docx_with("<w:b>" * 50 + para("x") + "</w:b>" * 50))


def test_the_defaults_leave_room_for_a_real_documents_nesting_and_size():
    assert parser_module.DOCX_MAX_DEPTH >= 100 and parser_module.DOCX_MAX_ELEMENTS >= 2_000_000
    assert read(nested_tables_docx(30)).text.count("Brown") == 1       # 30 levels of tables: 120 elements deep


def test_a_doctype_is_refused_even_in_another_encoding():
    evil = (
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">]>'
        f"<w:document {W}><w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>"
    ).encode("utf-16")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", evil)
    with pytest.raises(UnsupportedDocumentError, match="cannot be read safely"):
        read(buffer.getvalue())


def test_a_doctype_without_any_entity_is_refused_too():
    """No Word part has a DOCTYPE; the old reader refused any, and so does this one."""
    xml = f'<?xml version="1.0"?><!DOCTYPE d><w:document {W}><w:body><w:p><w:r><w:t>x</w:t></w:r></w:p></w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    with pytest.raises(UnsupportedDocumentError, match="cannot be read safely"):
        read(buffer.getvalue())


def test_a_damaged_part_has_its_message():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:body><w:p>")
    with pytest.raises(UnsupportedDocumentError, match="damaged text"):
        read(buffer.getvalue())


def test_an_archive_without_a_document_part_has_its_message():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/footnotes.xml", "<x/>")
    with pytest.raises(UnsupportedDocumentError, match="no document body"):
        DocumentParser()._parse_docx(buffer.getvalue())


# --- memory and time, with a hard stop ---------------------------------------------------------


def test_the_reader_holds_a_flat_amount_of_memory_whatever_the_part_size():
    """A part of 36 MB and 1.5 million elements (a run per word, 250,000 words). The tree-building
    reader peaked at 472 MB on it; this one stays near the interpreter's own size."""
    code = (
        "import resource, sys\n"
        "from tests.hostile import _HEAD, _TAIL, _zip_with_streamed_part\n"
        "from app.services.parser import DocumentParser\n"
        "run = (b'<w:r><w:rPr><w:rFonts w:ascii=\"Times New Roman\"/><w:sz w:val=\"24\"/></w:rPr>'\n"
        "       b'<w:t xml:space=\"preserve\">word </w:t></w:r>')\n"
        "para = b'<w:p>' + run * 120 + b'</w:p>'\n"
        "data = _zip_with_streamed_part('word/document.xml', [_HEAD] + [para] * 2000 + [_TAIL])\n"
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "out = DocumentParser().parse_document(data, 'x.docx')\n"
        "after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
        "print(len(out.text), (after - before) / 1024)\n"
    )
    done = run_python(code, timeout=120)
    assert done.returncode == 0, done.stderr
    chars, growth_mb = done.stdout.split()
    assert int(chars) > 1_000_000
    assert float(growth_mb) < 60, f"parsing grew the process by {growth_mb} MB"


def test_a_long_realistic_document_reads_under_the_default_limits():
    """About 250,000 words of paragraphs with citations, in a child with the default memory and
    time limits: the long-document case the limits were set for."""
    import asyncio

    from app.services.sandbox import parse_isolated

    parsed = asyncio.run(parse_isolated(big_word_docx(1_450_000), "long.docx"))
    assert 1_400_000 < len(parsed.text) <= 1_500_000
    assert parsed.text.count("Brown v. Board of Education") > 3000


def test_the_amplifying_documents_are_refused_in_seconds_and_with_a_413_message():
    """The reviewers' generators, through the real child: 44 KB of unclosed tags (1.8 GB as a
    tree) and 60 KB of empty paragraphs (9.6 s and 689 MB)."""
    import asyncio
    import time

    from app.services.sandbox import parse_isolated

    for make, fragment in ((unclosed_tag_docx, "nested more than 200 levels"), (empty_paragraph_docx, "more than 4,000,000 elements")):
        started = time.monotonic()
        with pytest.raises(DocumentTooComplexError) as caught:
            asyncio.run(asyncio.wait_for(parse_isolated(make(), "bomb.docx"), 30))
        assert fragment in str(caught.value)
        assert time.monotonic() - started < 15


def test_the_streaming_reader_survives_an_address_space_limit_that_killed_the_tree_reader():
    """Under a 300 MB address-space limit the 44 KB unclosed-tag file used to end in MemoryError
    (HTTP 400 'Failed to parse document: '). Now it ends in the precise refusal."""
    code = (
        "import resource\n"
        "resource.setrlimit(resource.RLIMIT_AS, (300 * 1024 * 1024,) * 2)\n"
        "from app.services.parser import DocumentParser, DocumentTooComplexError\n"
        "from tests.hostile import unclosed_tag_docx\n"
        "try:\n"
        "    DocumentParser().parse_document(unclosed_tag_docx(), 'x.docx')\n"
        "    print('parsed')\n"
        "except DocumentTooComplexError as e:\n"
        "    print('refused:', str(e)[:60])\n"
    )
    done = run_python(code, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("refused:")
