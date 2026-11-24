"""Document parsing for PDF, DOCX and plain-text files.

Three properties matter here, and each one was a real failure:

1. The format is decided from the file's own bytes, never from the Content-Type
   the browser reports. Phones routinely send an empty or generic type for Word
   and PDF files that come from iCloud or Google Drive, and trusting it meant
   those uploads were rejected before any parsing happened.

2. Word footnotes and endnotes are read. Law review drafts keep their citations
   in footnotes, and the body-only extraction returned zero citations for them.
   Footnotes come back with the numbers Word actually displays, rather than a
   number guessed from the text.

3. The archive is treated as hostile input. A DOCX is a ZIP, and this endpoint is
   public, so the entry count, the expanded size and any XML entity declaration
   are bounded before anything is parsed.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

# Limits on what a DOCX may expand to. A 10 MB upload can legitimately hold a
# long document; it cannot legitimately expand to gigabytes.
MAX_ZIP_ENTRIES = 2000
MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_PART_BYTES = 40 * 1024 * 1024

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W_NS}}}"

# Marker written in front of each extracted footnote. Markdown's footnote
# syntax, because it cannot be confused with a reporter volume or a statute
# title at the start of a line, which is how a footnote that begins
# "47 U.S.C. § 230" would otherwise be misread.
FOOTNOTE_MARKER = "[^{n}]"
ENDNOTE_MARKER = "[^e{n}]"


class UnsupportedDocumentError(ValueError):
    """The file is a kind this tool cannot read. The message says what to do."""


class DocumentTooLongError(UnsupportedDocumentError):
    """Over the page or text limit. The server answers 413 so the page can state the limit."""


class DocumentTooComplexError(DocumentTooLongError):
    """Within the size limits, but it needs more memory, time or nesting than one upload may
    use. Also a 413; the message (see limits.complex_message) says why and what to do."""


@dataclass
class ParsedDocument:
    text: str
    format: str
    footnote_count: int = 0
    endnote_count: int = 0
    warnings: list[str] = field(default_factory=list)


def detect_format(content: bytes, filename: str | None = None) -> str:
    """Identify the file from its bytes. The filename only breaks ties."""
    head = content[:4096]

    if head.lstrip().startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
        return "pdf"

    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise UnsupportedDocumentError(
                "This file looks damaged and could not be opened."
            ) from exc
        if "word/document.xml" in names:
            return "docx"
        if "content.xml" in names:
            raise UnsupportedDocumentError(
                "OpenDocument (.odt) files are not supported. Save it as .docx or PDF."
            )
        if any(n.startswith("ppt/") for n in names) or any(n.startswith("xl/") for n in names):
            raise UnsupportedDocumentError(
                "This is a PowerPoint or Excel file. Upload a Word document, PDF or text file."
            )
        raise UnsupportedDocumentError(
            "This archive is not a Word document. Upload a .docx, PDF or text file."
        )

    # Legacy binary Word (.doc), which is an OLE compound file.
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise UnsupportedDocumentError(
            "Old-format Word (.doc) files are not supported. "
            "Open it in Word and save it as .docx, or export a PDF."
        )

    if head.lstrip().startswith(b"{\\rtf"):
        raise UnsupportedDocumentError(
            "Rich Text Format (.rtf) is not supported. Save it as .docx or PDF."
        )

    ext = (filename or "").lower().rsplit(".", 1)[-1] if filename and "." in filename else ""
    if ext in {"pages", "key", "numbers"}:
        raise UnsupportedDocumentError(
            "Apple Pages files are not supported. Export to Word (.docx) or PDF first."
        )

    # Anything left must be readable as text, or it is some other binary.
    if _looks_like_text(head):
        return "txt"

    raise UnsupportedDocumentError(
        "This file type is not supported. Upload a PDF, Word (.docx) or text file."
    )


def _looks_like_text(sample: bytes) -> bool:
    if not sample:
        return False
    if sample.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
        return True  # byte-order mark: UTF-16 or UTF-8 text
    if b"\x00" in sample:
        return False
    printable = sum(1 for b in sample if b in (9, 10, 13) or b >= 32)
    return printable / len(sample) > 0.95


def decode_text(content: bytes) -> str:
    """Decode text of unknown encoding without ever raising."""
    if content.startswith(b"\xef\xbb\xbf"):
        return content[3:].decode("utf-8", errors="replace")
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16", errors="replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        # Windows-1252 is what Word and Notepad write when it is not UTF-8.
        return content.decode("cp1252", errors="replace")


class DocumentParser:
    """Extracts text from uploaded documents."""

    def parse(
        self,
        content: bytes,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> str:
        """Return the document's text.

        `content_type` is accepted for backward compatibility and ignored. The
        format comes from the bytes.
        """
        return self.parse_document(content, filename).text

    def parse_document(self, content: bytes, filename: str | None = None) -> ParsedDocument:
        fmt = detect_format(content, filename)
        if fmt == "pdf":
            return self._parse_pdf(content)
        if fmt == "docx":
            return self._parse_docx(content)
        return ParsedDocument(text=decode_text(content), format="txt")

    # PDF ------------------------------------------------------------------

    def _parse_pdf(self, content: bytes) -> ParsedDocument:
        # pdfium page by page (memory stays flat however long the file is), pdfminer.six
        # only as a second opinion, and the page limit checked before any page is read.
        # See services/pdf_text.py for why this is not pdfplumber.
        from .pdf_text import PdfReadError, PdfTooLongError, read_pdf

        try:
            result = read_pdf(content)
        except PdfTooLongError as exc:
            raise DocumentTooLongError(str(exc)) from exc
        except PdfReadError as exc:
            raise UnsupportedDocumentError(str(exc)) from exc
        except Exception as exc:  # a parser bug must not become a 500 the page cannot read
            raise UnsupportedDocumentError(
                "This PDF could not be read. It may be damaged or password protected."
            ) from exc
        return ParsedDocument(text=result.text, format="pdf", warnings=result.warnings)

    # DOCX -----------------------------------------------------------------

    def _parse_docx(self, content: bytes) -> ParsedDocument:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise UnsupportedDocumentError("This Word file looks damaged.") from exc

        with archive:
            self._check_archive(archive)
            document = self._load_xml(archive, "word/document.xml")
            if document is None:
                raise UnsupportedDocumentError("This Word file has no document body.")

            footnotes = self._collect_notes(archive, "word/footnotes.xml", "footnote")
            endnotes = self._collect_notes(archive, "word/endnotes.xml", "endnote")

        body_text = self._body_text(document)
        footnote_order = self._reference_order(document, "footnoteReference")
        endnote_order = self._reference_order(document, "endnoteReference")

        sections = [body_text]

        numbered_footnotes = self._number(footnote_order, footnotes)
        if numbered_footnotes:
            lines = [
                f"{FOOTNOTE_MARKER.format(n=n)} {text}" for n, text in numbered_footnotes
            ]
            sections.append("\n".join(lines))

        numbered_endnotes = self._number(endnote_order, endnotes)
        if numbered_endnotes:
            lines = [
                f"{ENDNOTE_MARKER.format(n=n)} {text}" for n, text in numbered_endnotes
            ]
            sections.append("\n".join(lines))

        text = "\n\n".join(s for s in sections if s.strip())
        return ParsedDocument(
            text=text,
            format="docx",
            footnote_count=len(numbered_footnotes),
            endnote_count=len(numbered_endnotes),
        )

    @staticmethod
    def _check_archive(archive: zipfile.ZipFile) -> None:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise UnsupportedDocumentError("This file has too many parts to be a normal document.")
        total = 0
        for info in infos:
            if info.file_size > MAX_PART_BYTES:
                raise UnsupportedDocumentError("This file expands to an unreasonable size.")
            total += info.file_size
            if total > MAX_EXPANDED_BYTES:
                raise UnsupportedDocumentError("This file expands to an unreasonable size.")

    @staticmethod
    def _load_xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
        try:
            raw = archive.read(name)
        except KeyError:
            return None
        # Entity declarations are how XML expansion attacks work, and no Word
        # part has a legitimate use for one.
        if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw:
            raise UnsupportedDocumentError("This file contains content that cannot be read safely.")
        try:
            return ET.fromstring(raw)
        except ET.ParseError as exc:
            raise UnsupportedDocumentError("This Word file contains damaged text.") from exc

    @staticmethod
    def _paragraph_text(paragraph: ET.Element) -> str:
        """Text of one paragraph.

        Walking in document order includes tracked insertions (their runs sit
        under w:ins) and leaves out tracked deletions, whose text lives in
        w:delText, a different element.
        """
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == _W + "t":
                pieces.append(node.text or "")
            elif node.tag in (_W + "tab", _W + "br", _W + "cr"):
                pieces.append(" ")
            elif node.tag == _W + "noBreakHyphen":
                pieces.append("-")
        return re.sub(r"[ \t]+", " ", "".join(pieces)).strip()

    def _body_text(self, document: ET.Element) -> str:
        body = document.find(_W + "body")
        if body is None:
            return ""
        blocks: list[str] = []
        for child in body:
            if child.tag == _W + "p":
                text = self._paragraph_text(child)
                if text:
                    blocks.append(text)
            elif child.tag == _W + "tbl":
                for row in child.iter(_W + "tr"):
                    cells = []
                    for cell in row.findall(_W + "tc"):
                        cell_text = " ".join(
                            t for t in (self._paragraph_text(p) for p in cell.iter(_W + "p")) if t
                        )
                        if cell_text:
                            cells.append(cell_text)
                    if cells:
                        blocks.append(" | ".join(cells))
        return "\n\n".join(blocks)

    def _collect_notes(
        self, archive: zipfile.ZipFile, part: str, tag: str
    ) -> dict[str, str]:
        """Map each note id to its text, skipping Word's separator notes."""
        root = self._load_xml(archive, part)
        if root is None:
            return {}
        notes: dict[str, str] = {}
        for note in root.iter(_W + tag):
            if note.get(_W + "type") in {"separator", "continuationSeparator", "continuationNotice"}:
                continue
            note_id = note.get(_W + "id")
            if note_id is None:
                continue
            paragraphs = [self._paragraph_text(p) for p in note.iter(_W + "p")]
            text = " ".join(p for p in paragraphs if p)
            if text:
                notes[note_id] = text
        return notes

    @staticmethod
    def _reference_order(document: ET.Element, tag: str) -> list[str]:
        """Ids in the order the references appear, which is the order Word numbers them."""
        order: list[str] = []
        for node in document.iter(_W + tag):
            ref_id = node.get(_W + "id")
            if ref_id is not None:
                order.append(ref_id)
        return order

    @staticmethod
    def _number(order: list[str], notes: dict[str, str]) -> list[tuple[int, str]]:
        """Pair each referenced note with the number Word displays for it."""
        numbered: list[tuple[int, str]] = []
        seen: set[str] = set()
        for position, note_id in enumerate(order, start=1):
            if note_id in seen:
                continue
            seen.add(note_id)
            if note_id in notes:
                numbered.append((position, notes[note_id]))
        # Notes that exist but are never referenced still deserve reading.
        extra = [text for nid, text in notes.items() if nid not in seen]
        next_number = (numbered[-1][0] + 1) if numbered else 1
        for text in extra:
            numbered.append((next_number, text))
            next_number += 1
        return numbered
