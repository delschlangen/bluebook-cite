"""What a suggestion may and may not contain.

A suggestion states only what the document says or what a looked-up record says. It never
holds an empty pair of brackets, two full stops in a row, a line break carried in from a PDF, or
a date nobody stated; and a citation with a part missing is not dressed as a finished one: it
has no closing full stop, and `missing` names what it lacks.
"""

import pytest

from app.models.citation import Citation, CitationStatus, CitationType
from app.services.bluebook_rules import BluebookFormatter, missing_fields
from app.services.extractor import CitationExtractor
from app.services.lookup_service import CitationCompleter

extractor = CitationExtractor()
formatter = BluebookFormatter()


def analysed(text):
    """Each citation with its suggestion, as the analysis endpoint builds them."""
    found = extractor.extract_all(text)
    for c in found:
        c.suggested_correction = formatter.format_citation(c)
    return found


DOCUMENT = (
    "The first decision is Smith v. Jones, 144 F.4th 98, which the second followed. See Doe v.\n"
    "Roe, 5 U.S. 137 (1803); Brown v. Board of Education; 42 U.S.C. § 1983; Wash. Rev. Code §\n"
    "7.48.330; Cal. Civ. Code § 3273.50 et seq. Source: https://example.org/a.html. Id. at 5.\n"
    "Erwin Chemerinsky, Constitutional Law: Principles and Policies (6th ed. 2019)."
)


class TestNothingMalformed:
    def test_no_suggestion_has_empty_brackets_doubled_full_stops_or_a_line_break(self):
        found = analysed(DOCUMENT)

        assert len(found) >= 8
        for c in found:
            for bad in ("()", "..", "\n", "  "):
                assert bad not in c.suggested_correction, (bad, c.suggested_correction)

    def test_a_case_with_a_reporter_but_no_year_prints_no_parenthetical(self):
        """ "NSSF v. James, 144 F.4th 98" has a volume, a reporter and a page and no court or
        year. It was suggested as "*NSSF v. James*, 144 F.4th 98 ()."."""
        (case,) = analysed("The Second Circuit's decision in NSSF v. James, 144 F.4th 98, upheld it.")

        assert case.suggested_correction == "*NSSF v. James*, 144 F.4th 98"
        assert case.status == CitationStatus.INCOMPLETE
        assert case.missing == ["court", "year"]

    def test_a_supreme_court_reporter_needs_a_year_but_no_court(self):
        (case,) = analysed("They rely on Brandenburg v. Ohio, 395 U.S. 444, throughout.")

        assert case.suggested_correction == "*Brandenburg v. Ohio*, 395 U.S. 444"
        assert case.missing == ["year"]

    def test_et_seq_is_not_followed_by_a_second_full_stop(self):
        statute = Citation(
            type=CitationType.STATUTE, status=CitationStatus.COMPLETE, raw_text="x", position_start=0,
            position_end=1, code="Cal. Civ. Code", section="3273.50 et seq.", year=2022,
        )
        assert formatter.format_citation(statute) == "Cal. Civ. Code § 3273.50 et seq. (2022)."
        statute.year = None
        assert formatter.format_citation(statute) == "Cal. Civ. Code § 3273.50 et seq."


class TestOneLine:
    """Reviewer F10: citations from PDFs carried raw line breaks into raw_text, the fields
    and the suggestion ("Civ. Code §\\n3273.50", "(2d\\nCir. 1972)")."""

    TEXT = (
        "As the court held in the first of the two appeals that term, Doe v.\nRoe, 456 F.2d 789, 791 (2d\n"
        "Cir. 1972), the rule is settled. See also Wash. Rev. Code §\n7.48.330 and https://example.org/a."
    )

    def test_raw_text_fields_and_suggestions_have_no_line_breaks(self):
        found = analysed(self.TEXT)

        assert [c.type.value for c in found] == ["case", "statute", "website"]
        for c in found:
            dumped = c.model_dump()
            for name, value in dumped.items():
                if isinstance(value, str):
                    assert "\n" not in value, (name, value)
            assert all("\n" not in p for p in (c.parties or []))
        assert found[0].raw_text == "Doe v. Roe, 456 F.2d 789, 791 (2d Cir. 1972)"
        assert found[0].court == "2d Cir."
        assert found[0].suggested_correction == "*Doe v. Roe*, 456 F.2d 789, 791 (2d Cir. 1972)."

    def test_the_positions_still_point_at_the_document_exactly(self):
        for c in analysed(self.TEXT):
            spanned = self.TEXT[c.position_start:c.position_end]
            assert " ".join(spanned.split()) == c.raw_text
            assert spanned == spanned.strip()


class TestMissingIsAccurate:
    @pytest.mark.parametrize(
        ("text", "status", "missing", "suggestion"),
        [
            ("See Brown v. Board of Education, 347 U.S. 483 (1954).", "complete", [],
             "*Brown v. Bd. of Educ.*, 347 U.S. 483 (1954)."),
            ("The court followed Brown v. Board of Education and stopped.", "incomplete",
             ["volume", "reporter", "page", "year"], "*Brown v. Bd. of Educ.*"),
            ("See 42 U.S.C. § 1983.", "complete", [], "42 U.S.C. § 1983."),
            ("Source: https://example.org/a.html.", "incomplete", ["title"], "https://example.org/a.html"),
        ],
    )
    def test_status_missing_and_suggestion_agree(self, text, status, missing, suggestion):
        (c,) = analysed(text)

        assert c.status.value == status
        assert c.missing == missing
        assert c.suggested_correction == suggestion
        # the finished shape, with each gap named, exactly when there is a gap
        assert (c.template is not None) == bool(missing)
        if missing:
            assert c.template.count("[") >= 1

    def test_a_complete_citation_ends_with_a_full_stop_and_an_incomplete_one_does_not(self):
        for c in analysed(DOCUMENT):
            if c.is_short_form or c.kind:
                continue
            assert c.suggested_correction.endswith(".") == (c.status == CitationStatus.COMPLETE), c.suggested_correction
            assert bool(c.missing) == (c.status != CitationStatus.COMPLETE)

    def test_missing_is_brought_up_to_date_when_a_lookup_fills_a_gap(self):
        (case,) = analysed("The court followed Brown v. Board of Education and stopped.")
        assert case.missing == ["volume", "reporter", "page", "year"]

        case.volume, case.reporter, case.page = "347", "U.S.", "483"
        assert formatter.format_citation(case) == "*Brown v. Bd. of Educ.*, 347 U.S. 483"
        assert case.missing == ["year"]
        assert case.template == "*Brown v. Bd. of Educ.*, 347 U.S. 483 ([year])."

        case.year = 1954
        assert formatter.format_citation(case) == "*Brown v. Bd. of Educ.*, 347 U.S. 483 (1954)."
        assert case.missing == [] and case.template is None

    def test_a_case_cited_by_docket_needs_a_court_and_a_date_not_a_volume(self):
        case = Citation(
            type=CitationType.CASE, status=CitationStatus.INCOMPLETE, raw_text="x", position_start=0,
            position_end=1, parties=["Arnold", "Kotek"], docket_number="S071885", court="Or. Sup. Ct.",
        )
        assert missing_fields(case) == ["date"]
        assert formatter.format_citation(case) == "*Arnold v. Kotek*, No. S071885 (Or. Sup. Ct.)"
        assert case.template == "*Arnold v. Kotek*, No. S071885 (Or. Sup. Ct. [date of decision])."


class TestTheDateOfAWebPage:
    """A looked-up page's PUBLICATION date was stored as the day the author visited it and
    printed as "(last visited 2004-09-10)": a statement nobody made."""

    def _page(self):
        return Citation(
            type=CitationType.WEBSITE, status=CitationStatus.INCOMPLETE, raw_text="https://example.org/a",
            position_start=0, position_end=21, url="https://example.org/a",
        )

    def test_a_looked_up_publication_date_is_not_an_access_date(self):
        data = {
            "title": "Gun Maker Settles Suit", "author": "Jane Roe", "publication_date": "2004-09-10",
            "site_name": "Example Sun", "url": "https://example.org/a",
        }
        page = CitationCompleter(lookup_service=None)._merge_lookup_data(self._page(), data)

        assert page.access_date is None
        assert page.publication_date == "2004-09-10"
        suggestion = formatter.format_citation(page)
        assert "last visited" not in suggestion
        # Rule 18.2.2: Author, Title, Site (Mon. D, YYYY), URL.
        assert suggestion == "Jane Roe, *Gun Maker Settles Suit*, EXAMPLE SUN (Sept. 10, 2004), https://example.org/a."
        assert formatter.format_citation(page, is_law_review=False) == (
            "Jane Roe, *Gun Maker Settles Suit*, Example Sun (Sept. 10, 2004), https://example.org/a."
        )

    def test_a_host_name_is_not_printed_as_the_name_of_a_site(self):
        data = {"title": "A Page", "publication_date": "2004-09-10", "site_name": "example.org"}
        page = CitationCompleter(lookup_service=None)._merge_lookup_data(self._page(), data)

        assert formatter.format_citation(page) == "*A Page* (Sept. 10, 2004), https://example.org/a."

    def test_last_visited_is_printed_when_the_document_says_so(self):
        (page,) = [c for c in analysed("Jane Roe, A Page, https://example.org/a (last visited Mar. 3, 2024).")
                   if c.type.value == "website"]

        assert page.suggested_correction == "https://example.org/a (last visited Mar. 3, 2024)"
        page.title = "A Page"
        assert formatter.format_citation(page) == "*A Page*, https://example.org/a (last visited Mar. 3, 2024)."
