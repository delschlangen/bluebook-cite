"""What follows a case name: the forms a case citation takes.

One real paper cited about a hundred pending or unreported cases in the order filings are
listed, "Name, Court (No. X)"; every one was reported as a bare name. A reviewer found the
ordinary forms of a brief unparsed as well: "F. App'x", "n.4" pin cites, parallel citations,
"Wash. 2d", WL citations, subsequent history, "In re" names, and the reporter short form.
"""

import time

import pytest

from app.services.bluebook_rules import BluebookFormatter
from app.services.extractor import CitationExtractor

extractor = CitationExtractor()
formatter = BluebookFormatter()


def cases(text):
    found = [c for c in extractor.extract_all(text) if c.type.value == "case"]
    for c in found:
        c.suggested_correction = formatter.format_citation(c)
    return found


def one(text):
    found = cases(text)
    assert len(found) == 1, [c.raw_text for c in found]
    return found[0]


# (the citation as written, court, docket number, the suggestion)
DOCKET_STYLE = [
    ("Birdt v. L.A. Sheriff's Dept., 9th Cir. (No. 12-55115)", "9th Cir.", "12-55115",
     "*Birdt v. L.A. Sheriff's Dept.*, No. 12-55115 (9th Cir.)"),
    ("NSSF v. Platkin, D.N.J. (No. 3:22-cv-06646-ZNQ)", "D.N.J.", "3:22-cv-06646-ZNQ",
     "*NSSF v. Platkin*, No. 3:22-cv-06646-ZNQ (D.N.J.)"),
    ("District of Columbia v. Heller, U.S. Sup. Ct. (No. 07-290)", "U.S. Sup. Ct.", "07-290",
     "*District of Columbia v. Heller*, No. 07-290 (U.S. Sup. Ct.)"),
    ("Gun Owners of Vermont v. Birmingham, Vt. Super. Ct., Windham Unit (No. 315-8-18)",
     "Vt. Super. Ct., Windham Unit", "315-8-18",
     "*Gun Owners of Vermont v. Birmingham*, No. 315-8-18 (Vt. Super. Ct., Windham Unit)"),
    ("State v. Misch, Vt. Super. Ct., Bennington Crim. Div. (No. 173-2-19)", "Vt. Super. Ct., Bennington Crim. Div.",
     "173-2-19", "*State v. Misch*, No. 173-2-19 (Vt. Super. Ct., Bennington Crim. Div.)"),
    ("City of Chicago v. Westforth Sports, Ill. App. Ct., 1st Dist. (No. 1-23-1908)", "Ill. App. Ct., 1st Dist.",
     "1-23-1908", "*City of Chicago v. Westforth Sports*, No. 1-23-1908 (Ill. App. Ct., 1st Dist.)"),
    ("NYSRPA v. Bruen, U.S. (No. 20-843)", "U.S.", "20-843", "*NYSRPA v. Bruen*, No. 20-843 (U.S.)"),
    ("Arnold v. Kotek, Or. Sup. Ct. (No. S071885)", "Or. Sup. Ct.", "S071885", "*Arnold v. Kotek*, No. S071885 (Or. Sup. Ct.)"),
    ("Guedes v. ATF, D.C. Cir. (No. 21-5045)", "D.C. Cir.", "21-5045", "*Guedes v. ATF*, No. 21-5045 (D.C. Cir.)"),
    ("NSSF v. Ferguson, E.D. Wash. (No. 2:23-cv-00113)", "E.D. Wash.", "2:23-cv-00113",
     "*NSSF v. Ferguson*, No. 2:23-cv-00113 (E.D. Wash.)"),
    ("Hanson v. District of Columbia, D.D.C. (No. 22-cv-2256)", "D.D.C.", "22-cv-2256",
     "*Hanson v. District of Columbia*, No. 22-cv-2256 (D.D.C.)"),
    ("Modern Sportsman v. U.S., Fed. Cir. (No. 20-1107)", "Fed. Cir.", "20-1107",
     "*Modern Sportsman v. United States*, No. 20-1107 (Fed. Cir.)"),
    ("Armstrong v. City of Philadelphia, Pa. Sup. Ct. (No. 81 EAL 2022)", "Pa. Sup. Ct.", "81 EAL 2022",
     "*Armstrong v. City of Philadelphia*, No. 81 EAL 2022 (Pa. Sup. Ct.)"),
    # several docket numbers, and words after the number that are not part of it
    ("Colorado Outfitters Ass'n v. Hickenlooper, 10th Cir. (Nos. 14-1290, 14-1292)", "10th Cir.", "14-1290, 14-1292",
     "*Colorado Outfitters Ass'n v. Hickenlooper*, Nos. 14-1290, 14-1292 (10th Cir.)"),
    ("Antonyuk v. Nigrelli, 2d Cir. (Nos. 22-2908(L)/22-2972)", "2d Cir.", "22-2908(L)/22-2972",
     "*Antonyuk v. Nigrelli*, Nos. 22-2908(L)/22-2972 (2d Cir.)"),
    ("We The Patriots v. Grisham, 10th Cir. (Nos. 23-2166, -2167, -2185)", "10th Cir.", "23-2166, -2167, -2185",
     "*We The Patriots v. Grisham*, Nos. 23-2166, -2167, -2185 (10th Cir.)"),
    ("Teixeira v. County of Alameda, 9th Cir. (No. 13-17132, panel stage)", "9th Cir.", "13-17132",
     "*Teixeira v. Cnty. of Alameda*, No. 13-17132 (9th Cir.)"),
    ("RMGO v. Hickenlooper, Colo. Ct. App. (appeal from Denver Dist. Ct. No. 2013CV33879)", "Colo. Ct. App.",
     "2013CV33879", "*RMGO v. Hickenlooper*, No. 2013CV33879 (Colo. Ct. App.)"),
    # no court at all
    ("Woollard v. Gallagher (No. 12-1437)", None, "12-1437", "*Woollard v. Gallagher*, No. 12-1437"),
]


class TestACaseCitedByItsDocket:
    @pytest.mark.parametrize(("citation", "court", "docket", "suggestion"), DOCKET_STYLE, ids=[d[0][:45] for d in DOCKET_STYLE])
    def test_court_and_docket_are_fields_and_the_suggestion_is_in_rule_10_8_1_order(self, citation, court, docket, suggestion):
        text = f"The groups filed a joint amicus brief, {citation}. The brief is short."
        case = one(text)

        assert text[case.position_start:case.position_end] == citation
        assert (case.court, case.docket_number) == (court, docket)
        # no date is in the document, so none is printed, no empty brackets stand in for it,
        # and the citation is not presented as finished
        assert case.suggested_correction == suggestion
        assert case.status.value == "incomplete"
        assert "date" in case.missing
        assert "[date of decision]" in case.template

    def test_the_bluebooks_own_order_with_a_date_is_complete(self):
        text = "See Smith v. Jones, No. 19-cv-1234, 2020 WL 1234567, at *3 (S.D.N.Y. Mar. 3, 2020)."
        case = one(text)

        assert (case.docket_number, case.court, case.year, case.decision_date) == ("19-cv-1234", "S.D.N.Y.", 2020, "Mar. 3, 2020")
        assert (case.volume, case.reporter, case.page, case.pincite) == ("2020", "WL", "1234567", "at *3")
        assert case.status.value == "complete"
        assert case.suggested_correction == "*Smith v. Jones*, No. 19-cv-1234, 2020 WL 1234567, at *3 (S.D.N.Y. Mar. 3, 2020)."

    def test_a_docket_number_with_no_parenthetical(self):
        case = one("The companion case is Richards v. Prieto, No. 11-16255) in the same court.")

        assert case.raw_text == "Richards v. Prieto, No. 11-16255"
        assert case.docket_number == "11-16255"
        assert case.missing == ["court", "date"]

    def test_a_court_with_no_docket_number(self):
        text = "The merit brief was filed in Klein v. Leis, Ohio Sup. Ct.\nIt argues the point."
        case = one(text)

        assert text[case.position_start:case.position_end] == "Klein v. Leis, Ohio Sup. Ct."
        assert case.court == "Ohio Sup. Ct."
        assert case.suggested_correction == "*Klein v. Leis* (Ohio Sup. Ct.)"
        assert case.missing == ["volume", "reporter", "page", "year"]

    def test_a_citation_wrapped_by_a_pdf_keeps_its_court_and_docket(self):
        text = "The first joint brief of that year was filed in the appeal, NSSF v. Ferguson, E.D.\nWash. (No.\n2:23-cv-00113)."
        case = one(text)

        assert (case.court, case.docket_number) == ("E.D. Wash.", "2:23-cv-00113")
        assert "\n" not in case.raw_text + case.suggested_correction

    def test_a_year_alone_after_the_name(self):
        case = one("The agency was quoting Jacobson v. Massachusetts (1905) in its defence.")

        assert case.raw_text == "Jacobson v. Massachusetts (1905)"
        assert case.year == 1905
        assert case.suggested_correction == "*Jacobson v. Massachusetts* (1905)"
        assert case.missing == ["volume", "reporter", "page"]

    def test_a_remark_in_brackets_is_not_a_court_and_year(self):
        case = one("They cite Smith v. Jones (decided in 1990 by a divided court) twice.")

        assert case.raw_text == "Smith v. Jones"
        assert case.year is None and case.court is None


# (text, expected fields, suggestion)
REPORTER_FORMS = [
    ("Hernandez v. Acme Corp., 700 F. App'x 12, 14 (2d Cir. 2017).",
     dict(volume="700", reporter="F. App'x", page="12", pincite="14", court="2d Cir.", year=2017),
     "*Hernandez v. Acme Corp.*, 700 F. App'x 12, 14 (2d Cir. 2017)."),
    ("United States v. Carolene Products Co., 304 U.S. 144, 152 n.4 (1938).",
     dict(volume="304", reporter="U.S.", page="144", pincite="152 n.4", year=1938),
     "*United States v. Carolene Prods. Co.*, 304 U.S. 144, 152 n.4 (1938)."),
    ("Doe v. Roe, 1 F.4th 2, 5 & n.3 (5th Cir. 2021).",
     dict(pincite="5 & n.3", court="5th Cir.", year=2021), "*Doe v. Roe*, 1 F.4th 2, 5 & n.3 (5th Cir. 2021)."),
    ("Roe v. Wade, 410 U.S. 113, 153, 93 S. Ct. 705, 727 (1973).",
     dict(volume="410", page="113", pincite="153", parallel_citations=["93 S. Ct. 705, 727"], year=1973),
     "*Roe v. Wade*, 410 U.S. 113, 153, 93 S. Ct. 705, 727 (1973)."),
    ("State v. Hernandez, 123 Wash. 2d 456, 460, 868 P.2d 1234 (1994).",
     dict(volume="123", reporter="Wash. 2d", page="456", pincite="460", parallel_citations=["868 P.2d 1234"], year=1994),
     "*State v. Hernandez*, 123 Wash. 2d 456, 460, 868 P.2d 1234 (1994)."),
    ("People v. Smith, 5 Cal. 4th 100 (1993).", dict(reporter="Cal. 4th", page="100", year=1993),
     "*People v. Smith*, 5 Cal. 4th 100 (1993)."),
    ("Doe v. Roe, 100 N.E.3d 5 (Ill. 2018).", dict(reporter="N.E.3d", court="Ill.", year=2018),
     "*Doe v. Roe*, 100 N.E.3d 5 (Ill. 2018)."),
    ("Doe v. Roe, 2020 WL 7654321, at *2 (N.D. Cal. 2020).",
     dict(volume="2020", reporter="WL", page="7654321", pincite="at *2", court="N.D. Cal.", year=2020),
     "*Doe v. Roe*, 2020 WL 7654321, at *2 (N.D. Cal. 2020)."),
    ("Marbury v. Madison, 5 U.S. (1 Cranch) 137, 177 (1803).",
     dict(volume="5", reporter="U.S. (1 Cranch)", page="137", pincite="177", year=1803),
     "*Marbury v. Madison*, 5 U.S. (1 Cranch) 137, 177 (1803)."),
    ("Skidmore v. Swift & Co., 323 U.S. 134, 140 (1944).", dict(pincite="140", year=1944),
     "*Skidmore v. Swift & Co.*, 323 U.S. 134, 140 (1944)."),
]


class TestReporterForms:
    @pytest.mark.parametrize(("text", "fields", "suggestion"), REPORTER_FORMS, ids=[r[0][:40] for r in REPORTER_FORMS])
    def test_the_ordinary_forms_of_a_brief(self, text, fields, suggestion):
        case = one("The point is settled. " + text)

        for name, value in fields.items():
            assert getattr(case, name) == value, name
        assert case.status.value == "complete"
        assert case.suggested_correction == suggestion
        assert case.raw_text == text[:-1]

    def test_subsequent_history_stays_with_its_citation(self):
        text = (
            "Nat'l Shooting Sports Found., Inc. v. James, 144 F.4th 98 (2d Cir. 2025), cert. denied, No. 25-1026\n"
            "(U.S. June 15, 2026)."
        )
        case = one(text)

        assert case.position_end == len(text) - 1
        assert case.subsequent_history == "cert. denied, No. 25-1026 (U.S. June 15, 2026)"
        assert case.suggested_correction == (
            "*Nat'l Shooting Sports Found., Inc. v. James*, 144 F.4th 98 (2d Cir. 2025), "
            "*cert. denied*, No. 25-1026 (U.S. June 15, 2026)."
        )

    def test_history_to_a_reporter(self):
        case = one("Smith v. Jones, 5 F.3d 1 (9th Cir. 1993), aff'd, 600 U.S. 1 (1995).")
        assert case.suggested_correction == "*Smith v. Jones*, 5 F.3d 1 (9th Cir. 1993), *aff'd*, 600 U.S. 1 (1995)."

    def test_a_volume_and_reporter_with_the_page_still_blank(self):
        case = one("Roe v. Wade, 410 U.S. ___ (1973).")

        assert (case.volume, case.reporter, case.page, case.year) == ("410", "U.S.", None, 1973)
        assert case.missing == ["page"]
        assert case.suggested_correction == "*Roe v. Wade*, 410 U.S. ___ (1973)"

    def test_no_comma_and_no_full_stops_is_still_a_reporter_citation(self):
        case = one("Brandenburg v Ohio 395 US 444")
        assert (case.volume, case.reporter, case.page) == ("395", "US", "444")


class TestWithoutAV:
    def test_the_reporter_short_form(self):
        text = "The see-cite is Bruen, 597 U.S. at 29 n.7, whose quoted matter is short."
        case = one(text)

        assert text[case.position_start:case.position_end] == "Bruen, 597 U.S. at 29 n.7"
        assert case.is_short_form and case.short_form_type == "short_case"
        assert (case.parties, case.volume, case.reporter, case.pincite) == (["Bruen"], "597", "U.S.", "29 n.7")
        assert case.suggested_correction == "*Bruen*, 597 U.S. at 29 n.7."

    def test_a_short_form_with_no_name_in_front_of_it(self):
        case = one("As the Court said in 1954, 347 U.S. at 495, separate is not equal.")

        assert case.raw_text == "347 U.S. at 495"
        assert case.parties is None

    def test_a_count_of_years_is_not_a_reporter(self):
        assert cases("He served 10 Years at 2 prisons and scored 3 Goals at 90 minutes.") == []

    @pytest.mark.parametrize(
        ("text", "name", "suggestion"),
        [
            ("See In re Winship, 397 U.S. 358, 364 (1970).", "In re Winship", "*In re Winship*, 397 U.S. 358, 364 (1970)."),
            ("See Ex parte Young, 209 U.S. 123 (1908).", "Ex parte Young", "*Ex parte Young*, 209 U.S. 123 (1908)."),
            ("The rule of In re Gault is settled.", "In re Gault", "*In re Gault*"),
        ],
    )
    def test_procedural_names(self, text, name, suggestion):
        case = one(text)

        assert case.parties == [name]
        assert case.suggested_correction == suggestion

    def test_matter_of_in_a_sentence_is_not_a_case(self):
        assert cases("As a matter of law it holds. Matter of fact, it does not.") == []


class TestId:
    @pytest.mark.parametrize(
        ("text", "span", "pin"),
        [
            ("Id. at 177.", "Id. at 177", "177"),
            ("Id. at 29 n.7.", "Id. at 29 n.7", "29 n.7"),
            ("Id. at 842-43, 850.", "Id. at 842-43, 850", "842-43, 850"),
            ("Id. § 7903(5)(A)(iii)", "Id. § 7903(5)(A)(iii)", "§ 7903(5)(A)(iii)"),
            ("Id. §§ 7901-7903.", "Id. §§ 7901-7903", "§§ 7901-7903"),
            ("Id.", "Id.", None),
        ],
    )
    def test_id_keeps_what_it_points_at(self, text, span, pin):
        (found,) = extractor.extract_all(text)

        assert found.short_form_type == "id"
        assert (found.raw_text, found.pincite) == (span, pin)


@pytest.mark.parametrize(
    "flood",
    [
        "A v. B, 9th Cir. (No. 12-55115). " * 900,
        "A v. B, No. 1" + "-1" * 14_000,
        "A v. B (Nos. " + "1-1, " * 6000,
        "A v. B, " + "Vt. Super. Ct., " * 1800,
        "A v. B, 1 U.S. 1" + ", 1" * 9000,
        "A v. B, 1 U.S. 1" + ", 1 U.S. 1" * 2900,
        "A v. B, 1 " + "F. " * 9000,
        "1 U.S. at 1 " * 2500,
        "1 " + "Ab. " * 7000,
        "In re " * 5000,
        "In re A, 1 U.S. 1 (1990). " * 1100,
        "Id. at 1, " * 3000,
        "A v. B, 1 U.S. 1 (1990), cert. denied, " * 700,
        "A v. B (" + "a " * 14_000,
    ],
    ids=["docket-style", "docket-hyphens", "docket-list", "courts", "pins", "parallel", "reporter-words", "short-forms",
         "number-then-words", "in-re", "in-re-cites", "id-pins", "history", "open-paren"],
)
def test_tails_are_read_in_linear_time(flood):
    started = time.perf_counter()
    extractor.extract_all(flood[:30_000])
    assert time.perf_counter() - started < 2.0
