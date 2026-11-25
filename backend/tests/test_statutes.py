"""Statutes: every subsection, ranges and lists, every state's code, session laws.

A string cite of eleven state statutes and session laws in one real paper produced five
citations, each wrong: the state was dropped ("Civ. Code § 3273.50"), a range stopped at its
first number, the year and publisher were ignored, whole families of codes were not known, and
one statute was reported as a book and set in capitals. A reviewer found the same on an ordinary
brief ("5 U.S.C. §§ 701–706" became "5 U.S.C. § 701.", marked complete).
"""

import time

import pytest

from app.services.bluebook_rules import BluebookFormatter
from app.services.extractor import CitationExtractor
from app.utils.bluebook_patterns import STATE_ABBREVIATIONS, STATE_CODES

extractor = CitationExtractor()
formatter = BluebookFormatter()


def statutes(text):
    return [c for c in extractor.extract_all(text) if c.type.value == "statute"]


def one(text):
    found = statutes(text)
    assert len(found) == 1, [c.raw_text for c in found]
    return found[0]


class TestFederal:
    @pytest.mark.parametrize(
        ("text", "section", "suggestion"),
        [
            ("See 18 U.S.C. § 922(g)(1).", "922(g)(1)", "18 U.S.C. § 922(g)(1)."),
            ("See 5 U.S.C. §§ 701–706.", "701–706", "5 U.S.C. §§ 701–706."),
            ("See 5 U.S.C. §§ 551-559 (2018).", "551-559", "5 U.S.C. §§ 551-559 (2018)."),
            ("See 28 U.S.C. §§ 1331, 1346(a)(2) (2018).", "1331, 1346(a)(2)", "28 U.S.C. §§ 1331, 1346(a)(2) (2018)."),
            ("See 5 U.S.C. § 553(b)–(c).", "553(b)–(c)", "5 U.S.C. § 553(b)–(c)."),
            ("See 42 U.S.C. § 2000e-2(a).", "2000e-2(a)", "42 U.S.C. § 2000e-2(a)."),
            ("See 15 U.S.C. §§ 78a et seq.", "78a et seq.", "15 U.S.C. § 78a et seq."),
            # "§§" in front of a single section is a slip, and is corrected
            ("See 47 U.S.C. §§ 230.", "230", "47 U.S.C. § 230."),
            ("See 18\nU.S.C. § 922(g)(3), which", "922(g)(3)", "18 U.S.C. § 922(g)(3)."),
        ],
    )
    def test_every_subsection_range_and_list_is_kept(self, text, section, suggestion):
        statute = one(text)

        assert (statute.title_number, statute.code, statute.section) == (text.split()[1], "U.S.C.", section)
        assert statute.status.value == "complete"
        assert formatter.format_citation(statute) == suggestion

    def test_the_span_is_the_whole_citation(self):
        text = "Compare 5 U.S.C. §§ 701–706 with 28 U.S.C. §§ 1331, 1346(a)(2) (2018), and 47 U.S.C. § 230(c)(1)."
        assert [text[c.position_start:c.position_end] for c in statutes(text)] == [
            "5 U.S.C. §§ 701–706", "28 U.S.C. §§ 1331, 1346(a)(2) (2018)", "47 U.S.C. § 230(c)(1)",
        ]

    def test_a_list_does_not_run_on_into_the_next_citation(self):
        text = "See 42 U.S.C. § 1983, 28 U.S.C. § 1331, and 5 years of practice."
        assert [c.section for c in statutes(text)] == ["1983", "1331"]

    def test_a_bare_section_sign_has_no_code_to_be_cited_to(self):
        assert statutes("The brief defends § 922(g)(9) and says § 898 is clear.") == []


# The eleven of the string cite, and the other families named in the report.
STATE_FORMS = [
    ("N.Y. Gen. Bus. Law §§ 898-a to 898-e (McKinney 2021)",
     dict(code="N.Y. Gen. Bus. Law", section="898-a to 898-e", year=2021, publisher="McKinney")),
    ("N.J. Stat. Ann. §§ 2C:58-33 to -35 (West 2022)",
     dict(code="N.J. Stat. Ann.", section="2C:58-33 to -35", year=2022, publisher="West")),
    ("Del. Code Ann. tit. 10, § 3930 (2022)", dict(code="Del. Code Ann.", title_number="10", section="3930", year=2022)),
    ("Cal. Civ. Code § 3273.50 et seq. (2022)", dict(code="Cal. Civ. Code", section="3273.50 et seq.", year=2022)),
    ("815 Ill. Comp. Stat. 505/2DDDD (2023)",
     dict(code="Ill. Comp. Stat.", title_number="815", section="505/2DDDD", year=2023)),
    ("Wash. Rev. Code § 7.48.330 (2023)", dict(code="Wash. Rev. Code", section="7.48.330", year=2023)),
    ("Colo. Rev. Stat. §§ 6-27-101 to -106 (2023)", dict(code="Colo. Rev. Stat.", section="6-27-101 to -106", year=2023)),
    ("Md. Code Ann., Cts. & Jud. Proc. §§ 3-2501 to 3-2504 (2024)",
     dict(code="Md. Code Ann., Cts. & Jud. Proc.", section="3-2501 to 3-2504", year=2024)),
    ("Va. Code Ann. §§ 59.1-148.5 to -148.8 (2026)", dict(code="Va. Code Ann.", section="59.1-148.5 to -148.8", year=2026)),
    ("Fla. Stat. § 790.065(13) (2023)", dict(code="Fla. Stat.", section="790.065(13)", year=2023)),
    ("Mass. Gen. Laws ch. 140, § 131 (2022)", dict(code="Mass. Gen. Laws", title_number="140", section="131", year=2022)),
    ("Tex. Penal Code Ann. § 46.02 (West 2021)", dict(code="Tex. Penal Code Ann.", section="46.02", year=2021, publisher="West")),
    ("42 Pa. Cons. Stat. § 9711 (2021)", dict(code="Pa. Cons. Stat.", title_number="42", section="9711", year=2021)),
    ("Ohio Rev. Code Ann. § 2923.12 (West 2021)",
     dict(code="Ohio Rev. Code Ann.", section="2923.12", year=2021, publisher="West")),
    ("Cal. Penal Code § 187(a) (West 2020)", dict(code="Cal. Penal Code", section="187(a)", year=2020, publisher="West")),
    ("Cal. Bus. & Prof. Code § 17200 (West 2020)",
     dict(code="Cal. Bus. & Prof. Code", section="17200", year=2020, publisher="West")),
    ("N.Y. Penal Law § 125.25 (McKinney 2021)", dict(code="N.Y. Penal Law", section="125.25", year=2021, publisher="McKinney")),
    ("Vt. Stat. Ann. tit. 13, § 4021 (2019)", dict(code="Vt. Stat. Ann.", title_number="13", section="4021", year=2019)),
    ("Me. Rev. Stat. Ann. tit. 17-A, § 201 (2021)", dict(code="Me. Rev. Stat. Ann.", title_number="17-A", section="201", year=2021)),
    ("Okla. Stat. tit. 21, § 701.7 (2021)", dict(code="Okla. Stat.", title_number="21", section="701.7", year=2021)),
    ("720 Ill. Comp. Stat. Ann. 5/9-1 (West 2021)",
     dict(code="Ill. Comp. Stat. Ann.", title_number="720", section="5/9-1", year=2021, publisher="West")),
    ("W. Va. Code § 61-2-1 (2020)", dict(code="W. Va. Code", section="61-2-1", year=2020)),
    ("D.C. Code § 22-2101 (2021)", dict(code="D.C. Code", section="22-2101", year=2021)),
    ("N.H. Rev. Stat. Ann. § 630:1 (2021)", dict(code="N.H. Rev. Stat. Ann.", section="630:1", year=2021)),
    ("Conn. Gen. Stat. § 53a-54a (2021)", dict(code="Conn. Gen. Stat.", section="53a-54a", year=2021)),
]


class TestStateCodes:
    @pytest.mark.parametrize(("citation", "fields"), STATE_FORMS, ids=[c[:40] for c, _ in STATE_FORMS])
    def test_code_section_year_and_publisher_are_read_and_the_citation_comes_back_whole(self, citation, fields):
        text = f"The duty is statutory. See {citation}; it is recent."
        statute = one(text)

        assert text[statute.position_start:statute.position_end] == citation
        for name, value in fields.items():
            assert getattr(statute, name) == value, name
        assert statute.status.value == "complete" and statute.missing == []
        # what the document says, in the order its form requires: nothing added, nothing lost
        assert formatter.format_citation(statute) == citation + "."

    def test_each_element_of_a_string_cite_is_its_own_citation(self):
        text = "See " + "; ".join(c for c, _ in STATE_FORMS[:9]) + "."
        found = statutes(text)

        assert [text[c.position_start:c.position_end] for c in found] == [c for c, _ in STATE_FORMS[:9]]

    def test_a_citation_broken_over_lines_by_a_pdf_is_read_and_printed_on_one(self):
        text = "The first of them is N.J.\nStat. Ann. §§ 2C:58-33 to -35 (West 2022); the next is Cal. Civ. Code §\n3273.50 et seq. (2022)."
        first, second = statutes(text)

        assert (first.code, first.section) == ("N.J. Stat. Ann.", "2C:58-33 to -35")
        assert formatter.format_citation(first) == "N.J. Stat. Ann. §§ 2C:58-33 to -35 (West 2022)."
        assert formatter.format_citation(second) == "Cal. Civ. Code § 3273.50 et seq. (2022)."
        assert "\n" not in first.raw_text + second.raw_text

    def test_a_state_code_without_its_year_is_incomplete_and_says_so(self):
        statute = one("The ban is Fla. Stat. § 790.065(13), enacted in 2018.")

        assert statute.status.value == "incomplete"
        assert statute.missing == ["year"]
        assert formatter.format_citation(statute) == "Fla. Stat. § 790.065(13)"
        assert statute.template == "Fla. Stat. § 790.065(13) ([year])."

    def test_an_explanatory_parenthetical_is_not_the_year(self):
        text = "See Va. Code Ann. §§ 59.1-148.5 to -148.8 (2026) (effective July 1, 2026)."
        statute = one(text)

        assert text[statute.position_start:statute.position_end] == "Va. Code Ann. §§ 59.1-148.5 to -148.8 (2026)"

    def test_every_state_and_the_district_has_a_code_that_is_recognised(self):
        assert set(STATE_CODES) == set(STATE_ABBREVIATIONS.values())
        for state, names in STATE_CODES.items():
            for name in names:
                written = name.replace("{title} ", "42 ").replace("{subject}", "Penal")
                if "Ill." in name:
                    text = f"See {written} 505/2 (2020)."
                else:
                    text = f"See {written} § 12-345 (2020)."
                statute = one(text)
                assert statute.code == written.replace("42 ", ""), (state, name)
                assert statute.year == 2020

    def test_the_ohio_style_is_read_and_written_as_the_bluebook_names_the_code(self):
        statute = one('The heading reads "R.C. 2923.12 By Regulating Concealed Weapons, Is Reasonable."')

        assert statute.raw_text == "R.C. 2923.12"
        assert (statute.code, statute.section) == ("Ohio Rev. Code Ann.", "2923.12")
        assert formatter.format_citation(statute) == "Ohio Rev. Code Ann. § 2923.12"
        assert statute.missing == ["year"]

    def test_a_code_the_table_does_not_know_is_reported_as_written_for_checking(self):
        statute = one("San Francisco's ordinance, Police Code § 4512, is a storage law.")

        assert statute.status.value == "needs_verification"
        assert formatter.format_citation(statute) == "Police Code § 4512"


class TestSessionLaws:
    def test_a_state_session_law_with_the_code_section_it_became(self):
        text = "See 2023 Haw. Sess. Laws Act 28 (codified at Haw. Rev. Stat.\nch. 134, pt. VI); it is new."
        law = one(text)

        assert (law.year, law.code, law.page) == (2023, "Haw. Sess. Laws", "Act 28")
        assert law.parallel_citations == ["Haw. Rev. Stat. ch. 134, pt. VI"]
        assert formatter.format_citation(law) == "2023 Haw. Sess. Laws Act 28 (codified at Haw. Rev. Stat. ch. 134, pt. VI)."

    def test_a_public_act_by_number(self):
        text = "See 2025 Conn. Pub. Acts No.\n25-43 (effective Oct. 1, 2025)."
        law = one(text)

        assert text[law.position_start:law.position_end] == "2025 Conn. Pub. Acts No.\n25-43"
        assert formatter.format_citation(law) == "2025 Conn. Pub. Acts No. 25-43."

    @pytest.mark.parametrize(
        "citation",
        ["2011 Tex. Gen. Laws 123", "2013 Colo. Sess. Laws 1234", "2005 Alaska Sess. Laws ch. 5", "2012 Cal. Stat. 1234",
         "2011 Vt. Acts & Resolves 123", "2021 N.Y. Laws 237"],
    )
    def test_other_states_forms(self, citation):
        assert formatter.format_citation(one(f"See {citation}.")) == citation + "."

    def test_the_federal_forms_still_work(self):
        (law,) = extractor.extract_all("See Pub. L. No. 111-148, 124 Stat. 119 (2010).")
        assert law.kind == "public_law"
        assert formatter.format_citation(law) == "Pub. L. No. 111-148, 124 Stat. 119 (2010)."

    def test_a_public_law_cited_to_a_section_is_one_citation_not_its_codification(self):
        """Reviewer F8: this was reduced to "15 U.S.C. § 9001"."""
        text = "See Pub. L. No. 116-136, § 2102, 134 Stat. 281, 313 (2020) (codified at 15 U.S.C. § 9001)."
        law = one(text)

        assert formatter.format_citation(law) == text[4:]
        assert (law.section, law.volume, law.page, law.pincite, law.year) == ("2102", "134", "281", "313", 2020)


class TestAStatuteIsNeverABook:
    """The book pattern is "Author, Title (Year)" and takes almost anything with a comma and a
    year, so statutes are tried first and what it calls the author is checked."""

    def test_a_state_statute_with_a_comma_in_its_name_is_a_statute(self):
        text = "See Md. Code Ann., Cts. & Jud. Proc. §§ 3-2501 to 3-2504 (2024)."
        (found,) = extractor.extract_all(text)

        assert found.type.value == "statute"
        assert formatter.format_citation(found) == "Md. Code Ann., Cts. & Jud. Proc. §§ 3-2501 to 3-2504 (2024)."

    @pytest.mark.parametrize(
        "text",
        [
            "Some Unknown Code Ann., Div. of Things §§ 1 to 5 (2024).",
            "Xyz. Rev. Stat., Part Two of the Third Schedule (2020).",
            "12 F.3d 345, Something Else Entirely (1994).",
        ],
    )
    def test_an_author_may_not_be_a_code_a_reporter_or_hold_a_section_sign(self, text):
        assert [c for c in extractor.extract_all(text) if c.type.value == "book"] == []

    def test_a_committee_print_described_in_prose_is_legislative_material_as_written(self):
        """It was a "book" whose author began with the sentence's first words, in capitals."""
        text = (
            'This is from the witness statement in the U.S. Senate Judiciary Committee, Subcommittee on the '
            'Constitution report, "The Right to Keep and Bear Arms" (1982).'
        )
        (found,) = extractor.extract_all(text)

        assert found.type.value == "legislative"
        assert found.status.value == "incomplete" and found.missing == ["congress"]
        assert text[found.position_start:].startswith("U.S. Senate Judiciary Committee")
        assert formatter.format_citation(found) == text[found.position_start:found.position_end]

    def test_real_books_are_still_books_and_lose_the_prose_in_front_of_them(self):
        text = "For the standard account see Erwin Chemerinsky, Constitutional Law: Principles and Policies (6th ed. 2019)."
        (book,) = extractor.extract_all(text)

        assert book.type.value == "book"
        assert book.author == "Erwin Chemerinsky"
        assert formatter.format_citation(book) == "ERWIN CHEMERINSKY, CONSTITUTIONAL LAW: PRINCIPLES AND POLICIES (6th ed. 2019)."

    def test_a_book_with_a_pinpoint_to_a_section_is_still_a_book(self):
        (book,) = extractor.extract_all("Erwin Chemerinsky, Constitutional Law: Principles and Policies § 11.2 (6th ed. 2019)")
        assert book.type.value == "book"


@pytest.mark.parametrize(
    "flood",
    [
        "§ " * 15_000,
        "Cal. Civ. Code § 1 " * 1500,
        "N.Y. Gen. Bus. Law §§ 898-a to 898-e (McKinney 2021); " * 500,
        "Del. Code Ann. tit. 10, § 3930 (2022); " * 700,
        "Cal. " + "Abc. " * 6000 + "Code § 1",
        "42 U.S.C. §§ " + "1, " * 10_000,
        "42 U.S.C. §§ 1" + "-1" * 15_000,
        "42 U.S.C. § 1" + "(a)" * 10_000,
        "815 Ill. Comp. Stat. 505/2 " * 1000,
        "R.C. 2923.12 " * 2000,
        "2023 Haw. Sess. Laws Act 28 (codified at Haw. Rev. Stat. ch. 134) " * 400,
        "2023 " * 6000,
        "Pub. L. No. 116-136, § 2102, 134 Stat. 281 " * 600,
    ],
    ids=["signs", "state", "ranges", "titles", "subject-run", "list", "hyphens", "subsections", "illinois", "local",
         "session", "years", "public-law"],
)
def test_statutes_are_read_in_linear_time(flood):
    started = time.perf_counter()
    extractor.extract_all(flood[:30_000])
    assert time.perf_counter() - started < 2.0
