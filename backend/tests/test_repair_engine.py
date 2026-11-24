"""Tests for the engine wired into the repair endpoint and the document pipeline."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.services.bluebook_rules import BluebookFormatter
from app.services.extractor import CitationExtractor
from app.utils.rules import VERIFIED_RULES
from tests.docfactory import make_docx

# The citation a user pasted from an iPhone: curly apostrophe, en dashes, and a title
# that capitalises "With" and "The". Both forms below are the sourced ones (AALL 2025).
GAO_PASTE = (
    "U.S. GOV’T ACCOUNTABILITY OFF., GAO–16–552, Firearms Data: "
    "ATF Did Not Always Comply With The Appropriations Act Restrictions (2016)"
)
GAO_LAW_REVIEW = (
    "U.S. GOV'T ACCOUNTABILITY OFF., GAO-16-552, FIREARMS DATA: ATF DID NOT ALWAYS "
    "COMPLY WITH THE APPROPRIATIONS ACT RESTRICTIONS (2016)."
)
GAO_PRACTITIONER = (
    "U.S. Gov't Accountability Off., GAO-16-552, *Firearms Data: ATF Did Not Always "
    "Comply with the Appropriations Act Restrictions* (2016)."
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def repair(client, text, style=None):
    body = {"text": text} if style is None else {"text": text, "style": style}
    response = client.post("/api/repair", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestTheGaoReportThatWasRejected:
    """A real user pasted this and was told it was not a citation."""

    def test_law_review_style(self, client):
        result = repair(client, GAO_PASTE, "law_review")
        assert result["status"] == "resolved"
        assert result["kind"] == "agency_report"
        assert result["formatted"] == GAO_LAW_REVIEW

    def test_practitioner_style_lowercases_with_and_the(self, client):
        result = repair(client, GAO_PASTE, "practitioner")
        assert result["formatted"] == GAO_PRACTITIONER

    def test_default_style_is_law_review(self, client):
        assert repair(client, GAO_PASTE)["formatted"] == GAO_LAW_REVIEW
        assert repair(client, GAO_PASTE)["style"] == "law_review"

    def test_it_is_not_misread_as_a_book(self, client):
        """With a year, the older book pattern also matches this text, with the author
        cut down to 'T ACCOUNTABILITY OFF.'. The reading that explains more wins."""
        assert repair(client, GAO_PASTE)["kind"] == "agency_report"
        books = CitationExtractor().extract_all(GAO_PASTE, include_spec=False)
        assert any(c.type.value == "book" for c in books), "the premise of this test has changed"

    def test_correcting_the_corrected_citation_changes_nothing(self, client):
        again = repair(client, GAO_PRACTITIONER, "practitioner")
        assert again["formatted"] == GAO_PRACTITIONER

    def test_no_outside_lookup_is_made(self, client):
        """respx with no routes: any HTTP request would raise, so a resolved result
        proves none was attempted."""
        with respx.mock(assert_all_called=False) as mock:
            assert repair(client, GAO_PASTE)["status"] == "resolved"
        assert mock.calls.call_count == 0


class TestIncompleteCitationsShowTheirShapeAndRule:
    def test_cfr_without_a_year_is_incomplete_unlike_the_us_code(self, client):
        result = repair(client, "47 CFR 54.101")
        assert result["status"] == "incomplete"
        assert result["formatted"] is None
        assert result["missing"] == ["year"]
        assert result["template"] == "47 C.F.R. § 54.101 ([year])."
        assert result["missing_details"][0]["display_rule"] == {
            "number": "14.2",
            "title": "Rules, Regulations, and Other Publications",
        }
        assert result["rule_note"], "the edition caveat accompanies any rule shown"

    def test_a_bare_report_number_asks_for_everything_else(self, client):
        result = repair(client, "GAO-16-552")
        assert result["kind"] == "agency_report"
        assert result["missing"] == ["author", "title", "year"]
        assert result["template"] == "[agency], GAO-16-552, [title] ([year])."

    def test_every_displayed_rule_is_verified(self, client):
        for text in ["47 CFR 54.101", "GAO-16-552", "82 Fed. Reg. 8977", "Executive Order 13769",
                     "H.R. 1234, 117th Cong.", "123 Cong. Rec. 12455", "UCC § 2-314",
                     "Moody v. NetChoice"]:
            for detail in repair(client, text)["missing_details"]:
                shown = detail["display_rule"]
                assert shown is not None, f"{text}: {detail['field']} has no verified rule"
                assert shown["number"] in VERIFIED_RULES

    def test_lower_confidence_formats_say_so(self, client):
        result = repair(client, "U.S. Const. art. I, § 8, cl. 3")
        assert result["format_confidence"] == "high"
        medium = repair(client, "Restatement (Second) of Torts § 402A (Am. L. Inst. 1965)")
        assert medium["format_confidence"] == "medium"
        assert any("Confirm it in your Bluebook" in n for n in medium["notes"])


class TestStyleParameter:
    def test_an_unknown_style_is_refused(self, client):
        response = client.post("/api/repair", json={"text": "x", "style": "bogus"})
        assert response.status_code == 422

    def test_restatement_follows_the_style(self, client):
        text = "Restatement (Second) of Torts § 402A (Am. L. Inst. 1965)"
        assert repair(client, text, "law_review")["formatted"].startswith("RESTATEMENT (SECOND) OF TORTS")
        assert repair(client, text, "practitioner")["formatted"].startswith("Restatement (Second) of Torts")


class TestUnrecognisedInput:
    def test_prose_is_not_forced_into_a_type(self, client):
        result = repair(client, "I need a citation about free speech")
        assert result["status"] == "unparseable"
        assert result["formatted"] is None
        assert "kind of source" in result["notes"][0]

    def test_a_case_is_still_handled_by_the_case_reader(self, client):
        result = repair(client, "Brandenburg v. Ohio, 395 U.S. 444 (1969)")
        assert result["status"] == "resolved"
        assert result["kind"] is None
        assert result["formatted"] == "*Brandenburg v. Ohio*, 395 U.S. 444 (1969)."


class TestDocumentAnalysis:
    DOC = (
        "The agency acted under 47 C.F.R. § 54.101 (2022). "
        "Congress had considered H.R. 1234, 117th Cong. (2021). "
        "See also 47 CFR 54.202."
    )

    def analyse(self, client, text):
        response = client.post(
            "/api/analyze", json={"document_id": "t", "text": text, "filename": "t.txt"}
        )
        assert response.status_code == 200, response.text
        return response.json()

    def test_engine_kinds_are_found_with_their_corrections(self, client):
        citations = self.analyse(client, self.DOC)["analysis"]["citations"]
        kinds = [c["kind"] for c in citations]
        assert kinds == ["cfr", "bill", "cfr"]
        assert citations[0]["suggested_correction"] == "47 C.F.R. § 54.101 (2022)."
        assert citations[1]["suggested_correction"] == "H.R. 1234, 117th Cong. (2021)."

    def test_an_incomplete_one_is_flagged_not_silently_completed(self, client):
        incomplete = self.analyse(client, self.DOC)["analysis"]["citations"][2]
        assert incomplete["status"] == "incomplete"
        assert incomplete["missing"] == ["year"]
        assert incomplete["template"] == "47 C.F.R. § 54.202 ([year])."

    def test_engine_kinds_are_never_sent_to_an_outside_search(self, client):
        """A C.F.R. cite searched against a case or article database can only return
        noise. respx with no routes would raise on any request."""
        with respx.mock(assert_all_called=False) as mock:
            analysis = self.analyse(client, self.DOC)
        assert analysis["stats"]["total_citations"] == 3
        # A failed lookup is swallowed by design, so the result alone cannot show that
        # none was tried. Counting the requests can.
        assert mock.calls.call_count == 0

    def test_the_response_carries_the_new_fields(self, client):
        citation = self.analyse(client, self.DOC)["analysis"]["citations"][0]
        for key in ("kind", "kind_label", "spec_fields", "missing", "format_confidence"):
            assert key in citation

    def test_a_citation_in_a_word_footnote_is_found_with_its_real_number(self, client):
        doc = make_docx(
            [("Firearms data matter.", [31])],
            footnotes={31: "See U.S. GOV’T ACCOUNTABILITY OFF., GAO–16–552, Firearms Data (2016)."},
        )
        upload = client.post("/api/upload", files={"file": ("a.docx", doc, "")}).json()
        citations = self.analyse(client, upload["full_text"])["analysis"]["citations"]
        (report,) = [c for c in citations if c["kind"] == "agency_report"]
        assert report["footnote_number"] == 1
        assert report["suggested_correction"] == (
            "U.S. GOV'T ACCOUNTABILITY OFF., GAO-16-552, FIREARMS DATA (2016)."
        )


class TestBooksAndArticlesWereFixedToMatchTheSources:
    fm = BluebookFormatter()
    ex = CitationExtractor()

    def fmt(self, text, law_review=True):
        return self.fm.format_citation(self.ex.extract_all(text)[0], law_review)

    def test_a_second_author_is_never_silently_dropped(self):
        """The pattern lacked '&', so the first author vanished and the book was
        attributed to the second author alone."""
        text = "Roy M. Mersky & Donald J. Dunn, Fundamentals of Legal Research 120 (8th ed. 2002)"
        assert self.fmt(text) == (
            "ROY M. MERSKY & DONALD J. DUNN, FUNDAMENTALS OF LEGAL RESEARCH 120 (8th ed. 2002)."
        )
        assert self.fmt(text, False) == (
            "Roy M. Mersky & Donald J. Dunn, *Fundamentals of Legal Research* 120 (8th ed. 2002)."
        )

    def test_a_pinpoint_is_not_italicised_or_capitalised_with_the_title(self):
        text = "Erwin Chemerinsky, Constitutional Law: Principles and Policies § 11.2 (6th ed. 2019)"
        assert self.fmt(text, False) == (
            "Erwin Chemerinsky, *Constitutional Law: Principles and Policies* § 11.2 (6th ed. 2019)."
        )

    def test_an_edition_uses_the_bluebook_ordinals(self):
        text = "Jane Roe, Some Legal Treatise (2nd ed. 2010)"
        assert "(2d ed. 2010)" in self.fmt(text)

    def test_an_article_has_a_comma_after_its_title_and_a_capitalised_journal(self):
        text = "Charles A. Reich, The New Property, 73 Yale L.J. 733, 737-38 (1964)"
        assert self.fmt(text) == "Charles A. Reich, *The New Property*, 73 YALE L.J. 733, 737-38 (1964)."
        assert self.fmt(text, False) == "Charles A. Reich, *The New Property*, 73 Yale L.J. 733, 737-38 (1964)."


class TestSharedEngineInstance:
    def test_the_engine_knows_every_transform_its_spec_uses(self):
        import re

        from app.services.citation_engine import ENGINE
        from app.services.spec_engine import TRANSFORMS

        for spec in ENGINE.spec["types"]:
            for template in spec["templates"].values():
                for m in re.finditer(r"\{\w+((?:\|\w+)*)\}", template):
                    for name in filter(None, m.group(1).split("|")):
                        assert name in TRANSFORMS

    def test_a_failed_outside_lookup_cannot_fail_an_engine_kind(self, client):
        with respx.mock:
            respx.route().mock(side_effect=httpx.ConnectError("down"))
            assert repair(client, GAO_PASTE)["status"] == "resolved"
