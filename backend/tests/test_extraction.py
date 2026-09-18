"""Golden-corpus tests for citation extraction and formatting.

Every case in GOLDEN is a real citation. The corpus is the contract: if a
regex change alters any of these outputs, CI fails before the change can
reach production.

The REGRESSIONS block is the more important half. Each entry is a bug that
actually shipped and was seen in the deployed app.
"""

import time

import pytest

from app.services.extractor import CitationExtractor
from app.utils.bluebook_patterns import PATTERNS

# (input, expected formatted output)
GOLDEN = [
    # --- Cases, Rule 10 ---
    (
        "Brandenburg v. Ohio, 395 U.S. 444 (1969)",
        "*Brandenburg v. Ohio*, 395 U.S. 444 (1969).",
    ),
    (
        "Texas v. Johnson, 491 U.S. 397 (1989)",
        "*Texas v. Johnson*, 491 U.S. 397 (1989).",
    ),
    (
        "Packingham v. North Carolina, 137 S. Ct. 1730 (2017)",
        "*Packingham v. North Carolina*, 137 S. Ct. 1730 (2017).",
    ),
    # Pincite is preserved.
    (
        "Miami Herald Publishing Co. v. Tornillo, 418 U.S. 241, 258 (1974)",
        "*Miami Herald Publ'g Co. v. Tornillo*, 418 U.S. 241, 258 (1974).",
    ),
    # Court identifier survives the parenthetical.
    (
        "Gonzalez v. Google LLC, 2 F.4th 871 (9th Cir. 2021)",
        "*Gonzalez v. Google LLC*, 2 F.4th 871 (9th Cir. 2021).",
    ),
    # Entity suffix behind a comma. This extracted as "LLC v. Paxton" in
    # production, so it is pinned here and in the browser suite.
    (
        "NetChoice, LLC v. Paxton, 49 F.4th 439 (5th Cir. 2022)",
        "*NetChoice, LLC v. Paxton*, 49 F.4th 439 (5th Cir. 2022).",
    ),
    # --- Statutes and regulations ---
    ("47 U.S.C. § 230", "47 U.S.C. § 230."),
    ("15 U.S.C. § 45", "15 U.S.C. § 45."),
    ("47 C.F.R. § 54", "47 C.F.R. § 54."),
    # --- Books, Rule 15 ---
    (
        "Erwin Chemerinsky, Constitutional Law: Principles and Policies (6th ed. 2019)",
        "Erwin Chemerinsky, CONSTITUTIONAL LAW: PRINCIPLES AND POLICIES (6th ed. 2019).",
    ),
    (
        "Lawrence Lessig, Code and Other Laws of Cyberspace (1999)",
        "Lawrence Lessig, CODE AND OTHER LAWS OF CYBERSPACE (1999).",
    ),
]


@pytest.mark.parametrize("source,expected", GOLDEN, ids=[g[0][:40] for g in GOLDEN])
def test_golden_corpus(roundtrip, source, expected):
    assert roundtrip(source) == expected


# ---------------------------------------------------------------------------
# Regressions. Each of these shipped to production at least once.
# ---------------------------------------------------------------------------


class TestPartyNameCommas:
    """The party pattern could not cross a comma, so the entity suffix
    became the whole party name."""

    def test_llc_after_comma_is_kept(self, extractor):
        cites = extractor.extract_all(
            "NetChoice, LLC v. Paxton, 49 F.4th 439 (5th Cir. 2022)"
        )
        assert cites[0].parties == ["NetChoice, LLC", "Paxton"]

    def test_inc_after_comma_is_kept(self, extractor):
        cites = extractor.extract_all(
            "Students for Fair Admissions, Inc. v. Harvard, 600 U.S. 181 (2023)"
        )
        assert cites[0].parties == ["Students for Fair Admissions, Inc.", "Harvard"]

    @pytest.mark.parametrize(
        "text",
        [
            "NetChoice, LLC v. Paxton, 49 F.4th 439 (5th Cir. 2022)",
            "Students for Fair Admissions, Inc. v. Harvard, 600 U.S. 181 (2023)",
        ],
    )
    def test_plaintiff_is_never_a_bare_entity_suffix(self, extractor, text):
        plaintiff = extractor.extract_all(text)[0].parties[0]
        assert plaintiff not in {"LLC", "Inc.", "Corp.", "Co."}


class TestFootnoteMarkers:
    """Reporter volumes and statute titles were being reported as footnote
    numbers, producing labels like 'Note 395' and 'Note 47'."""

    def test_reporter_volume_is_not_a_footnote(self, extractor):
        cites = extractor.extract_all(
            "See Brandenburg v. Ohio, 395 U.S. 444 (1969)."
        )
        assert all(c.footnote_number is None for c in cites)

    def test_statute_title_is_not_a_footnote(self, extractor):
        cites = extractor.extract_all("Congress said so. See 47 U.S.C. § 230.")
        assert all(c.footnote_number != 47 for c in cites)

    def test_real_footnote_lines_still_match(self):
        text = "12 See Brandenburg v. Ohio, 395 U.S. 444 (1969).\n13. Texas v. Johnson."
        found = [m.group(1) for m in PATTERNS["footnote_marker"].finditer(text)]
        assert found == ["12", "13"]

    def test_inline_numbers_never_match(self):
        text = "See Brandenburg v. Ohio, 395 U.S. 444 (1969). Also 47 U.S.C. § 230."
        assert list(PATTERNS["footnote_marker"].finditer(text)) == []


class TestPartyNameCleanup:
    """The prose-trimming heuristic must not corrupt real case names."""

    @pytest.mark.parametrize(
        "name",
        [
            "In re Grand Jury Subpoena",
            "Ex parte Young",
            "In the Matter of Baby M",
            "A Book Named Memoirs",
        ],
    )
    def test_procedural_and_article_names_survive(self, extractor, name):
        assert extractor._clean_party_name(name) == name

    @pytest.mark.parametrize(
        "captured,expected",
        [
            ("The Supreme Court in Moody", "Moody"),
            ("See also Brown", "Brown"),
            ("held that Smith", "Smith"),
            ("First Amendment issues. See Brown", "Brown"),
        ],
    )
    def test_prose_prefix_is_trimmed(self, extractor, captured, expected):
        assert extractor._clean_party_name(captured) == expected

    def test_leading_the_is_dropped_per_rule_10_2_1(self, extractor):
        assert extractor._clean_party_name("The Florida Star") == "Florida Star"


class TestBookEdition:
    """The ordinal was dropped from the edition, rendering '6th ed.' as
    '6 ed.'."""

    # "2d" and "3d" are the Bluebook spellings (Rule 6.2(b)), not "2nd"/"3rd".
    @pytest.mark.parametrize("ordinal", ["2d", "3d", "4th", "6th", "21st"])
    def test_ordinal_suffix_is_captured(self, extractor, ordinal):
        text = f"Author Name, Some Legal Treatise ({ordinal} ed. 2020)"
        cites = extractor.extract_all(text)
        assert cites[0].edition == ordinal


class TestPerformance:
    """The party pattern is quadratic. Ordinary documents must stay fast, and
    adversarial input must not be able to pin a worker."""

    def test_long_document_extracts_quickly(self, extractor):
        paragraph = (
            "The Supreme Court has held that the First Amendment protects "
            "expressive conduct. See Brandenburg v. Ohio, 395 U.S. 444 (1969). "
            "The Court in Texas v. Johnson reaffirmed this principle. "
        )
        text = paragraph * 200  # roughly a law review article
        start = time.perf_counter()
        extractor.extract_all(text)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"extraction took {elapsed:.2f}s on a normal document"

    def test_adversarial_input_is_bounded(self):
        # Capitalized words that never complete a " v. " construction are the
        # worst case for the party pattern.
        hostile = "A" + (" Ab" * 2000) + " v"
        start = time.perf_counter()
        PATTERNS["case_complete"].search(hostile)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"adversarial input took {elapsed:.2f}s"


def test_extraction_is_deterministic(extractor):
    text = (
        "See Brandenburg v. Ohio, 395 U.S. 444 (1969). Id. at 447. "
        "Compare Texas v. Johnson, 491 U.S. 397 (1989), with 47 U.S.C. § 230."
    )
    first = [(c.type, c.raw_text) for c in extractor.extract_all(text)]
    second = [(c.type, c.raw_text) for c in CitationExtractor().extract_all(text)]
    assert first == second


def test_no_citation_in_plain_prose(extractor):
    text = "This paragraph discusses the law generally but cites nothing at all."
    assert extractor.extract_all(text) == []
