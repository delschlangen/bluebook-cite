"""Golden tests for the real citation spec.

shared/spec_golden.json is ALSO run by the browser's test suite against the JavaScript
engine, so both engines are held to the same answers on the same real citations.
"""

import json
from pathlib import Path

import pytest

import app.services.transforms  # noqa: F401  (registers the transforms the spec uses)
from app.services.spec_engine import Engine, diagnose
from app.utils.citation_spec import SPEC
from app.utils.text_normalize import normalize_text

GOLDEN = json.loads((Path(__file__).resolve().parents[2] / "shared" / "spec_golden.json").read_text())
ENGINE = Engine(SPEC)


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["name"][:70] for c in GOLDEN["cases"]])
def test_golden_citation(case):
    result = diagnose(ENGINE, normalize_text(case["input"]), case.get("style", "law_review"))

    if case["type_id"] is None:
        assert result is None, f"recognised as {result and result.type_id}"
        return

    assert result is not None, "expected the citation to be recognised"
    assert result.type_id == case["type_id"]
    assert result.missing == case["missing"]
    assert result.formatted == case["formatted"]
    if "template" in case:
        assert result.template == case["template"]


@pytest.mark.parametrize("case", GOLDEN["document_cases"], ids=[c["name"][:70] for c in GOLDEN["document_cases"]])
def test_golden_document(case):
    text = normalize_text(case["input"])
    found = [{"type_id": m.type_id, "text": text[m.start : m.end]} for m in ENGINE.find_all(text)]
    assert found == case["expected"]


class TestSpecIntegrity:
    """Properties that must hold for EVERY type, so a new one cannot be added wrongly."""

    def test_every_type_has_the_required_keys(self):
        for t in SPEC["types"]:
            for key in ("id", "label", "family", "citation_type", "confidence", "fields", "templates", "example"):
                assert key in t, f"{t.get('id')} is missing {key}"
            assert "law_review" in t["templates"], f"{t['id']} has no law_review template"

    def test_ids_are_unique(self):
        ids = [t["id"] for t in SPEC["types"]]
        assert len(ids) == len(set(ids))

    def test_every_type_belongs_to_a_declared_family(self):
        families = {f["id"] for f in SPEC["families"]}
        for t in SPEC["types"]:
            assert t["family"] in families, t["id"]

    def test_every_placeholder_in_a_template_is_a_declared_field(self):
        import re
        for t in SPEC["types"]:
            names = {f["name"] for f in t["fields"]}
            for style, template in t["templates"].items():
                for m in re.finditer(r"\{(\w+)", template):
                    assert m.group(1) in names, f"{t['id']}/{style}: {{{m.group(1)}}} is not a field"

    def test_every_field_that_is_optional_sits_inside_an_optional_block(self):
        """An optional field outside <<...>> would be shown to the user as a gap."""
        import re
        for t in SPEC["types"]:
            optional = {f["name"] for f in t["fields"] if not f["required"]}
            for style, template in t["templates"].items():
                outside = re.sub(r"<<.*?>>", "", template, flags=re.S)
                for m in re.finditer(r"\{(\w+)", outside):
                    assert m.group(1) not in optional, (
                        f"{t['id']}/{style}: optional field {m.group(1)} is outside an optional block"
                    )

    def test_every_required_field_appears_in_every_template(self):
        import re
        for t in SPEC["types"]:
            required = {f["name"] for f in t["fields"] if f["required"]}
            for style, template in t["templates"].items():
                used = {m.group(1) for m in re.finditer(r"\{(\w+)", template)}
                assert required <= used, f"{t['id']}/{style} omits required {required - used}"

    def test_every_transform_a_template_uses_is_registered(self):
        import re

        from app.services.spec_engine import TRANSFORMS
        for t in SPEC["types"]:
            for template in t["templates"].values():
                for m in re.finditer(r"\{\w+((?:\|\w+)*)\}", template):
                    for name in filter(None, m.group(1).split("|")):
                        assert name in TRANSFORMS, f"{t['id']} uses unknown transform {name}"

    def test_every_worked_example_renders_completely(self):
        """The example shown in the browse view is rendered through the real template,
        so it can never drift from what the tool actually outputs."""
        for t in SPEC["types"]:
            for style in t["templates"]:
                rendered = ENGINE.render_example(t["id"], style)
                assert rendered, f"{t['id']}/{style} example does not render"

    def test_worked_examples_have_no_gaps_left_in_them(self):
        for t in SPEC["types"]:
            rendered = ENGINE.render_example(t["id"])
            assert rendered is not None and "[" not in rendered, f"{t['id']}: {rendered}"

    def test_a_worked_example_is_recognised_as_its_own_type(self):
        """Round trip: what the tool prints for an example, it must understand."""
        for t in SPEC["types"]:
            if not t["patterns"]:
                continue  # guidance-only types are never read back
            rendered = ENGINE.render_example(t["id"], "law_review")
            result = diagnose(ENGINE, rendered, "law_review")
            assert result is not None, f"{t['id']}: {rendered!r} is not recognised"
            assert result.type_id == t["id"], f"{t['id']}: {rendered!r} read as {result.type_id}"
            assert result.missing == [], f"{t['id']}: {rendered!r} reports missing {result.missing}"

    def test_the_output_of_a_correction_is_stable(self):
        """Correcting a corrected citation must change nothing."""
        for case in GOLDEN["cases"]:
            if case.get("formatted"):
                style = case.get("style", "law_review")
                again = diagnose(ENGINE, case["formatted"], style)
                assert again is not None, f"{case['name']}: output not recognised"
                assert again.formatted == case["formatted"], (
                    f"{case['name']}: {case['formatted']!r} became {again.formatted!r}"
                )

    def test_every_claimed_rule_resolves_to_a_verified_one(self):
        """No field may end up with no rule to show at all."""
        for t in SPEC["types"]:
            for f in t["fields"]:
                assert ENGINE.display_rule(f["rule"]) is not None, f"{t['id']}.{f['name']}: rule {f['rule']!r}"

    def test_a_low_confidence_type_never_recognises_input(self):
        """A format taken from search summaries is guidance, never a correction."""
        for t in SPEC["types"]:
            if t["confidence"] == "low":
                assert not t["patterns"], f"{t['id']} is low confidence but corrects input"
