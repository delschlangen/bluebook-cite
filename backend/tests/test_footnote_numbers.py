"""A note's number belongs to the note, not to everything after it.

In one real paper the reader marked only notes 1 and 2, on the first page. Every one of the 300
citations after them, in 56 pages of body text, was reported as "note 2": the number was carried
forward until the next marker, however far away. A note now runs from its marker to the next
marker or the next blank line, whichever comes first.

The layouts below are the two the readers produce. The PDF reader writes each page's lines one
to a line with the notes at the foot of the page and a blank line between pages. The Word reader
writes the body's blocks with blank lines between them, then the footnotes one to a line, then
the endnotes one to a line ("[^e3]").
"""

from app.services.context_analyzer import DocumentContextAnalyzer
from app.services.extractor import CitationExtractor

extractor = CitationExtractor()


def notes(text):
    return [(c.raw_text.split(",")[0], c.footnote_number, c.note_type) for c in extractor.extract_all(text)]


PDF_LAYOUT = (
    "The first page cites nothing in its body text at all.\n"
    "[^1] Roe v. Wade, 410 U.S. 113 (1973); Doe v. Bolton, 410 U.S. 179 (1973).\n"
    "[^2] Brown v. Board of Education, 347 U.S. 483 (1954), which\n"
    "runs on to a second line. See also Miranda v. Arizona, 384 U.S. 436 (1966).\n"
    "\n"
    "The second page discusses Gideon v. Wainwright, 372 U.S. 335 (1963), in its body.\n"
    "A later paragraph turns to Mapp v. Ohio, 367 U.S. 643 (1961).\n"
    "\n"
    "The third page has Terry v. Ohio, 392 U.S. 1 (1968).\n"
    "[^3] Katz v. United States, 389 U.S. 347 (1967).\n"
)


class TestWhereANoteEnds:
    def test_a_number_is_not_carried_past_the_blank_line_that_ends_the_page(self):
        assert notes(PDF_LAYOUT) == [
            ("Roe v. Wade", 1, "footnote"),
            ("Doe v. Bolton", 1, "footnote"),
            ("Brown v. Board of Education", 2, "footnote"),
            ("Miranda v. Arizona", 2, "footnote"),      # the note's own second line
            ("Gideon v. Wainwright", None, None),       # body text of the next page
            ("Mapp v. Ohio", None, None),
            ("Terry v. Ohio", None, None),
            ("Katz v. United States", 3, "footnote"),
        ]

    def test_three_hundred_citations_after_the_last_marker_are_not_all_in_it(self):
        body = "".join(f"Entry {n} relies on Alpha{n} v. Beta{n}, {n} U.S. {n} (1990).\n\n" for n in range(1, 301))
        text = "Opening text.\n[^1] Roe v. Wade, 410 U.S. 113 (1973).\n[^2] Doe v. Bolton, 410 U.S. 179 (1973).\n\n" + body
        found = extractor.extract_all(text)

        assert [c.footnote_number for c in found[:2]] == [1, 2]
        assert len(found) == 302
        assert all(c.footnote_number is None for c in found[2:])

    def test_the_next_marker_ends_a_note_too(self):
        text = "[^7] Roe v. Wade, 410 U.S. 113 (1973).\n[^8] Doe v. Bolton, 410 U.S. 179 (1973)."
        assert [n for _, n, _ in notes(text)] == [7, 8]

    def test_lines_that_only_look_like_notes_follow_the_same_rule(self):
        """No markers from a reader: a line that begins with a number is taken for a note."""
        text = (
            "12 See Roe v. Wade, 410 U.S. 113 (1973).\n"
            "13. Doe v. Bolton, 410 U.S. 179 (1973).\n"
            "\n"
            "The next page begins with Gideon v. Wainwright, 372 U.S. 335 (1963).\n"
        )
        assert [n for _, n, _ in notes(text)] == [12, 13, None]

    def test_text_with_no_notes_has_no_note_numbers(self):
        assert [n for _, n, _ in notes("See Roe v. Wade, 410 U.S. 113 (1973).\n\nAnd Doe v. Bolton.")] == [None, None]


WORD_LAYOUT = (
    "The body cites Gideon v. Wainwright, 372 U.S. 335 (1963), in its first paragraph.\n"
    "\n"
    "Its second paragraph cites nothing.\n"
    "\n"
    "[^1] Roe v. Wade, 410 U.S. 113 (1973).\n"
    "[^2] Doe v. Bolton, 410 U.S. 179 (1973).\n"
    "\n"
    "[^e1] Smith v. Jones, 1 U.S. 1 (1990).\n"
    "[^e2] Smith v. Jones, 1 U.S. 1 (1990)."
)


class TestFootnotesAndEndnotes:
    """A Word file numbers its footnotes and its endnotes separately, so each has a note 1.
    Both were reported as footnote 1 and shared one history (reviewer F11)."""

    def test_the_two_kinds_are_told_apart(self):
        assert notes(WORD_LAYOUT) == [
            ("Gideon v. Wainwright", None, None),
            ("Roe v. Wade", 1, "footnote"),
            ("Doe v. Bolton", 2, "footnote"),
            ("Smith v. Jones", 1, "endnote"),
            ("Smith v. Jones", 2, "endnote"),
        ]

    def test_id_is_judged_within_one_kind_of_note(self):
        """Endnote 2 repeats the only source in endnote 1, so "Id." is right. Counted together
        with footnote 1 the "previous note" held two sources and Id. was refused."""
        suggestions = DocumentContextAnalyzer().analyze_citation_sequence(extractor.extract_all(WORD_LAYOUT))

        last = suggestions[-1]
        assert last["footnote_number"] == 2
        assert last["short_form_type"] == "id"

    def test_a_footnote_does_not_take_id_from_the_endnote_with_the_number_before_it(self):
        text = (
            "Body text.\n\n"
            "[^1] Roe v. Wade, 410 U.S. 113 (1973).\n"
            "[^2] Smith v. Jones, 1 U.S. 1 (1990).\n"
            "\n"
            "[^e1] Smith v. Jones, 1 U.S. 1 (1990)."
        )
        suggestions = DocumentContextAnalyzer().analyze_citation_sequence(extractor.extract_all(text))

        # footnote 2 follows footnote 1 (Roe), not endnote 1 (Smith): no Id.
        assert suggestions[1]["short_form_type"] == "full"
        assert suggestions[2]["short_form_type"] == "short_case"
