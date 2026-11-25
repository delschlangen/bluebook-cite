"""An incomplete case citation keeps the whole of each party's name.

`case_incomplete` ended with a negative lookahead that refused a reporter citation after the
second party. When that lookahead failed the regular expression did not give up: it gave back one
letter of the name at a time until the lookahead passed, so

    Roe v. Wade, 410 U.S. ___ (1973)        was reported as   Roe v. Wad
    Marbury v. Madison, 5 U.S. (1 Cranch) 137  as            Marbury v. Madiso

and the outside lookup searched for a case that does not exist. Two reviewers noticed it
independently, in the original code as well as the new. A page of long-document results made it
worse, because every such citation was also sent for lookup under its damaged name.
"""

import pytest

from app.services.extractor import CitationExtractor, read_party_right
from app.utils import bluebook_patterns as bp

extractor = CitationExtractor()


def _cases(text):
    return [c for c in extractor.extract_all(text) if c.type.value == "case"]


class TestPartyNamesAreWhole:
    @pytest.mark.parametrize(
        ("text", "first", "second"),
        [
            ("Roe v. Wade, 410 U.S. ___ (1973).", "Roe", "Wade"),
            ("Marbury v. Madison, 5 U.S. (1 Cranch) 137, 177 (1803).", "Marbury", "Madison"),
            ("Alpha v. Delta, 5 U.S. ___ (1999).", "Alpha", "Delta"),
            ("See Gibbons v. Ogden, 22 U.S. (9 Wheat.) 1 (1824).", "Gibbons", "Ogden"),
            ("Smith v. Jones, 5 U.S.", "Smith", "Jones"),
            ("Brown v. Board of Education, 347 U.S. ___ (1954).", "Brown", "Board of Education"),
            ("Smith v. Jones, Inc., 5 U.S. ___ (1999).", "Smith", "Jones, Inc."),
            ("Smith v. Jones, 12 F.4th ___ (9th Cir. 2022).", "Smith", "Jones"),
        ],
    )
    def test_the_last_letter_of_the_second_name_is_kept(self, text, first, second):
        cases = _cases(text)

        assert len(cases) == 1, [(c.parties, c.raw_text) for c in cases]
        assert cases[0].parties == [first, second]
        # The name is whole. (What follows it used to be left out of the citation, because a
        # blank page number and an early reporter's name in brackets were not understood; they
        # are now, so the citation runs on past the name. See tests/test_case_forms.py.)
        assert cases[0].raw_text.startswith(f"{first} v. {second}")
        assert not cases[0].raw_text.startswith(f"{first} v. {second}".rstrip() + "x")

    def test_a_name_followed_by_a_comma_and_a_reporter_is_not_cut_at_every_letter(self):
        """The old lookahead made the engine back off letter by letter. A name is no longer
        matched by a pattern at all: it is read word by word and ends at the comma, so there is
        no shorter name for anything to fall back to."""
        text = "Roe v. Wade, 410 U.S. ___ (1973)."
        anchor = bp.V_ANCHOR.search(text)

        assert anchor is not None
        end, _ = read_party_right(text, anchor.end())
        assert text[anchor.end():end].strip() == "Wade"

    def test_complete_citations_are_unchanged(self):
        cases = _cases("Brown v. Board of Education, 347 U.S. 483 (1954).")

        assert len(cases) == 1
        assert cases[0].status.value == "complete"
        assert cases[0].parties == ["Brown", "Board of Education"]

    def test_two_incomplete_citations_in_a_row_are_both_whole(self):
        cases = _cases("Roe v. Wade, 410 U.S. ___ (1973). Doe v. Bolton, 410 U.S. ___ (1973).")

        assert [c.parties for c in cases] == [["Roe", "Wade"], ["Doe", "Bolton"]]
