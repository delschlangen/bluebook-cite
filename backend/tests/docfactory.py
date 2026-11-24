"""Builders for realistic test documents.

Built in code rather than checked in as binaries, so a test shows exactly what
the document contains and CI needs no fixtures. The Word builder writes real
footnotes.xml the way Word does, including its separator notes and arbitrary ids.
"""

import io
import zipfile

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_docx(
    paragraphs: list,
    footnotes: dict[int, str] | None = None,
    endnotes: dict[int, str] | None = None,
    extra_parts: dict[str, bytes] | None = None,
) -> bytes:
    """Build a .docx.

    `paragraphs` items are either a string, or a (text, [footnote ids]) pair, where
    the ids become footnoteReference runs after the text, in order. Footnote ids are
    deliberately not 1, 2, 3: Word's ids are arbitrary and its separator notes
    occupy -1 and 0, so a parser that numbers by id gets the wrong numbers.
    """
    body = []
    for item in paragraphs:
        text, refs = (item, []) if isinstance(item, str) else item
        runs = f'<w:r><w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'
        for ref in refs:
            kind = "endnoteReference" if endnotes and ref in endnotes and not (footnotes and ref in footnotes) else "footnoteReference"
            runs += f'<w:r><w:{kind} w:id="{ref}"/></w:r>'
        body.append(f"<w:p>{runs}</w:p>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {W}><w:body>{''.join(body)}</w:body></w:document>"
    )

    content_types = _CONTENT_TYPES
    doc_rels = ""
    parts: dict[str, bytes] = {}

    if footnotes is not None:
        notes = (
            '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
            '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        )
        for note_id, text in footnotes.items():
            notes += (
                f'<w:footnote w:id="{note_id}"><w:p><w:r><w:footnoteRef/></w:r>'
                f'<w:r><w:t xml:space="preserve"> {_esc(text)}</w:t></w:r></w:p></w:footnote>'
            )
        parts["word/footnotes.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes {W}>{notes}</w:footnotes>'
        ).encode()
        doc_rels += '<Relationship Id="rId10" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'

    if endnotes is not None:
        notes = ""
        for note_id, text in endnotes.items():
            notes += (
                f'<w:endnote w:id="{note_id}"><w:p><w:r><w:t xml:space="preserve">{_esc(text)}</w:t></w:r></w:p></w:endnote>'
            )
        parts["word/endnotes.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:endnotes {W}>{notes}</w:endnotes>'
        ).encode()
        doc_rels += '<Relationship Id="rId11" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/>'

    parts.update(extra_parts or {})

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", document)
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{doc_rels}</Relationships>",
        )
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf_pages(pages: list[list[tuple[int, str]]]) -> bytes:
    """A PDF with one page per item; each page is a list of (y, text) lines.

    Handwritten rather than generated with a library, so the test suite carries
    no PDF dependency beyond the parser under test. Each page has its own content
    stream, as in a real document, which is what makes page-by-page reading (and
    its memory behaviour) testable.
    """
    count = len(pages)
    # Object numbers: 1 catalog, 2 pages tree, 3 font, then (page, contents) pairs.
    first_page_obj = 4
    page_objs = [first_page_obj + 2 * i for i in range(count)]
    objects: list[str] = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids ["
        + " ".join(f"{n} 0 R" for n in page_objs)
        + f"] /Count {count} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, lines in enumerate(pages):
        stream = "BT /F1 12 Tf " + " ".join(
            f"1 0 0 1 72 {y} Tm ({_pdf_escape(t)}) Tj" for y, t in lines
        ) + " ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {page_objs[i] + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_pdf(lines: list[tuple[int, str]]) -> bytes:
    """A minimal one-page PDF with text at the given (y, text) positions."""
    return make_pdf_pages([lines])
