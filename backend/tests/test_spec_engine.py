"""Tests for the data-driven citation engine.

The cases live in shared/engine_conformance.json and are read by the browser's test
suite as well, so the Python and JavaScript engines are held to the same answers.
"""

import json
from pathlib import Path

import pytest

from app.services.spec_engine import TRANSFORMS, Engine, diagnose

SHARED = Path(__file__).resolve().parents[2] / "shared" / "engine_conformance.json"
CORPUS = json.loads(SHARED.read_text())
ENGINE = Engine(CORPUS["spec"])


@pytest.mark.parametrize("case", CORPUS["match_cases"], ids=[c["name"][:60] for c in CORPUS["match_cases"]])
def test_conformance_match_cases(case):
    result = diagnose(ENGINE, case["input"], case["style"])

    if case["type_id"] is None:
        assert result is None, f"expected no recognition, got {result}"
        return

    assert result is not None, "expected the citation to be recognised"
    assert result.type_id == case["type_id"]
    assert result.missing == case["missing"]
    assert result.formatted == case["formatted"]
    assert result.template == case["template"]


@pytest.mark.parametrize("case", CORPUS["find_all_cases"], ids=[c["name"][:60] for c in CORPUS["find_all_cases"]])
def test_conformance_find_all(case):
    found = ENGINE.find_all(case["input"])
    actual = [{"type_id": m.type_id, "text": case["input"][m.start : m.end]} for m in found]
    assert actual == case["expected"]


class TestTheGuaranteeThatMatters:
    """A formatted citation is never produced with a hole in it."""

    def test_nothing_is_formatted_while_a_required_field_is_missing(self):
        result = diagnose(ENGINE, "GAO-16-552")
        assert result.formatted is None
        assert result.missing == ["author", "title", "year"]

    def test_gaps_are_shown_only_when_asked_for(self):
        match = ENGINE.best_match("GAO-16-552")
        assert ENGINE.render(match.type_id, match.fields) is None
        assert "[author]" in ENGINE.render(match.type_id, match.fields, gaps=True)

    def test_every_missing_field_carries_its_rule_and_explanation(self):
        result = diagnose(ENGINE, "GAO-16-552")
        assert [d["rule"] for d in result.details] == ["R1", "R3", "R4"]
        assert all(d["why"] and d["label"] for d in result.details)


class TestEngineMechanics:
    def test_optional_block_needs_every_field_inside_it(self):
        spec = {
            "types": [
                {
                    "id": "t",
                    "label": "t",
                    "patterns": [{"regex": r"(?P<a>A\d)(?:-(?P<b>B\d))?(?:-(?P<c>C\d))?"}],
                    "fields": [{"name": "a", "label": "a", "required": True}],
                    "templates": {"law_review": "{a}<< pair {b} and {c}>>."},
                }
            ]
        }
        engine = Engine(spec)
        both = engine.best_match("A1-B2-C3")
        assert engine.render("t", both.fields) == "A1 pair B2 and C3."
        only_one = engine.best_match("A1-B2")
        assert engine.render("t", only_one.fields) == "A1."

    def test_transforms_apply_left_to_right(self):
        """upper then italic and italic then upper give the same answer, so they
        cannot show the order. These two do not commute."""
        from app.services.spec_engine import register_transform

        register_transform("add_x", lambda v, s: v + "x")
        try:
            spec = {"types": [{
                "id": "t", "label": "t",
                "patterns": [{"regex": r"(?P<a>[a-z]+)"}],
                "fields": [{"name": "a", "label": "a", "required": True}],
                "templates": {"law_review": "{a|add_x|upper} / {a|upper|add_x}"},
            }]}
            engine = Engine(spec)
            match = engine.best_match("word")
            assert engine.render("t", match.fields) == "WORDX / WORDx"
        finally:
            TRANSFORMS.pop("add_x", None)

    def test_transforms_apply_in_order(self):
        spec = {
            "types": [
                {
                    "id": "t",
                    "label": "t",
                    "patterns": [{"regex": r"(?P<a>[a-z]+)"}],
                    "fields": [{"name": "a", "label": "a", "required": True}],
                    "templates": {"law_review": "{a|upper|italic}"},
                }
            ]
        }
        engine = Engine(spec)
        match = engine.best_match("word")
        assert engine.render("t", match.fields) == "*WORD*"

    def test_the_known_transforms_exist(self):
        assert {"upper", "smallcaps", "italic", "roman"} <= set(TRANSFORMS)

    def test_a_pattern_covering_little_of_the_input_is_rejected(self):
        engine = Engine(CORPUS["spec"])
        assert engine.best_match("x" * 80 + " GAO-16-552 " + "y" * 80) is None

    def test_priority_breaks_a_tie_between_equal_matches(self):
        spec = {
            "types": [
                {"id": "low", "label": "low", "priority": 1,
                 "patterns": [{"regex": r"(?P<a>ABC)"}],
                 "fields": [{"name": "a", "label": "a", "required": True}],
                 "templates": {"law_review": "{a}"}},
                {"id": "high", "label": "high", "priority": 9,
                 "patterns": [{"regex": r"(?P<a>ABC)"}],
                 "fields": [{"name": "a", "label": "a", "required": True}],
                 "templates": {"law_review": "{a}"}},
            ]
        }
        assert Engine(spec).best_match("ABC").type_id == "high"
