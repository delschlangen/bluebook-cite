"""What Word really writes around ordinary text, and what the reader makes of it.

Each group here is a defect independent reviewers reproduced on real-looking documents: content
controls dropped without a word, Strict Open XML files read as empty, text boxes read twice and run
into the sentence that anchors them, an image counted against the size limit although it is never
opened, and a text file refused as a damaged PDF because it mentions a PDF header. The fixtures are
built by tests/docfactory.py:word_docx with the markup Word writes for each structure.
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
    detect_format,
)
from tests.docfactory import make_pdf, word_docx

MIRANDA = "Miranda v. Arizona, 384 U.S. 436 (1966)"
ROE = "Roe v. Wade, 410 U.S. 113 (1973)"


def read(data: bytes, **kw):
    return DocumentParser(**kw).parse_document(data, "a.docx")


def text_of(body: str, **kw) -> str:
    return read(word_docx(body, **kw)).text


def p(text: str, style: str | None = None) -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def field(code: str, result: str) -> str:
    """A complex field the way Word writes one: begin, the code, separate, the result, end."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{result}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def control(content: str, properties: str = '<w:id w:val="-1620140281"/>') -> str:
    return f"<w:sdt><w:sdtPr>{properties}</w:sdtPr><w:sdtContent>{content}</w:sdtContent></w:sdt>"


# What References > Table of Authorities / Table of Contents inserts: a content control holding a
# heading and one field whose result is the entries, each a hyperlink with a tab and a page number.
def table_of_authorities(*entries: str) -> str:
    lines = ""
    for number, entry in enumerate(entries, start=1):
        inner = (
            f'<w:hyperlink w:anchor="_Toc{number}" w:history="1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/><w:noProof/></w:rPr>'
            f"<w:t>{entry}</w:t></w:r><w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:tab/></w:r>"
            + field(f"PAGEREF _Toc{number} \\h", "<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:t>4</w:t></w:r>")
            + "</w:hyperlink>"
        )
        if number == 1:
            inner = (
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + inner
            )
        lines += (
            '<w:p><w:pPr><w:pStyle w:val="TOC1"/><w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9350"/></w:tabs>'
            f"<w:rPr><w:noProof/></w:rPr></w:pPr>{inner}</w:p>"
        )
    return (
        '<w:sdt><w:sdtPr><w:id w:val="-1620140281"/><w:docPartObj><w:docPartGallery w:val="Table of Contents"/>'
        "<w:docPartUnique/></w:docPartObj></w:sdtPr><w:sdtEndPr><w:rPr><w:b/><w:bCs/><w:noProof/></w:rPr></w:sdtEndPr>"
        f'<w:sdtContent>{p("Table of Authorities", "TOCHeading")}{lines}'
        '<w:p><w:r><w:rPr><w:b/><w:bCs/><w:noProof/></w:rPr><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        "</w:sdtContent></w:sdt>"
    )


# --- content controls, custom XML and smart tags are read through (H3 = F4 = CR-5) ----------------


class TestContentControls:
    def test_a_table_of_authorities_in_a_content_control_is_read(self):
        text = text_of(table_of_authorities(MIRANDA, ROE) + p("ARGUMENT", "Heading1") + p(f"See {ROE}."))
        assert text == f"Table of Authorities\n\n{MIRANDA} 4\n\n{ROE} 4\n\nARGUMENT\n\nSee {ROE}."

    def test_a_document_whose_whole_body_is_in_a_content_control_is_read(self):
        """A template with one rich-text control around everything: it was refused as empty."""
        properties = (
            '<w:alias w:val="Brief"/><w:tag w:val="brief"/><w:id w:val="1423921532"/>'
            '<w:placeholder><w:docPart w:val="DefaultPlaceholder_-1854013440"/></w:placeholder>'
        )
        text = text_of(control(p(f"See {MIRANDA}.") + p(f"See also {ROE}."), properties))
        assert text == f"See {MIRANDA}.\n\nSee also {ROE}."

    def test_a_citation_inserted_with_insert_citation_stays_in_its_sentence(self):
        """References > Insert Citation writes an inline control around a CITATION field."""
        cite = control(
            field("CITATION Mir66 \\l 1033", "<w:r><w:rPr><w:noProof/></w:rPr><w:t>(Miranda v. Arizona, 1966)</w:t></w:r>"),
            '<w:id w:val="-573587230"/><w:citation/>',
        )
        body = f'<w:p><w:r><w:t xml:space="preserve">The warnings are required. </w:t></w:r>{cite}<w:r><w:t xml:space="preserve"> They were given.</w:t></w:r></w:p>'
        assert text_of(body) == "The warnings are required. (Miranda v. Arizona, 1966) They were given."

    def test_a_table_in_a_control_and_controls_around_rows_and_cells(self):
        """A repeating-section control wraps a row; a plain-text control can wrap a cell."""
        cell = "<w:tc><w:tcPr><w:tcW w:w=\"4675\" w:type=\"dxa\"/></w:tcPr>{}</w:tc>"
        table = (
            '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            '<w:tblGrid><w:gridCol w:w="4675"/><w:gridCol w:w="4675"/></w:tblGrid>'
            f"<w:tr>{cell.format(p('Authority'))}{cell.format(p('Page'))}</w:tr>"
            + control(f"<w:tr>{cell.format(p(MIRANDA))}{cell.format(p('4'))}</w:tr>")
            + f"<w:tr>{control(cell.format(p(ROE)))}{cell.format(control(p('7')))}</w:tr>"
            "</w:tbl>"
        )
        text = text_of(p("Before.") + control(table) + p("After."))
        assert text == f"Before.\n\nAuthority | Page\n\n{MIRANDA} | 4\n\n{ROE} | 7\n\nAfter."

    def test_custom_xml_and_smart_tags_are_read_through(self):
        body = (
            f'<w:customXml w:uri="urn:court:brief" w:element="argument"><w:customXmlPr><w:attr w:name="n" w:val="1"/></w:customXmlPr>{p(f"See {MIRANDA}.")}'
            f"<w:tbl><w:tr><w:tc>{p('In a table.')}</w:tc></w:tr></w:tbl></w:customXml>"
            '<w:p><w:r><w:t xml:space="preserve">Decided in </w:t></w:r>'
            '<w:smartTag w:uri="urn:schemas-microsoft-com:office:smarttags" w:element="place"><w:smartTagPr><w:attr w:name="x" w:val="y"/></w:smartTagPr>'
            "<w:r><w:t>Arizona</w:t></w:r></w:smartTag><w:r><w:t>.</w:t></w:r></w:p>"
        )
        assert text_of(body) == f"See {MIRANDA}.\n\nIn a table.\n\nDecided in Arizona."

    def test_controls_inside_controls(self):
        assert text_of(control(control(p("Inner.")) + p("Outer."))) == "Inner.\n\nOuter."

    def test_a_controls_properties_are_never_text(self):
        """Nothing under w:sdtPr or w:sdtEndPr is the document's text, whatever is put there."""
        properties = (
            '<w:alias w:val="Caption"/><w:id w:val="5"/><w:placeholder><w:docPart w:val="Placeholder text"/></w:placeholder>'
            '<w:dropDownList><w:listItem w:displayText="Plaintiff" w:value="P"/></w:dropDownList>'
            + p("A paragraph smuggled into the properties.")
        )
        body = f"<w:sdt><w:sdtPr>{properties}</w:sdtPr><w:sdtEndPr>{p('And into the end properties.')}</w:sdtEndPr><w:sdtContent>{p('Real text.')}</w:sdtContent></w:sdt>"
        assert text_of(body) == "Real text."
        inline = f"<w:p>{run('Before ')}<w:sdt><w:sdtPr>{run('Click or tap here to enter text.')}</w:sdtPr><w:sdtContent>{run('the value')}</w:sdtContent></w:sdt>{run(' after.')}</w:p>"
        assert text_of(inline) == "Before the value after."

    def test_controls_in_footnotes_and_endnotes(self):
        body = (
            '<w:p><w:r><w:t>Body.</w:t></w:r><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="2"/></w:r>'
            '<w:r><w:rPr><w:rStyle w:val="EndnoteReference"/></w:rPr><w:endnoteReference w:id="1"/></w:r></w:p>'
        )
        note = (
            '<w:{kind} w:id="{id}">' + control(
                '<w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:{kind}Ref/></w:r>'
                '<w:r><w:t xml:space="preserve"> See </w:t></w:r>' + control("<w:r><w:t>{cite}</w:t></w:r>") + "<w:r><w:t>.</w:t></w:r></w:p>"
            ) + "</w:{kind}>"
        )
        parsed = read(word_docx(
            body,
            footnotes=note.format(kind="footnote", id=2, cite=MIRANDA),
            endnotes=note.format(kind="endnote", id=1, cite=ROE),
        ))
        assert parsed.text == f"Body.\n\n[^1] See {MIRANDA}.\n\n[^e1] See {ROE}."
        assert (parsed.footnote_count, parsed.endnote_count) == (1, 1)

    def test_containers_count_toward_the_depth_limit(self, monkeypatch):
        monkeypatch.setattr(parser_module, "DOCX_MAX_DEPTH", 20)
        deep = p("x")
        for _ in range(12):
            deep = f"<w:sdt><w:sdtContent>{deep}</w:sdtContent></w:sdt>"
        with pytest.raises(DocumentTooComplexError, match="nested more than 20 levels deep"):
            text_of(deep)
        monkeypatch.setattr(parser_module, "DOCX_MAX_DEPTH", 40)
        assert text_of(deep) == "x"

    def test_containers_and_their_skipped_properties_count_toward_the_element_limit(self, monkeypatch):
        monkeypatch.setattr(parser_module, "DOCX_MAX_ELEMENTS", 500)
        with pytest.raises(DocumentTooComplexError, match="more than 500 elements"):
            text_of("<w:sdt><w:sdtPr>" + "<w:tag/>" * 600 + "</w:sdtPr><w:sdtContent/></w:sdt>")
        with pytest.raises(DocumentTooComplexError, match="more than 500 elements"):
            text_of("<w:sdt><w:sdtContent/></w:sdt>" * 300)


# --- a PDF header is a header only at the start of the file (H5 = PF-7b) ---------------------------

PDF = make_pdf([(700, f"See {MIRANDA}.")])
EMAIL = (
    "From: clerk@example.org\r\nTo: counsel@example.org\r\nSubject: Rejected filing\r\n\r\n"
    "Your upload was rejected because the file does not begin with %PDF-1.4 as a PDF must.\r\n"
    f"Please refile. See {MIRANDA}.\r\n"
).encode()


class TestPdfHeaderDetection:
    @pytest.mark.parametrize("text", [
        EMAIL,
        b"Notes on filing: the PDF should begin with %PDF- and end with %%EOF. See Roe v. Wade, 410 U.S. 113 (1973).",
        "Café notes — the header %PDF-1.7 is missing.".encode(),             # UTF-8, not ASCII
        "Café notes: the header %PDF-1.7 is missing from the file.".encode("cp1252"),  # Windows-1252
        b"\xef\xbb\xbfA note with a byte-order mark that mentions %PDF-1.4.",
        b"x%PDF-1.4",
    ])
    def test_text_that_mentions_a_pdf_header_is_text(self, text):
        assert detect_format(text, "notes.txt") == "txt"
        assert DocumentParser().parse_document(text, "notes.txt").format == "txt"

    def test_the_email_is_read_whole(self):
        assert MIRANDA in DocumentParser().parse_document(EMAIL, "mail.txt").text

    def test_a_word_file_whose_first_entry_holds_a_pdf_header_is_a_word_file(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("docProps/note.txt", "%PDF-1.4 is how a PDF begins")
            with zipfile.ZipFile(io.BytesIO(word_docx(p(f"See {MIRANDA}.")))) as source:
                for item in source.infolist():
                    archive.writestr(item.filename, source.read(item.filename))
        data = buffer.getvalue()
        assert b"%PDF-" in data[:1024]
        assert detect_format(data, "a.docx") == "docx"
        assert read(data).text == f"See {MIRANDA}."

    @pytest.mark.parametrize("prefix", [
        b"",
        b"\xef\xbb\xbf",                                  # a UTF-8 byte-order mark
        b"\r\n\r\n   ",                                    # blank lines
        b"\x00" * 128,                                     # NUL padding (a MacBinary header is this)
        b"\x1b%-12345X@PJL JOB\r\n@PJL ENTER LANGUAGE=PDF\r\n",   # a printer job header
        b"\x04\x00\xff\xfe\x9c",                           # a few junk bytes
    ])
    def test_a_real_pdf_is_a_pdf_with_or_without_junk_in_front_of_its_header(self, prefix):
        assert detect_format(prefix + PDF, "brief.pdf") == "pdf"

    @pytest.mark.parametrize("prefix", [b"", b"\x00" * 128, b"\x1b%-12345X@PJL JOB\r\n"])
    def test_a_pdf_with_junk_in_front_of_its_header_is_still_read(self, prefix):
        parsed = DocumentParser().parse_document(prefix + PDF, "brief.pdf")
        assert parsed.format == "pdf" and "Miranda v. Arizona" in parsed.text

    def test_a_pdf_header_past_the_first_kilobyte_is_not_looked_for(self):
        with pytest.raises(UnsupportedDocumentError):
            detect_format(b"\x00\x01\x02" * 400 + PDF, "x.bin")


# --- Strict Open XML, and the tab of a table of contents (H6) --------------------------------------

REFERENCES = (
    '<w:p><w:r><w:t>First.</w:t></w:r><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="2"/></w:r></w:p>'
    '<w:p><w:r><w:t>Second.</w:t></w:r><w:r><w:rPr><w:rStyle w:val="EndnoteReference"/></w:rPr><w:endnoteReference w:id="1"/></w:r></w:p>'
)


def note(kind: str, ident: int, inner: str) -> str:
    """A footnote or endnote as Word writes it: the reference mark, a space, then the text."""
    style = "FootnoteText" if kind == "footnote" else "EndnoteText"
    mark = (
        f'<w:r><w:rPr><w:rStyle w:val="{kind.capitalize()}Reference"/></w:rPr><w:{kind}Ref/></w:r>'
        '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
    )
    if not inner.startswith("<w:p>"):
        inner = f'<w:p>{inner}</w:p>'
    inner = inner.replace("<w:p>", f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{mark}', 1)
    return f'<w:{kind} w:id="{ident}">{inner}</w:{kind}>'


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


class TestStrictOpenXml:
    def build(self, strict: bool) -> bytes:
        body = (
            REFERENCES
            + control(p("In a control."))
            + f"<w:tbl><w:tr><w:tc>{p('A1')}</w:tc><w:tc>{p('B1')}</w:tc></w:tr></w:tbl>"
            + "<w:p><w:r><w:t>one</w:t><w:tab/><w:t>two</w:t><w:noBreakHyphen/><w:t>three</w:t></w:r></w:p>"
        )
        return word_docx(
            body,
            footnotes=note("footnote", 2, run(f"See {MIRANDA}.")),
            endnotes=note("endnote", 1, run(f"See {ROE}.")),
            strict=strict,
        )

    def test_the_fixture_really_is_in_the_strict_namespace(self):
        with zipfile.ZipFile(io.BytesIO(self.build(strict=True))) as archive:
            for part in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
                xml = archive.read(part).decode()
                assert 'xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main"' in xml
                assert "schemas.openxmlformats.org/wordprocessingml" not in xml

    def test_a_strict_document_reads_exactly_like_the_same_document_saved_the_usual_way(self):
        usual, strict = read(self.build(strict=False)), read(self.build(strict=True))
        assert usual.text == (
            f"First.\n\nSecond.\n\nIn a control.\n\nA1 | B1\n\none two-three\n\n[^1] See {MIRANDA}.\n\n[^e1] See {ROE}."
        )
        assert strict.text == usual.text
        assert (strict.footnote_count, strict.endnote_count) == (1, 1)

    def test_separator_notes_are_skipped_in_a_strict_document_too(self):
        """w:type and w:id are attributes in the strict namespace there."""
        assert "[^2]" not in read(self.build(strict=True)).text


def test_a_positional_tab_separates_words_like_any_tab():
    """w:ptab is what a table-of-contents line and right-aligned text use between entry and page."""
    body = (
        '<w:p><w:r><w:t>Roe v. Wade,</w:t></w:r><w:r><w:ptab w:relativeTo="margin" w:alignment="right" w:leader="dot"/></w:r>'
        "<w:r><w:t>410 U.S. 113</w:t></w:r></w:p>"
    )
    assert text_of(body) == "Roe v. Wade, 410 U.S. 113"


# --- text boxes: once, and as paragraphs of their own (F5) -----------------------------------------


def text_box(content: str, anchor_id: int = 1) -> str:
    """A text box as Word writes it: the drawing in mc:Choice and a VML copy of it in mc:Fallback."""
    return (
        "<w:r><w:rPr><w:noProof/></w:rPr><mc:AlternateContent><mc:Choice Requires=\"wps\"><w:drawing>"
        '<wp:anchor distT="45720" distB="45720" distL="114300" distR="114300" simplePos="0" relativeHeight="251659264" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
        f'<wp:simplePos x="0" y="0"/><wp:extent cx="2360930" cy="1404620"/><wp:docPr id="{anchor_id}" name="Text Box 2"/>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp>'
        f"<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic></wp:anchor>"
        "</w:drawing></mc:Choice><mc:Fallback><w:pict>"
        '<v:shape id="Text Box 2" o:spid="_x0000_s1026" type="#_x0000_t202" style="position:absolute;width:185.9pt;height:110.6pt">'
        f"<v:textbox><w:txbxContent>{content}</w:txbxContent></v:textbox><w10:wrap type=\"square\"/></v:shape>"
        "</w:pict></mc:Fallback></mc:AlternateContent></w:r>"
    )


QUOTE = "Pull quote: see Smith v. Jones, 123 F.3d 456, 460 (9th Cir. 1997)."


class TestTextBoxes:
    def test_a_text_box_is_read_once_and_as_its_own_paragraph(self):
        body = p("Before.") + f"<w:p>{run('The sentence that anchors the box ')}{text_box(p(QUOTE))}{run('goes on after it.')}</w:p>" + p("After.")
        assert text_of(body) == f"Before.\n\n{QUOTE}\n\nThe sentence that anchors the box goes on after it.\n\nAfter."

    def test_each_paragraph_of_a_box_is_a_paragraph_and_its_table_a_table(self):
        box = text_box(p("Box one.") + p("Box two.") + f"<w:tbl><w:tr><w:tc>{p('A1')}</w:tc><w:tc>{p('B1')}</w:tc></w:tr></w:tbl>")
        assert text_of(f"<w:p>{run('Host.')}{box}</w:p>") == "Box one.\n\nBox two.\n\nA1 | B1\n\nHost."

    def test_an_older_vml_only_text_box_is_read(self):
        """Compatibility-mode documents hold only the w:pict form, with no mc:AlternateContent."""
        box = f'<w:r><w:pict><v:shape type="#_x0000_t202"><v:textbox><w:txbxContent>{p(QUOTE)}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>'
        assert text_of(f"<w:p>{run('Host.')}{box}</w:p>") == f"{QUOTE}\n\nHost."

    def test_a_fallback_is_read_when_there_is_no_choice_and_only_the_first_choice_otherwise(self):
        only_fallback = f"<w:r><mc:AlternateContent><mc:Fallback>{run('fallback').replace('<w:r>', '').replace('</w:r>', '')}</mc:Fallback></mc:AlternateContent></w:r>"
        two_choices = (
            '<w:r><mc:AlternateContent><mc:Choice Requires="w14"><w:t>first</w:t></mc:Choice>'
            '<mc:Choice Requires="wps"><w:t>second</w:t></mc:Choice><mc:Fallback><w:t>third</w:t></mc:Fallback></mc:AlternateContent></w:r>'
        )
        assert text_of(f"<w:p>{only_fallback}{run(' ')}{two_choices}</w:p>") == "fallback first"

    def test_a_text_box_in_a_table_cell_stays_in_its_cell(self):
        body = f"<w:tbl><w:tr><w:tc><w:p>{run('Cell.')}{text_box(p('Boxed.'))}</w:p></w:tc><w:tc>{p('Next cell.')}</w:tc></w:tr></w:tbl>"
        assert text_of(body) == "Boxed. Cell. | Next cell."

    def test_a_text_box_in_a_footnote_stays_in_its_footnote(self):
        parsed = read(word_docx(REFERENCES, footnotes=note("footnote", 2, run("Note text.") + text_box(p(QUOTE))), endnotes=note("endnote", 1, run("End."))))
        assert f"[^1] {QUOTE} Note text.\n" in parsed.text and parsed.text.count("Smith v. Jones") == 1

    def test_a_footnote_called_from_a_text_box_is_numbered_once(self):
        """The reference used to be seen in both copies of the box, which moved every later number."""
        ref = '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="{}"/></w:r>'
        body = f"<w:p>{run('Host.')}{text_box('<w:p>' + run('Boxed.') + ref.format(2) + '</w:p>')}</w:p><w:p>{run('Later.')}{ref.format(3)}</w:p>"
        parsed = read(word_docx(body, footnotes=note("footnote", 2, run("From the box.")) + note("footnote", 3, run("From the body."))))
        assert parsed.text.endswith("[^1] From the box.\n[^2] From the body.")

    def test_text_waiting_behind_open_text_boxes_counts_toward_the_text_limit(self):
        """A paragraph interrupted by a box keeps its text until the box closes. Boxes nested in
        boxes must not be a way to hold more text than one paragraph may."""
        part = parser_module._WordPart(parser_module._TextBudget(1000))
        w = parser_module.W_NS + "}"
        part.start(w + "body", {})
        with pytest.raises(DocumentTooLongError):
            for _ in range(6):
                for name in ("p", "r", "t"):
                    part.start(w + name, {})
                part.characters("x" * 300_000)
                part.end(w + "t")
                part.start(w + "txbxContent", {})
        assert part.elements < 20, "refused while the text was still waiting, not after"


# --- only the parts that are read count toward the size limits (CR-6) ------------------------------


def with_parts(data: bytes, parts: dict[str, bytes]) -> bytes:
    """The archive `data` with more parts added to it."""
    buffer = io.BytesIO(data)
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class TestArchiveLimitsCountWhatIsRead:
    def test_a_short_document_with_a_large_picture_is_read(self):
        """The reviewer's file: one paragraph and a 90 MiB bitmap that deflates to 90 KB."""
        buffer = io.BytesIO(word_docx(p(f"See {MIRANDA}.")))
        with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive, archive.open("word/media/exhibit1.bmp", "w", force_zip64=True) as out:
            for _ in range(90):
                out.write(b"\x00" * (1 << 20))
        data = buffer.getvalue()
        assert len(data) < 200_000
        assert read(data).text == f"See {MIRANDA}."

    def test_parts_that_are_not_read_are_never_decompressed(self, monkeypatch):
        opened = []
        original = zipfile.ZipFile.open

        def recording_open(self, name, *args, **kw):
            opened.append(name if isinstance(name, str) else name.filename)
            return original(self, name, *args, **kw)

        data = word_docx(
            REFERENCES, footnotes=note("footnote", 2, run("Foot.")), endnotes=note("endnote", 1, run("End.")),
            extra_parts={"word/media/image1.png": b"\x89PNG" + b"\x00" * 100_000, "word/comments.xml": b"<x/>", "word/embeddings/sheet.xlsx": b"PK" * 50_000},
        )
        monkeypatch.setattr(zipfile.ZipFile, "open", recording_open)
        read(data)
        assert opened == ["word/document.xml", "word/footnotes.xml", "word/endnotes.xml"]

    def test_the_size_limits_still_hold_for_every_part_that_is_read(self, monkeypatch):
        monkeypatch.setattr(parser_module, "MAX_PART_BYTES", 1 << 20)
        monkeypatch.setattr(parser_module, "MAX_EXPANDED_BYTES", 2 << 20)
        base = word_docx(p("Body."))
        blank = b" " * (900 * 1024)
        notes = b'<w:%s xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">%s</w:%s>'
        footnotes, endnotes = notes % (b"footnotes", blank, b"footnotes"), notes % (b"endnotes", blank, b"endnotes")
        big_picture = b"\x00" * (8 << 20)

        assert read(with_parts(base, {"word/media/big.bmp": big_picture})).text == "Body."    # not read: not counted
        both = with_parts(base, {"word/footnotes.xml": footnotes, "word/endnotes.xml": endnotes})
        assert read(both).text == "Body."                                                     # read, under both limits
        for name in ("word/footnotes.xml", "word/endnotes.xml"):                              # one read part over the per-part limit
            with pytest.raises(UnsupportedDocumentError, match="unreasonable size"):
                read(with_parts(base, {name: notes % (b"x", blank + blank, b"x")}))
        monkeypatch.setattr(parser_module, "MAX_EXPANDED_BYTES", 1_500_000)                   # the same two, now over the total
        with pytest.raises(UnsupportedDocumentError, match="unreasonable size"):
            read(both)

    def test_an_oversized_document_part_is_refused_before_it_is_opened(self, monkeypatch):
        monkeypatch.setattr(parser_module, "MAX_PART_BYTES", 1 << 20)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "<w:document>" + " " * (2 << 20))
        monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: pytest.fail("the part was opened"))
        with pytest.raises(UnsupportedDocumentError, match="unreasonable size"):
            DocumentParser()._parse_docx(buffer.getvalue())

    def test_the_entry_limit_counts_every_entry_read_or_not(self, monkeypatch):
        monkeypatch.setattr(parser_module, "MAX_ZIP_ENTRIES", 20)
        extra = {f"word/media/image{i}.png": b"x" for i in range(30)}
        with pytest.raises(UnsupportedDocumentError, match="too many parts"):
            read(with_parts(word_docx(p("Body.")), extra))


# --- what is text and what is not --------------------------------------------------------------

CHANGE = 'w:id="7" w:author="A. Lawyer" w:date="2024-03-01T10:00:00Z"'


class TestWhatCountsAsText:
    def test_tracked_insertions_are_kept_and_deletions_are_not(self):
        body = (
            f"<w:p>{run('The court held ')}<w:del {CHANGE}><w:r><w:rPr><w:b/></w:rPr><w:delText xml:space=\"preserve\">wrongly </w:delText></w:r></w:del>"
            f"<w:ins {CHANGE}><w:r><w:t xml:space=\"preserve\">correctly </w:t></w:r></w:ins>{run('that it applies.')}"
            f"<w:pPr><w:rPr><w:del {CHANGE}/></w:rPr></w:pPr></w:p>"
        )
        assert text_of(body) == "The court held correctly that it applies."

    def test_a_tracked_move_is_read_where_it_moved_to_and_not_where_it_came_from(self):
        """Unlike a deletion, the source of a move keeps its text in w:t, so it was read twice."""
        moved = f"<w:r><w:t xml:space=\"preserve\">See {MIRANDA}. </w:t></w:r>"
        body = (
            f'<w:p><w:moveFromRangeStart w:id="1" w:name="move1" w:author="A" w:date="2024-03-01T10:00:00Z"/>'
            f"<w:moveFrom {CHANGE}>{moved}</w:moveFrom><w:moveFromRangeEnd w:id=\"1\"/>{run('First paragraph.')}</w:p>"
            f'<w:p>{run("Second paragraph. ")}<w:moveToRangeStart w:id="2" w:name="move1" w:author="A" w:date="2024-03-01T10:00:00Z"/>'
            f"<w:moveTo {CHANGE}>{moved}</w:moveTo><w:moveToRangeEnd w:id=\"2\"/></w:p>"
        )
        assert text_of(body) == f"First paragraph.\n\nSecond paragraph. See {MIRANDA}."

    def test_comments_are_not_body_text(self):
        body = (
            f'<w:p><w:commentRangeStart w:id="0"/>{run("Commented text.")}<w:commentRangeEnd w:id="0"/>'
            '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r></w:p>'
        )
        comments = (
            '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="0" w:author="Partner" w:initials="P">'
            "<w:p><w:r><w:annotationRef/></w:r><w:r><w:t>Check this against 5 U.S.C. § 552.</w:t></w:r></w:p></w:comment></w:comments>"
        ).encode()
        assert text_of(body, extra_parts={"word/comments.xml": comments}) == "Commented text."

    def test_text_formatted_as_hidden_is_not_read(self):
        """Hidden text is not printed. Only the run's own formatting is looked at."""
        hidden = '<w:r><w:rPr><w:vanish/></w:rPr><w:t xml:space="preserve">[note to self: check 1 U.S. 1] </w:t></w:r>'
        not_hidden = '<w:r><w:rPr><w:vanish w:val="0"/><w:webHidden/></w:rPr><w:t xml:space="preserve">kept </w:t></w:r>'
        body = f"<w:p><w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr>{run('Shown ')}{hidden}{not_hidden}{run('too.')}</w:p>"
        assert text_of(body) == "Shown kept too."

    def test_field_codes_are_not_text_and_field_results_are(self):
        marked = field('TA \\l "Miranda v. Arizona, 384 U.S. 436 (1966)" \\s "Miranda" \\c 1', "")
        ref = field("REF _Ref123 \\h", run("Section II"))
        simple = '<w:fldSimple w:instr=" PAGE "><w:r><w:t>3</w:t></w:r></w:fldSimple>'
        body = f"<w:p>{run(f'See {MIRANDA}')}{marked}{run(' and ')}{ref}{run(', page ')}{simple}{run('.')}</w:p>"
        assert text_of(body) == f"See {MIRANDA} and Section II, page 3."

    def test_a_hyperlinks_display_text_is_kept(self):
        link = '<w:hyperlink r:id="rId8" w:history="1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr><w:t>https://www.supremecourt.gov/opinions</w:t></w:r></w:hyperlink>'
        assert text_of(f"<w:p>{run('Available at ')}{link}{run('.')}</w:p>") == "Available at https://www.supremecourt.gov/opinions."

    def test_optional_hyphens_vanish_and_no_break_hyphens_are_hyphens(self):
        body = "<w:p><w:r><w:t>con</w:t><w:softHyphen/><w:t>stitutional, 42 U.S.C. § 2000e</w:t><w:noBreakHyphen/><w:t>2</w:t></w:r></w:p>"
        assert text_of(body) == "constitutional, 42 U.S.C. § 2000e-2"

    def test_the_reference_mark_inside_a_footnote_does_not_repeat_its_number(self):
        parsed = read(word_docx(REFERENCES, footnotes=note("footnote", 2, run(f"See {MIRANDA}.")), endnotes=note("endnote", 1, run("End."))))
        assert f"\n\n[^1] See {MIRANDA}.\n\n[^e1] End." in parsed.text

    def test_a_footnote_with_several_paragraphs_and_a_table_is_one_footnote(self):
        inner = (
            f"<w:p>{run('First paragraph.')}</w:p><w:p>{run(f'See {MIRANDA}.')}</w:p>"
            f"<w:tbl><w:tr><w:tc>{p('Cell one.')}</w:tc><w:tc>{p(f'See {ROE}.')}</w:tc></w:tr></w:tbl><w:p>{run('Last.')}</w:p>"
        )
        parsed = read(word_docx(REFERENCES, footnotes=note("footnote", 2, inner), endnotes=note("endnote", 1, run("End."))))
        assert f"[^1] First paragraph. See {MIRANDA}. Cell one. See {ROE}. Last.\n\n[^e1] End." in parsed.text
        assert parsed.footnote_count == 1 and parsed.text.count("[^") == 2
