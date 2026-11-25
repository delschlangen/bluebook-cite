"""Three ways a citation was lost, or an analysis was, without a word.

- An invisible character inside a citation (text copied from Westlaw, a web page or many Word
  files carries zero-width spaces and soft hyphens) made every pattern miss it.
- "supra note" followed by thousands of digits raised ValueError and the endpoint answered 500.
- An article or book whose title ran past 250 characters was silently dropped.
"""

import time

import pytest

from app.services.extractor import CitationExtractor
from app.utils.text_normalize import INVISIBLE, strip_invisible

extractor = CitationExtractor()

INVISIBLES = {
    "zero-width space": "​",
    "zero-width non-joiner": "‌",
    "zero-width joiner": "‍",
    "word joiner": "⁠",
    "byte-order mark": "﻿",
    "soft hyphen": "­",
    "left-to-right mark": "‎",
    "right-to-left mark": "‏",
    "right-to-left override": "‮",
    "NUL": "\x00",
}


class TestInvisibleCharacters:
    @pytest.mark.parametrize("character", INVISIBLES.values(), ids=INVISIBLES.keys())
    @pytest.mark.parametrize(
        "template",
        [
            "See Roe{x} v. Wade, 410 U.S. 113 (1973).",       # between the name and "v."
            "See Roe v. Wade, 410 U.{x}S. 113 (1973).",       # inside the reporter
            "See Roe v. W{x}ade, 410 U.S. 113 (19{x}73).",    # inside a word and inside the year
            "{x}See Roe v. Wade, 410 U.S. 113 (1973).{x}",    # at the edges of the text
        ],
    )
    def test_a_citation_with_one_inside_it_is_still_found_whole(self, character, template):
        text = template.format(x=character)
        (case,) = extractor.extract_all(text)

        assert case.status.value == "complete"
        assert case.parties == ["Roe", "Wade"]
        assert (case.volume, case.reporter, case.page, case.year) == ("410", "U.S.", "113", 1973)
        assert case.raw_text == "Roe v. Wade, 410 U.S. 113 (1973)"

    @pytest.mark.parametrize("character", ["​", "­", "﻿"])
    def test_the_positions_point_at_the_text_that_was_given(self, character):
        text = f"Intro{character}duction. See Roe{character} v. Wade, 410 U.{character}S. 113 (1973){character}. Then 42 U.S.C. § 1983{character}."
        case, statute = extractor.extract_all(text)

        spanned = text[case.position_start:case.position_end]
        assert spanned.startswith("Roe") and spanned.endswith("(1973)")
        assert INVISIBLE.sub("", spanned) == "Roe v. Wade, 410 U.S. 113 (1973)"
        assert text[statute.position_start:statute.position_end] == "42 U.S.C. § 1983"

    def test_text_without_any_is_not_copied_or_mapped(self):
        text = "See Roe v. Wade, 410 U.S. 113 (1973)."
        cleaned, offsets = strip_invisible(text)

        assert cleaned is text and offsets is None

    def test_the_map_is_exact_at_every_position(self):
        text = "​ab​​cd­e﻿"
        cleaned, offsets = strip_invisible(text)

        assert cleaned == "abcde"
        assert [text[offsets.start(i)] for i in range(5)] == list("abcde")
        assert text[offsets.start(1):offsets.end(4)].replace("​", "") == "bcd"
        assert offsets.end(5) == text.index("e") + 1

    def test_a_text_of_nothing_but_invisible_characters(self):
        assert extractor.extract_all("​" * 50) == []

    def test_stripping_is_linear(self):
        text = ("Roe​ v. Wade, 410 U.S. 113 (1973). " * 800)[:30_000]
        started = time.perf_counter()
        found = extractor.extract_all(text)
        assert time.perf_counter() - started < 2.0
        assert len(found) > 700


class TestSupra:
    def test_a_supra_citation_names_its_source_and_note(self):
        (found,) = extractor.extract_all("Sunstein, supra note 12, at 45.")

        assert found.short_form_type == "supra"
        assert (found.author, found.footnote_number, found.pincite) == ("Sunstein", 12, "45")
        assert found.raw_text == "Sunstein, supra note 12, at 45"

    @pytest.mark.parametrize("count", [7, 20, 5000, 30_000])
    def test_a_run_of_digits_after_supra_note_is_not_an_error(self, count):
        """int() refuses a number of more than 4,300 digits; the endpoint answered 500."""
        text = "Smith, supra note " + "7" * count + ". See Roe v. Wade, 410 U.S. 113 (1973)."
        found = extractor.extract_all(text)        # must not raise

        assert [c.raw_text for c in found if c.type.value == "case"] == ["Roe v. Wade, 410 U.S. 113 (1973)"]
        assert [c for c in found if c.short_form_type == "supra"] == []

    def test_supra_is_found_in_linear_time(self):
        for flood in ("supra note 1, at 1; " * 1500, "Alpha, supra note 1 " * 1500, "supra " * 5000, "a" * 30_000 + " supra note 1"):
            started = time.perf_counter()
            extractor.extract_all(flood)
            assert time.perf_counter() - started < 2.0


class TestLongTitles:
    @pytest.mark.parametrize("length", [100, 240, 260, 300, 390])
    def test_an_article_with_a_long_title_is_not_dropped(self, length):
        title = ("Administrative Law and the Problem of Deference " * 10)[:length].strip()
        text = f"Jane Q. Roe, {title}, 107 Harv. L. Rev. 1613, 1621 (2019)."
        (article,) = extractor.extract_all(text)

        assert article.type.value == "law_review"
        assert article.title == title
        assert (article.volume, article.page, article.year) == ("107", "1613", 2019)

    @pytest.mark.parametrize("length", [100, 260, 390])
    def test_a_book_with_a_long_title_is_not_dropped(self, length):
        title = ("The Law of Administrative Procedure in Theory and Practice " * 8)[:length].strip()
        (book,) = extractor.extract_all(f"Jane Q. Roe, {title} (3d ed. 2019).")

        assert book.type.value == "book"
        assert book.title == title
