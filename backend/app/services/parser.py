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
   are bounded before anything is parsed, and each XML part is streamed through
   the parser (no tree is built) with its element count, nesting depth and text
   bounded as it goes. This runs inside the child process of services/sandbox.py.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.parsers import expat

from ..limits import (
    DOCX_MAX_DEPTH,
    DOCX_MAX_ELEMENTS,
    MAX_TEXT_CHARS,
    complex_message,
    too_long_message,
)

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


# ---- Word XML, streamed ---------------------------------------------------------------------------
#
# A Word part is read once, through expat's callbacks, and no tree is built. Building one used to
# cost about 60 bytes of memory for every byte of XML and held the interpreter lock while it did:
# a 44 KB file of unclosed <w:b> tags took 1.8 GB. Here memory is the open path (at most
# DOCX_MAX_DEPTH names) and the text kept, the element count is capped, and text is counted as it is
# read so that the read stops at the text limit instead of after the whole part has been walked.

_NS = W_NS + "}"            # expat is told to join a namespace and a name with "}"
_P, _T, _TBL, _TR, _TC, _BODY = (_NS + n for n in ("p", "t", "tbl", "tr", "tc", "body"))
_BREAKS = frozenset(_NS + n for n in ("tab", "br", "cr"))
_NO_BREAK_HYPHEN = _NS + "noBreakHyphen"
_FOOTNOTE_REF, _ENDNOTE_REF = _NS + "footnoteReference", _NS + "endnoteReference"
_ID, _TYPE = _NS + "id", _NS + "type"
_SEPARATOR_NOTES = frozenset({"separator", "continuationSeparator", "continuationNotice"})
_SQUEEZE = re.compile(r"[ \t]+")
_UNSAFE = "This file contains content that cannot be read safely."


class _TextBudget:
    """The characters of text still allowed, shared by the parts of one document.

    The reading stops once the text is clearly over the limit: a little over, not exactly at it,
    because the text is counted before it is joined with its separators and footnote marks. A
    document that is only just over is read to the end and refused by the exact check, with its
    true size in the message."""

    SLACK = 65_536

    def __init__(self, limit: int):
        self.limit = limit
        self.spent = 0

    def add(self, n: int) -> None:
        self.spent += n
        if self.spent > self.limit + self.SLACK:
            raise DocumentTooLongError(too_long_message(self.spent, self.limit, exact=False))


class _WordPart:
    """Collects, from one Word XML part, what the old tree walk collected:

    * `blocks`: the body's paragraphs and table rows, in order (a row is its cells' text joined by
      " | "; a cell is its paragraphs joined by a space). Only paragraphs and tables that are direct
      children of w:body count, as before. A table inside a table cell is part of that cell: its
      paragraphs are read once, in place. (They used to be read twice, once as part of the cell and
      again as rows of their own, so every extra level of nesting repeated the text once more, and a
      3 KB file of nested tables became a million characters.)
    * `footnote_refs` / `endnote_refs`: the note ids in the order they are referenced.
    * `notes`: for a part read with `note_tag`, each note's text by id (separator notes skipped).

    A paragraph's text is its w:t text, with tabs and breaks as spaces and no-break hyphens as "-";
    text inside tracked insertions counts and tracked deletions (w:delText) do not."""

    def __init__(self, budget: _TextBudget, note_tag: str | None = None):
        self.budget = budget
        self.note_tag = _NS + note_tag if note_tag else None
        self.max_elements, self.max_depth = DOCX_MAX_ELEMENTS, DOCX_MAX_DEPTH
        self.elements = 0
        self.path: list[str] = []
        self.para_depth = 0
        self.pieces: list[str] = []
        self.pending = 0
        self.in_text = False
        self.counted: list[bool] = []       # for each open w:tbl: is it one whose rows are read?
        self.table_depth = 0
        self.row_cells: list[str] | None = None
        self.cell_paras: list[str] | None = None
        self.blocks: list[str] = []
        self.footnote_refs: list[str] = []
        self.endnote_refs: list[str] = []
        self.notes: dict[str, str] = {}
        self.note_id: str | None = None
        self.note_paras: list[str] | None = None

    def start(self, name: str, attrs: dict) -> None:
        self.elements += 1
        if self.elements > self.max_elements:
            raise DocumentTooComplexError(complex_message(f"it has more than {self.max_elements:,} elements"))
        if len(self.path) >= self.max_depth:
            raise DocumentTooComplexError(complex_message(f"its text is nested more than {self.max_depth} levels deep"))
        path = self.path
        if name == _P:
            if self.para_depth == 0:
                self.pieces, self.pending = [], 0
            self.para_depth += 1
        elif name == _T:
            self.in_text = True
        elif self.para_depth and name in _BREAKS:
            self.pieces.append(" ")
        elif self.para_depth and name == _NO_BREAK_HYPHEN:
            self.pieces.append("-")
        elif name == _TBL:
            counted = self.table_depth > 0 or (bool(path) and path[-1] == _BODY)
            self.counted.append(counted)
            if counted:
                self.table_depth += 1
        elif name == _TR and self.table_depth == 1:
            self.row_cells = []
        elif name == _TC and self.table_depth == 1 and path and path[-1] == _TR:
            self.cell_paras = []
        elif name == _FOOTNOTE_REF:
            ref = attrs.get(_ID)
            if ref is not None:
                self.footnote_refs.append(ref)
        elif name == _ENDNOTE_REF:
            ref = attrs.get(_ID)
            if ref is not None:
                self.endnote_refs.append(ref)
        elif name == self.note_tag:
            ident = attrs.get(_ID)
            if ident is not None and attrs.get(_TYPE) not in _SEPARATOR_NOTES:
                self.note_id, self.note_paras = ident, []
        path.append(name)

    def characters(self, data: str) -> None:
        if self.in_text and self.para_depth:
            self.pieces.append(data)
            self.pending += len(data)
            # a single run of text far past what is left is over the limit already
            if self.pending > self.budget.limit - self.budget.spent + 1_000_000:
                raise DocumentTooLongError(too_long_message(self.pending, self.budget.limit, exact=False))

    def end(self, name: str) -> None:
        path = self.path
        path.pop()
        if name == _T:
            self.in_text = False
        elif name == _P:
            self.para_depth -= 1
            if self.para_depth == 0:
                self._paragraph_done()
        elif name == _TC and self.table_depth == 1 and self.cell_paras is not None and path and path[-1] == _TR:
            text = " ".join(self.cell_paras)
            self.cell_paras = None
            if text and self.row_cells is not None:
                self.row_cells.append(text)
        elif name == _TR and self.table_depth == 1:
            if self.row_cells:
                self.blocks.append(" | ".join(self.row_cells))
            self.row_cells = None
        elif name == _TBL:
            if self.counted.pop():
                self.table_depth -= 1
        elif name == self.note_tag and self.note_id is not None:
            text = " ".join(self.note_paras or [])
            if text:
                self.notes[self.note_id] = text
            self.note_id, self.note_paras = None, None

    def _paragraph_done(self) -> None:
        text = _SQUEEZE.sub(" ", "".join(self.pieces)).strip()
        self.pieces, self.pending = [], 0
        if not text:
            return
        self.budget.add(len(text) + 2)
        if self.note_paras is not None:
            self.note_paras.append(text)
        elif self.cell_paras is not None:
            self.cell_paras.append(text)
        elif self.path and self.path[-1] == _BODY:
            self.blocks.append(text)


class DocumentParser:
    """Extracts text from uploaded documents."""

    def __init__(self, max_text_chars: int | None = None):
        # The most text a Word document may hold; the reader stops at it. None means the server's limit.
        self.max_text_chars = max_text_chars

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
        from . import pdf_text
        from .pdf_text import PdfReadError, PdfTimeoutError, PdfTooLongError, read_pdf

        try:
            result = read_pdf(content)
        except PdfTooLongError as exc:
            raise DocumentTooLongError(str(exc)) from exc
        except PdfTimeoutError as exc:
            # the same answer as when the child is stopped for time: too complex for this server's limits
            raise DocumentTooComplexError(complex_message(
                f"reading it took longer than the {pdf_text.PDF_TIME_BUDGET_S:g} seconds one PDF is allowed")) from exc
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

        budget = _TextBudget(self.max_text_chars if self.max_text_chars is not None else MAX_TEXT_CHARS)
        with archive:
            self._check_archive(archive)
            document = _WordPart(budget)
            if not self._scan(archive, "word/document.xml", document):
                raise UnsupportedDocumentError("This Word file has no document body.")
            footnotes = self._scan_notes(archive, "word/footnotes.xml", "footnote", budget)
            endnotes = self._scan_notes(archive, "word/endnotes.xml", "endnote", budget)

        body_text = "\n\n".join(document.blocks)
        sections = [body_text]

        numbered_footnotes = self._number(document.footnote_refs, footnotes)
        if numbered_footnotes:
            lines = [
                f"{FOOTNOTE_MARKER.format(n=n)} {text}" for n, text in numbered_footnotes
            ]
            sections.append("\n".join(lines))

        numbered_endnotes = self._number(document.endnote_refs, endnotes)
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
    def _scan(archive: zipfile.ZipFile, name: str, part: _WordPart) -> bool:
        """Stream the archive member `name` through `part`. False if there is no such member.

        Entity declarations are how XML expansion attacks work, and no Word part has a legitimate
        use for one, so any DOCTYPE is refused (the parser reports it whatever the file's encoding)."""
        try:
            info = archive.getinfo(name)
        except KeyError:
            return False

        def refuse(*args):
            raise UnsupportedDocumentError(_UNSAFE)

        parser = expat.ParserCreate(None, "}")
        parser.buffer_text = True
        parser.StartElementHandler = part.start
        parser.EndElementHandler = part.end
        parser.CharacterDataHandler = part.characters
        parser.StartDoctypeDeclHandler = refuse
        parser.EntityDeclHandler = refuse
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        try:
            read = 0
            with archive.open(info) as member:
                while True:
                    chunk = member.read(1 << 16)
                    if not chunk:
                        break
                    read += len(chunk)
                    if read > MAX_PART_BYTES:
                        raise UnsupportedDocumentError("This file expands to an unreasonable size.")
                    parser.Parse(chunk, False)
            parser.Parse(b"", True)
        except expat.ExpatError as exc:
            raise UnsupportedDocumentError("This Word file contains damaged text.") from exc
        return True

    def _scan_notes(self, archive: zipfile.ZipFile, part: str, tag: str, budget: _TextBudget) -> dict[str, str]:
        """Map each note id to its text, skipping Word's separator notes."""
        notes = _WordPart(budget, note_tag=tag)
        return notes.notes if self._scan(archive, part, notes) else {}

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
