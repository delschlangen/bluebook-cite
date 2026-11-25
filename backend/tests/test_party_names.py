"""A case name is the two party names and nothing else.

The party pattern used to be "any run of up to eight words that starts with a capital". On a
real 58-page paper that produced a wrong span for 117 of 121 case citations: the prose in front
of the name, the prose behind it, the sentence's own full stop and the first word of the next
line were all read as parts of a party. A name is now read word by word (extractor.py, "Party
names"); every row below is a shape that went wrong, in a sentence written for the test.
"""

import time

import pytest

from app.services.bluebook_rules import BluebookFormatter
from app.services.extractor import CitationExtractor, read_party_left, read_party_right
from app.utils import bluebook_patterns as bp

extractor = CitationExtractor()
formatter = BluebookFormatter()


def cases(text):
    return [c for c in extractor.extract_all(text) if c.type.value == "case"]


# (sentence, [(the text of the name, [first party, second party]), ...])
PROSE_AROUND_THE_NAME = [
    # prose in front: a court, a document, a person, a verb
    (
        "The Ninth Circuit in National Rifle Association v. Bondi explained why.",
        [("National Rifle Association v. Bondi", ["National Rifle Association", "Bondi"])],
    ),
    (
        "A press statement on McDonald v. City of Chicago went out that night.",
        [("McDonald v. City of Chicago", ["McDonald", "City of Chicago"])],
    ),
    (
        "The agency, quoting Jacobson v. Massachusetts, defended the rule.",
        [("Jacobson v. Massachusetts", ["Jacobson", "Massachusetts"])],
    ),
    (
        "Mary Major on NYSRPA v. Bruen: the licensing rule was the target.",
        [("NYSRPA v. Bruen", ["NYSRPA", "Bruen"])],
    ),
    (
        "The Supreme Court's grant of certiorari in McDonald v. City of Chicago changed the plan.",
        [("McDonald v. City of Chicago", ["McDonald", "City of Chicago"])],
    ),
    # prose behind: a verb, a conjunction and a clause, a noun the name modifies
    (
        "The ban in District of Columbia v. Heller was struck down.",
        [("District of Columbia v. Heller", ["District of Columbia", "Heller"])],
    ),
    (
        "They cite United States v. Miller and arguing the point further would not help.",
        [("United States v. Miller", ["United States", "Miller"])],
    ),
    (
        "The test comes from the Arnold v. Cleveland framework. In its own voice the brief says more.",
        [("Arnold v. Cleveland", ["Arnold", "Cleveland"])],
    ),
    # a possessive place or court in front of the name is prose
    (
        "The brief applies Colorado's Robertson v. Denver standard. Heading III says so.",
        [("Robertson v. Denver", ["Robertson", "Denver"])],
    ),
    (
        "Under Ohio's Arnold v. Cleveland test the ordinance stands.",
        [("Arnold v. Cleveland", ["Arnold", "Cleveland"])],
    ),
    (
        "The Court's Heller v. District of Columbia ruling came later.",
        [("Heller v. District of Columbia", ["Heller", "District of Columbia"])],
    ),
    (
        "Justice Blackmun's Roe v. Wade opinion is long.",
        [("Roe v. Wade", ["Roe", "Wade"])],
    ),
    # the sentence's own full stop is not part of the name
    (
        "The release was about United States v. Rahimi.",
        [("United States v. Rahimi", ["United States", "Rahimi"])],
    ),
    (
        "It was filed as Brady Campaign v. Brownback. The complaint is long.",
        [("Brady Campaign v. Brownback", ["Brady Campaign", "Brownback"])],
    ),
    # ...and the first word of the next line is not the second party
    (
        "This followed the grant of review in McDonald v. City of Chicago.\nSource: the court's docket.",
        [("McDonald v. City of Chicago", ["McDonald", "City of Chicago"])],
    ),
    # an abbreviation that ends a sentence, then a new sentence
    (
        "The first was Smith v. Acme Corp. The court then turned to damages.",
        [("Smith v. Acme Corp.", ["Smith", "Acme Corp."])],
    ),
    (
        "In Miranda v. Arizona Justice Harlan dissented.",
        [("Miranda v. Arizona", ["Miranda", "Arizona"])],
    ),
    # two cases joined by a conjunction share out the words between the two "v."
    (
        "The brief was filed in NRA v. Oak Park & McDonald v. City of Chicago, both in 2009.",
        [
            ("NRA v. Oak Park", ["NRA", "Oak Park"]),
            ("McDonald v. City of Chicago", ["McDonald", "City of Chicago"]),
        ],
    ),
    (
        "Compare Roe v. Wade and Planned Parenthood v. Casey, which differ.",
        [("Roe v. Wade", ["Roe", "Wade"]), ("Planned Parenthood v. Casey", ["Planned Parenthood", "Casey"])],
    ),
    # a complaint's title after the name
    (
        "On January 22: City of Rochester v. Smith & Wesson Brands, Inc., First Amended Complaint.",
        [("City of Rochester v. Smith & Wesson Brands, Inc.", ["City of Rochester", "Smith & Wesson Brands, Inc."])],
    ),
]


@pytest.mark.parametrize(("text", "expected"), PROSE_AROUND_THE_NAME, ids=[t[0][:50] for t in PROSE_AROUND_THE_NAME])
def test_the_name_is_the_two_parties_and_nothing_else(text, expected):
    found = cases(text)

    assert [c.parties for c in found] == [parties for _, parties in expected]
    for case, (name, _) in zip(found, expected, strict=True):
        # the citation begins where the name begins, and nothing but the name comes before "v."
        assert text[case.position_start:].startswith(name)
        assert formatter.format_citation(case).startswith("*")


# Names that must be found whole. Each is a real caption (or a real short name of one).
WHOLE_NAMES = [
    ("Brown", "Board of Education"),
    ("Planned Parenthood of Southeastern Pa.", "Casey"),
    ("Students for Fair Admissions, Inc.", "President & Fellows of Harvard College"),
    ("Church of the Lukumi Babalu Aye, Inc.", "City of Hialeah"),
    ("United States ex rel. Schutte", "SuperValu Inc."),
    ("Friends of the Earth, Inc.", "Laidlaw Environmental Services (TOC), Inc."),
    ("Citizens for a Better Environment", "Gorsuch"),
    ("Committee on Children's Television, Inc.", "General Foods Corp."),
    ("Firearm Owners Against Crime", "City of Harrisburg"),
    ("Libertarian Party of Erie County", "Cuomo"),
    ("Fiscal", "City and County of San Francisco"),
    ("We The Patriots", "Grisham"),
    ("3M Co.", "Browning"),
    ("White", "U.S."),
    ("State", "Weber"),
    ("People", "Aguilar"),
    ("Commonwealth", "Depina"),
    ("NYSRPA", "Bruen"),
    ("VanDerStok", "Garland"),
    ("Kolbe", "O'Malley"),
    # more of the same kinds
    ("Mayor and City Council of Baltimore and State of Maryland", "Glock, Inc."),
    ("Nat'l Shooting Sports Found., Inc.", "James"),
    ("Chevron U.S.A., Inc.", "Natural Resources Defense Council, Inc."),
    ("Motor Vehicle Mfrs. Ass'n", "State Farm Mut. Auto. Ins. Co."),
    ("Alaska Dep't of Envtl. Conservation", "EPA"),
    ("Univ. of Tex. Sw. Med. Ctr.", "Nassar"),
    ("Texas Dep't of Hous. & Cmty. Affairs", "Inclusive Cmtys. Project, Inc."),
    ("Goldman Sachs & Co.", "Smith"),
    ("Nat'l Fed'n of Indep. Bus.", "Sebelius"),
    ("Minnesota Mining & Manufacturing Co.", "Johnson"),
    ("Vt. Federation of Sportsmen's Clubs", "Birmingham"),
    ("Birdt", "L.A. Sheriff's Dept."),
    ("Children's Hospital", "Smith"),
    ("Skidmore", "Swift & Co."),
    ("NLRB", "Jones & Laughlin Steel Corp."),
    ("Citizens to Preserve Overton Park, Inc.", "Volpe"),
    ("Coalition on Homelessness", "City and County of San Francisco"),
    ("Hernandez", "de la Cruz"),
    ("Treasury Employees", "Von Raab"),
    ("eBay Inc.", "MercExchange, L.L.C."),
    ("Colorado Outfitters Ass'n", "Hickenlooper"),
    ("Gun Owners of Vermont", "Birmingham"),
    ("Rocky Mountain Gun Owners", "Polis"),
    ("Modern Sportsman", "U.S."),
    ("Smith", "Glock Ges.m.b.H."),
    ("Veterans' Ass'n of Ohio", "Jones"),
]
FRAMES = [
    "{name}, 1 U.S. 1 (1990).",
    "The court held as follows. {name}, 1 F.3d 2, 3 (2d Cir. 1990).",
    "See {name}, 1 U.S. 1 (1990).",
    "The panel that decided {name} disagreed.",
    "It relied on {name}.",
    "(citing {name})",
]


@pytest.mark.parametrize(("first", "second"), WHOLE_NAMES, ids=[f"{a} v. {b}"[:60] for a, b in WHOLE_NAMES])
def test_a_real_name_is_found_whole_wherever_it_stands(first, second):
    name = f"{first} v. {second}"
    for frame in FRAMES:
        text = frame.format(name=name)
        found = cases(text)

        assert len(found) == 1, (text, [(c.parties, c.raw_text) for c in found])
        assert found[0].parties == [first, second], text
        assert text[found[0].position_start:].startswith(name), text


class TestCommasInsideAName:
    """Something in the cleaning code cut a name at its comma: "Nat'l Shooting Sports Found.,
    Inc. v. James" was reported with parties ["Inc.", "James"] and the suggestion "*Inc. v.
    James*" (a reviewer found the same on Chevron U.S.A., Inc.). It was the old rule that any
    word ending in a full stop and longer than four characters ended a sentence."""

    def test_an_abbreviation_before_the_comma_is_not_a_sentence_end(self):
        text = "Nat'l Shooting Sports Found., Inc. v. James, 144 F.4th 98 (2d Cir. 2025)."
        (case,) = cases(text)

        assert case.parties == ["Nat'l Shooting Sports Found., Inc.", "James"]
        assert formatter.format_citation(case).startswith("*Nat'l Shooting Sports Found., Inc. v. James*, 144 F.4th 98")

    def test_curly_apostrophes_make_no_difference(self):
        text = "Nat’l Shooting Sports Found., Inc. v. James, 144 F.4th 98 (2d Cir. 2025)."
        (case,) = cases(text)

        assert case.parties == ["Nat'l Shooting Sports Found., Inc.", "James"]

    def test_chevron(self):
        text = "Chevron U.S.A., Inc. v. Natural Resources Defense Council, Inc., 467 U.S. 837, 842-43 (1984)."
        (case,) = cases(text)

        assert case.parties == ["Chevron U.S.A., Inc.", "Natural Resources Defense Council, Inc."]
        assert formatter.format_citation(case) == (
            "*Chevron U.S.A., Inc. v. Natural Res. Defense Council, Inc.*, 467 U.S. 837, 842-43 (1984)."
        )

    def test_an_entity_suffix_is_a_whole_word(self):
        """ "Co" was tried as a prefix, so the court after the name gave the defendant a suffix:
        "RMGO v. Hickenlooper, Colo. Ct. App." became "Hickenlooper, Co"."""
        text = "The brief in RMGO v. Hickenlooper, Colo. Ct. App., was filed in June."
        (case,) = cases(text)

        assert case.parties == ["RMGO", "Hickenlooper"]

    @pytest.mark.parametrize("suffix", ["Inc.", "LLC", "L.L.C.", "Ltd.", "L.P.", "Corp.", "Co.", "N.A.", "P.C."])
    def test_a_comma_is_inside_the_name_only_before_a_suffix(self, suffix):
        (case,) = cases(f"See Acme, {suffix} v. Jones, Secretary of State, 1 U.S. 1 (1990).")

        assert case.parties == [f"Acme, {suffix}", "Jones"]


class TestWhereANameStops:
    def test_a_lower_case_word_ends_it_on_the_right_and_blocks_it_on_the_left(self):
        (case,) = cases("As the dissent in Roe v. Wade observed, the line is hard to draw.")
        assert case.parties == ["Roe", "Wade"]

    @pytest.mark.parametrize(
        ("text", "parties"),
        [
            ("the Second Circuit in Smith v. Jones", ["Smith", "Jones"]),       # "in" after a court
            ("a statement on Smith v. Jones", ["Smith", "Jones"]),              # "on" after a noun
            ("according to Smith v. Jones", ["Smith", "Jones"]),                # "to" after a verb
            ("the Committee on Smith v. Jones", ["Committee on Smith", "Jones"]),  # the stated limit of the rule
            ("Leadership Conference on Civil Rights v. Jones", ["Leadership Conference on Civil Rights", "Jones"]),
            ("People in Interest of A.B. v. Jones", ["People in Interest of A.B.", "Jones"]),
            ("Mothers against Drunk Driving v. Jones", ["Mothers against Drunk Driving", "Jones"]),
        ],
    )
    def test_on_in_to_and_against_belong_to_a_name_only_after_an_organisations_head_noun(self, text, parties):
        (case,) = cases(text + " the point was made.")
        assert case.parties == parties

    def test_a_connector_left_dangling_at_an_edge_is_dropped(self):
        (case,) = cases("This was the holding of the Smith v. Jones and of later cases.")
        assert case.parties == ["Smith", "Jones"]
        assert case.raw_text == "Smith v. Jones"

    def test_and_continues_a_name_only_if_a_name_word_follows(self):
        (one,) = cases("They cite Smith v. Jones and say no more.")
        (two,) = cases("They cite Smith v. Jones and Laughlin Steel Corp., which is longer.")

        assert one.parties == ["Smith", "Jones"]
        assert two.parties == ["Smith", "Jones and Laughlin Steel Corp."]

    @pytest.mark.parametrize("word", ["See", "In", "Under", "Compare", "But", "Cf.", "Following", "Unlike", "The"])
    def test_a_word_that_only_introduces_the_citation_is_not_its_first_word(self, word):
        text = f"{word} Smith v. Jones, 1 U.S. 1 (1990)."
        (case,) = cases(text)

        assert case.parties == ["Smith", "Jones"]
        assert text[case.position_start:].startswith("Smith")

    def test_a_token_ending_in_a_full_stop_that_is_not_an_abbreviation_ends_the_sentence(self):
        """Decided from the tables and the token's shape, not its length: "Ohio." and "Roe."
        end a sentence, "Indep." and "Envtl." do not."""
        assert [c.parties for c in cases("It happened in Ohio. Smith v. Jones was next.")] == [["Smith", "Jones"]]
        assert [c.parties for c in cases("It followed Roe. Smith v. Jones was next.")] == [["Smith", "Jones"]]
        assert bp.is_abbreviation("Indep.") and bp.is_abbreviation("Envtl.") and bp.is_abbreviation("Cmtys.")
        assert bp.is_abbreviation("U.S.A.") and bp.is_abbreviation("Ges.m.b.H.") and bp.is_abbreviation("J.")
        assert not bp.is_abbreviation("Ohio.") and not bp.is_abbreviation("Roe.") and not bp.is_abbreviation("Rahimi.")

    def test_a_case_caption_is_not_a_citation(self):
        assert cases("JOHN SMITH,\nPlaintiff,\nv.\nACME CORP.,\nDefendant.") == []


class TestLineBreaks:
    """A PDF's layout leaves a line break wherever a line was full, including inside a name."""

    @pytest.mark.parametrize(
        ("text", "parties"),
        [
            ("The first amicus brief of that term was filed in District of\nColumbia v. Heller, and it was long.",
             ["District of Columbia", "Heller"]),
            ("The joint brief of the three groups was filed in Hanson\nv. District of Columbia, and it was short.",
             ["Hanson", "District of Columbia"]),
            ("The brief was filed in the appeal that is called McDonald v.\nCity of Chicago, and it was short.",
             ["McDonald", "City of Chicago"]),
            ("The brief was filed in the appeal that is called Fiscal v. City and County of San\nFrancisco, and lost.",
             ["Fiscal", "City and County of San Francisco"]),
        ],
    )
    def test_a_name_may_run_over_one_line_break_and_its_fields_have_single_spaces(self, text, parties):
        (case,) = cases(text)

        assert case.parties == parties
        assert "\n" not in formatter.format_citation(case)

    def test_a_short_line_was_not_wrapped_so_the_name_does_not_cross_it(self):
        text = "Background\nSmith v. Jones\nAnalysis follows in the next part."
        (case,) = cases(text)

        assert case.parties == ["Smith", "Jones"]
        assert text[case.position_start:case.position_end] == "Smith v. Jones"

    def test_a_name_never_crosses_a_blank_line(self):
        text = "The appeal was decided on the papers and the opinion was short, as in Alpha\n\nBeta v. Gamma Delta\n\nEpsilon"
        (case,) = cases(text)

        assert case.parties == ["Beta", "Gamma Delta"]

    def test_a_page_break_beside_the_v_leaves_both_names_whole(self):
        text = "As the Court explained in New York Times Co. v.\n\nSullivan, 376 U.S. 254, 270 (1964), the rule is settled."
        (case,) = cases(text)

        assert case.parties == ["New York Times Co.", "Sullivan"]
        assert case.volume == "376"


class TestBounds:
    def test_a_name_longer_than_eight_words_keeps_its_start(self):
        text = "The suit is Mayor and City Council of Baltimore and State of Maryland v. Glock, Inc., filed last year."
        (case,) = cases(text)

        assert case.parties[0] == "Mayor and City Council of Baltimore and State of Maryland"

    def test_the_readers_are_exposed_for_the_tests_and_return_offsets(self):
        text = "See Brown v. Board of Education, 347 U.S. 483 (1954)."
        anchor = bp.V_ANCHOR.search(text)

        assert text[read_party_left(text, anchor.start()):anchor.start()].strip() == "Brown"
        end, another_case_follows = read_party_right(text, anchor.end())
        assert text[anchor.end():end].strip() == "Board of Education"
        assert another_case_follows is False

    @pytest.mark.parametrize(
        "flood",
        [
            "A v. " * 6000,
            "Alpha Beta Gamma Delta " * 1500 + "v. " + "Alpha Beta Gamma Delta " * 1500,
            ("Alpha of the Beta and " * 8 + "v. ") * 400,
            ("Alpha, Inc. v. Beta, LLC, " * 1200),
            "v. " * 10000,
            ("Alpha\nBeta v.\nGamma\n" * 1500),
        ],
        ids=["versus", "long-names", "connectors", "suffixes", "bare-v", "line-breaks"],
    )
    def test_reading_names_is_linear(self, flood):
        started = time.perf_counter()
        extractor.extract_all(flood, include_spec=False)
        assert time.perf_counter() - started < 2.0
