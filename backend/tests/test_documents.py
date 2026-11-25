"""Tests for uploading and reading documents.

Every case here reproduces something that failed for a real user: a phone sending
an empty file type, and a law review draft whose citations all live in footnotes.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.parser import (
    DocumentParser,
    UnsupportedDocumentError,
    detect_format,
)
from app.utils.text_normalize import NORMALIZATION, normalize_text
from tests.docfactory import make_docx, make_pdf

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# A WELL-FORMED minimal document body. The archive-limit tests must use this: if
# the body were malformed, the file would be refused for that reason and the test
# would pass even with the limit it claims to cover switched off.
WELL_FORMED_BODY = (
    '<?xml version="1.0"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>See Brandenburg v. Ohio, 395 U.S. 444 (1969).</w:t></w:r></w:p></w:body>"
    "</w:document>"
)

LAW_REVIEW = make_docx(
    [
        ("The First Amendment protects expressive conduct.", [41]),
        ("Courts later extended that rule to symbolic speech.", [97]),
    ],
    # Word's ids are arbitrary. 41 and 97 must come out as footnotes 1 and 2.
    footnotes={
        41: "See Brandenburg v. Ohio, 395 U.S. 444 (1969).",
        97: "47 U.S.C. § 230; Texas v. Johnson, 491 U.S. 397 (1989).",
    },
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestFormatDetectionIgnoresTheDeclaredType:
    """A phone reports an empty or generic type for files from iCloud and Drive."""

    @pytest.mark.parametrize("declared", ["", "application/octet-stream", "text/plain", DOCX_MIME])
    def test_docx_is_recognised_whatever_the_browser_claims(self, client, declared):
        response = client.post(
            "/api/upload", files={"file": ("brief.docx", LAW_REVIEW, declared)}
        )
        assert response.status_code == 200
        assert response.json()["format"] == "docx"

    @pytest.mark.parametrize("declared", ["", "application/octet-stream", "application/pdf"])
    def test_pdf_is_recognised_whatever_the_browser_claims(self, client, declared):
        pdf = make_pdf([(700, "See Brandenburg v. Ohio, 395 U.S. 444 (1969).")])
        response = client.post("/api/upload", files={"file": ("brief.pdf", pdf, declared)})
        assert response.status_code == 200
        assert response.json()["format"] == "pdf"
        assert "Brandenburg" in response.json()["full_text"]

    @pytest.mark.parametrize("declared", ["", "application/octet-stream", "text/plain"])
    def test_text_is_recognised_whatever_the_browser_claims(self, client, declared):
        response = client.post(
            "/api/upload", files={"file": ("notes.txt", b"47 U.S.C. \xc2\xa7 230 applies.", declared)}
        )
        assert response.status_code == 200
        assert response.json()["format"] == "txt"

    def test_a_misleading_extension_does_not_fool_it(self, client):
        # A Word file named .txt is still a Word file.
        response = client.post(
            "/api/upload", files={"file": ("looks-like-text.txt", LAW_REVIEW, "text/plain")}
        )
        assert response.status_code == 200
        assert response.json()["format"] == "docx"


class TestWordFootnotes:
    """Law review drafts keep their citations in footnotes. Reading only the body
    returned zero citations for them."""

    def test_footnotes_are_read_and_counted(self, client):
        body = client.post("/api/upload", files={"file": ("a.docx", LAW_REVIEW, "")}).json()
        assert body["footnote_count"] == 2
        assert "Brandenburg v. Ohio" in body["full_text"]
        assert "Texas v. Johnson" in body["full_text"]

    def test_citations_in_footnotes_are_found(self, client):
        upload = client.post("/api/upload", files={"file": ("a.docx", LAW_REVIEW, "")}).json()
        analysis = client.post(
            "/api/analyze",
            json={"document_id": "t", "text": upload["full_text"], "filename": "a.docx"},
        ).json()
        kinds = [c["type"] for c in analysis["analysis"]["citations"]]
        assert kinds.count("case") == 2
        assert "statute" in kinds

    def test_footnote_numbers_are_the_ones_word_displays_not_the_xml_ids(self, client):
        upload = client.post("/api/upload", files={"file": ("a.docx", LAW_REVIEW, "")}).json()
        analysis = client.post(
            "/api/analyze",
            json={"document_id": "t", "text": upload["full_text"], "filename": "a.docx"},
        ).json()
        by_text = {
            c["raw_text"]: c["footnote_number"] for c in analysis["analysis"]["citations"]
        }
        brandenburg = next(v for k, v in by_text.items() if "Brandenburg" in k)
        johnson = next(v for k, v in by_text.items() if "Johnson" in k)
        statute = next(v for k, v in by_text.items() if "U.S.C." in k)
        assert brandenburg == 1
        assert johnson == 2
        assert statute == 2

    def test_a_footnote_that_begins_with_a_number_is_not_misread(self, client):
        """'47 U.S.C. § 230' at the start of a note must not be taken for the
        note's own number."""
        doc = make_docx(
            [("Section 230 shields platforms.", [5])],
            footnotes={5: "47 U.S.C. § 230."},
        )
        upload = client.post("/api/upload", files={"file": ("a.docx", doc, "")}).json()
        analysis = client.post(
            "/api/analyze",
            json={"document_id": "t", "text": upload["full_text"], "filename": "a.docx"},
        ).json()
        (citation,) = analysis["analysis"]["citations"]
        assert citation["footnote_number"] == 1

    def test_separator_notes_are_not_counted(self):
        parsed = DocumentParser().parse_document(LAW_REVIEW, "a.docx")
        assert parsed.footnote_count == 2

    def test_a_note_marked_as_a_separator_is_excluded_even_when_it_has_text(self):
        """Word's continuationNotice note can carry real text ("continued on next
        page"). It is furniture, not a footnote, whatever it says."""
        notes_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:footnote w:type="continuationNotice" w:id="0"><w:p><w:r><w:t>continued on next page</w:t></w:r></w:p></w:footnote>'
            b'<w:footnote w:id="9"><w:p><w:r><w:t>See Brandenburg v. Ohio, 395 U.S. 444 (1969).</w:t></w:r></w:p></w:footnote>'
            b"</w:footnotes>"
        )
        doc = make_docx(
            [("Body.", [9])],
            footnotes={9: "placeholder"},
            extra_parts={"word/footnotes.xml": notes_xml},
        )
        parsed = DocumentParser().parse_document(doc, "a.docx")
        assert "continued on next page" not in parsed.text
        assert "Brandenburg" in parsed.text
        assert parsed.footnote_count == 1

    def test_an_unreferenced_note_is_still_read_and_numbered_after_the_rest(self):
        doc = make_docx(
            [("Body.", [3])],
            footnotes={3: "See Brandenburg v. Ohio, 395 U.S. 444 (1969).", 8: "47 U.S.C. § 230."},
        )
        parsed = DocumentParser().parse_document(doc, "a.docx")
        assert parsed.footnote_count == 2
        assert "[^2] 47 U.S.C." in parsed.text

    def test_endnotes_are_read_separately(self):
        doc = make_docx(
            [("Body text.", [3])],
            endnotes={3: "See Texas v. Johnson, 491 U.S. 397 (1989)."},
        )
        parsed = DocumentParser().parse_document(doc, "a.docx")
        assert parsed.endnote_count == 1
        assert "Texas v. Johnson" in parsed.text

    def test_body_only_documents_still_work(self):
        doc = make_docx(["See Brandenburg v. Ohio, 395 U.S. 444 (1969)."])
        parsed = DocumentParser().parse_document(doc, "a.docx")
        assert parsed.footnote_count == 0
        assert "Brandenburg" in parsed.text

    def test_tracked_deletions_are_excluded_and_insertions_included(self):
        xml = (
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Kept. </w:t></w:r>"
            "<w:del><w:r><w:delText>Deleted. </w:delText></w:r></w:del>"
            "<w:ins><w:r><w:t>Inserted.</w:t></w:r></w:ins></w:p></w:body></w:document>"
        )
        doc = make_docx([], extra_parts={})
        # Replace the generated body with the tracked-changes one.
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(doc)) as src, zipfile.ZipFile(rebuilt, "w") as dst:
            for item in src.infolist():
                data = xml.encode() if item.filename == "word/document.xml" else src.read(item.filename)
                dst.writestr(item.filename, data)
        text = DocumentParser().parse(rebuilt.getvalue(), None, "a.docx")
        assert "Kept." in text and "Inserted." in text
        assert "Deleted." not in text


def padded_part(root: str, size: int) -> str:
    """A well-formed, empty footnotes or endnotes part of `size` bytes. The archive-limit tests
    pad the parts the reader opens: the size limits are on those, and a part it never opens (a
    picture, say) is not counted, whatever its size (tests/test_docx_word_structures.py)."""
    head = f'<?xml version="1.0"?><w:{root} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    tail = f"</w:{root}>"
    return head + " " * (size - len(head) - len(tail)) + tail


class TestArchiveFixturesAreValid:
    """The limit tests are only meaningful if the same archive is accepted when
    nothing is over a limit. Otherwise they pass because the file is broken."""

    def test_the_padded_archive_is_accepted_when_under_every_limit(self, client):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", WELL_FORMED_BODY)
            z.writestr("word/footnotes.xml", padded_part("footnotes", 2 * 1024 * 1024))
            z.writestr("word/endnotes.xml", padded_part("endnotes", 768 * 1024))
        response = client.post("/api/upload", files={"file": ("ok.docx", archive.getvalue(), "")})
        assert response.status_code == 200
        assert "Brandenburg" in response.json()["full_text"]


class TestHostileAndUnsupportedFiles:
    def test_old_doc_format_explains_what_to_do(self, client):
        ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
        response = client.post("/api/upload", files={"file": ("old.doc", ole, "application/msword")})
        assert response.status_code == 415
        assert ".docx" in response.json()["detail"]

    def test_rtf_explains_what_to_do(self, client):
        response = client.post(
            "/api/upload", files={"file": ("a.rtf", b"{\\rtf1\\ansi Hello}", "application/rtf")}
        )
        assert response.status_code == 415
        assert "rtf" in response.json()["detail"].lower()

    def test_arbitrary_binary_is_refused_not_decoded_as_garbage(self, client):
        response = client.post(
            "/api/upload", files={"file": ("blob.bin", bytes(range(256)) * 8, "")}
        )
        assert response.status_code == 415

    def test_a_zip_that_is_not_word_is_refused(self, client):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("readme.txt", "hello")
        response = client.post("/api/upload", files={"file": ("a.zip", buffer.getvalue(), "")})
        assert response.status_code == 415

    def test_a_single_oversized_part_is_refused(self, client, monkeypatch):
        """One part that expands past the per-part limit."""
        import app.services.parser as parser_module

        monkeypatch.setattr(parser_module, "MAX_PART_BYTES", 1024 * 1024)
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", WELL_FORMED_BODY)
            z.writestr("word/footnotes.xml", padded_part("footnotes", 2 * 1024 * 1024))
        assert len(bomb.getvalue()) < 20_000, "the bomb must be small on the wire"
        response = client.post("/api/upload", files={"file": ("bomb.docx", bomb.getvalue(), "")})
        assert response.status_code == 415

    def test_many_parts_that_add_up_past_the_total_limit_are_refused(self, client, monkeypatch):
        """Each part is under the per-part limit, so only the TOTAL check can stop
        this. A bomb split across the parts that are read is the way round a
        per-part limit."""
        import app.services.parser as parser_module

        monkeypatch.setattr(parser_module, "MAX_PART_BYTES", 1024 * 1024)
        monkeypatch.setattr(parser_module, "MAX_EXPANDED_BYTES", 1024 * 1024)
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", WELL_FORMED_BODY)
            z.writestr("word/footnotes.xml", padded_part("footnotes", 768 * 1024))
            z.writestr("word/endnotes.xml", padded_part("endnotes", 768 * 1024))
        response = client.post("/api/upload", files={"file": ("bomb.docx", bomb.getvalue(), "")})
        assert response.status_code == 415

    def test_too_many_entries_is_refused(self, client, monkeypatch):
        import app.services.parser as parser_module

        monkeypatch.setattr(parser_module, "MAX_ZIP_ENTRIES", 20)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("word/document.xml", WELL_FORMED_BODY)
            for i in range(50):
                z.writestr(f"word/part{i}.xml", "<x/>")
        response = client.post("/api/upload", files={"file": ("many.docx", archive.getvalue(), "")})
        assert response.status_code == 415

    def test_xml_entity_declarations_are_refused(self, client):
        evil = (
            '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("word/document.xml", evil)
        response = client.post("/api/upload", files={"file": ("x.docx", buffer.getvalue(), "")})
        assert response.status_code == 415

    def test_a_damaged_pdf_gets_a_message_not_a_crash(self, client):
        response = client.post(
            "/api/upload", files={"file": ("bad.pdf", b"%PDF-1.4\nthis is not a pdf", "")}
        )
        assert response.status_code in (400, 415)
        assert response.json()["detail"]

    def test_empty_file_is_refused(self, client):
        assert client.post("/api/upload", files={"file": ("e.txt", b"", "")}).status_code == 400

    def test_detect_format_is_stable_for_text_with_a_bom(self):
        assert detect_format("﻿Notes".encode(), "n.txt") == "txt"

    def test_unsupported_error_is_a_value_error(self):
        # Callers that only know about ValueError must still catch it.
        assert issubclass(UnsupportedDocumentError, ValueError)


class TestTypographicPunctuation:
    """An iPhone keyboard turns apostrophes and hyphens into curly quotes and en
    dashes, which defeated every pattern."""

    def test_every_replacement_is_one_character_so_offsets_stay_valid(self):
        for char, replacement in NORMALIZATION.items():
            assert len(char) == 1 and len(replacement) == 1

    def test_length_is_preserved(self):
        text = "GOV’T “quoted” GAO–16–552 here"
        assert len(normalize_text(text)) == len(text)

    def test_curly_and_dashes_become_plain(self):
        assert normalize_text("GOV’T GAO–16–552") == "GOV'T GAO-16-552"

    def test_a_citation_with_smart_punctuation_still_extracts(self):
        from app.services.extractor import CitationExtractor

        straight = CitationExtractor().extract_all("See Brandenburg v. Ohio, 395 U.S. 444 (1969).")
        curly = CitationExtractor().extract_all(
            "See Brandenburg v. Ohio, 395 U.S. 444–447 (1969)."
        )
        assert len(straight) == len(curly) == 1

    def test_normalisation_does_not_change_document_text_shown_to_the_user(self, client):
        original = "GOV’T report"
        upload = client.post(
            "/api/upload", files={"file": ("n.txt", original.encode(), "")}
        ).json()
        assert upload["full_text"] == original
