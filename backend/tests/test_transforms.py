"""Tests for the citation transforms.

The expected answers live in shared/engine_conformance.json under transform_cases and
are ALSO run by the browser's test suite against the JavaScript implementation. If the
two ever disagree, one of the suites fails.
"""

import json
from pathlib import Path

import pytest

from app.services import transforms
from app.services.spec_engine import TRANSFORMS

SHARED = Path(__file__).resolve().parents[2] / "shared" / "engine_conformance.json"
CASES = json.loads(SHARED.read_text())["transform_cases"]


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{c['transform']}:{c['input'][:32]}" for c in CASES]
)
def test_shared_transform_cases(case):
    assert TRANSFORMS[case["transform"]](case["input"], "law_review") == case["expected"]


def test_every_shared_transform_is_registered():
    for case in CASES:
        assert case["transform"] in TRANSFORMS


def test_registration_exposes_every_function():
    names = {
        "roman", "thousands", "ordinal", "bbdate", "chamber",
        "institution", "paper", "state_abbr", "titlecase",
    }
    assert names <= set(TRANSFORMS)
    assert transforms.register_all() is None


class TestRule8TitleCapitalisation:
    """The case that started this: a pasted GAO title capitalised 'With' and 'The'."""

    def test_the_pasted_gao_title(self):
        pasted = "Firearms Data: ATF Did Not Always Comply With The Appropriations Act Restrictions"
        assert transforms.titlecase(pasted) == (
            "Firearms Data: ATF Did Not Always Comply with the Appropriations Act Restrictions"
        )

    def test_the_first_word_is_always_capitalised(self):
        assert transforms.titlecase("the law").startswith("The")

    def test_the_word_after_a_colon_is_always_capitalised(self):
        assert "A Study" in transforms.titlecase("history: a study of the law")

    def test_five_letter_prepositions_stay_capitalised(self):
        # "Between" is seven letters, "Through" is seven, "Under" is five.
        assert transforms.titlecase("between facts") == "Between Facts"
        assert " Through " in transforms.titlecase("a walk through time")
        assert " Under " in transforms.titlecase("a state under siege")

    def test_acronyms_and_names_are_left_exactly_as_typed(self):
        assert transforms.titlecase("the ATF and NetChoice") == "The ATF and NetChoice"

    def test_an_all_capitals_title_is_returned_unchanged(self):
        # ATF cannot be told from DID, so nothing is guessed.
        assert transforms.titlecase("FIREARMS DATA: ATF DID NOT") == "FIREARMS DATA: ATF DID NOT"

    def test_it_is_idempotent(self):
        once = transforms.titlecase("the rise and fall of the roman empire")
        assert transforms.titlecase(once) == once

    def test_punctuation_around_a_word_does_not_hide_it(self):
        assert transforms.titlecase('the "rule of law" and order') == 'The "Rule of Law" and Order'


class TestStateNamesSurviveAbbreviation:
    def test_west_virginia_is_not_split(self):
        assert transforms.institution("West Virginia Department of Health") == "West Virginia Dep't of Health"
