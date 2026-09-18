"""Tests for Bluebook Table 6 party-name abbreviation.

abbreviate_party_name applies every Table 6 entry with IGNORECASE and word
boundaries, in dict order. That is easy to break and hard to notice, so the
behavior is pinned here.
"""

import pytest

from app.utils.bluebook_patterns import (
    PARTY_ABBREVIATIONS,
    STATE_ABBREVIATIONS,
    abbreviate_party_name,
)

TABLE_6_CASES = [
    ("Association of American Railroads", "Ass'n of Am. Railroads"),
    ("Miami Herald Publishing Company", "Miami Herald Publ'g Co."),
    ("Northern Railway Company", "N. Ry. Co."),
    ("International Business Machines Corporation", "Int'l Business Machines Corp."),
    ("Environmental Protection Agency", "Envtl. Prot. Agency"),
    ("Southwest Airlines Co.", "Sw. Airlines Co."),
]


@pytest.mark.parametrize("raw,expected", TABLE_6_CASES, ids=[c[0][:32] for c in TABLE_6_CASES])
def test_table_6_abbreviations(raw, expected):
    assert abbreviate_party_name(raw) == expected


class TestStateNamesAreProtected:
    """"North Carolina" must not become "N. Carolina". Table 6 abbreviates
    "North" to "N.", but a state name is a unit."""

    @pytest.mark.parametrize(
        "state",
        ["North Carolina", "South Dakota", "West Virginia", "New York", "New Hampshire"],
    )
    def test_state_name_survives_intact(self, state):
        assert abbreviate_party_name(state) == state

    def test_state_inside_a_longer_name(self):
        assert abbreviate_party_name("State of North Carolina") == "State of North Carolina"

    def test_directional_word_still_abbreviates_when_not_a_state(self):
        # "Northern" is not a state name, so Table 6 applies normally.
        assert abbreviate_party_name("Northern Railway Company") == "N. Ry. Co."

    def test_no_placeholder_leaks_into_output(self):
        """The implementation swaps state names for placeholders while
        applying Table 6. A placeholder reaching the output is a hard bug."""
        for state in STATE_ABBREVIATIONS:
            result = abbreviate_party_name(f"{state} Department of Transportation")
            assert "__STATE_" not in result, f"placeholder leaked for {state!r}"


class TestAbbreviationProperties:
    def test_idempotent(self):
        """Abbreviating twice must equal abbreviating once. Otherwise repeated
        formatting slowly corrupts a name."""
        for raw, _ in TABLE_6_CASES:
            once = abbreviate_party_name(raw)
            assert abbreviate_party_name(once) == once, f"not idempotent: {raw!r}"

    def test_idempotent_across_every_table_6_entry(self):
        for full in PARTY_ABBREVIATIONS:
            once = abbreviate_party_name(full)
            twice = abbreviate_party_name(once)
            assert twice == once, f"not idempotent for Table 6 entry {full!r}"

    def test_never_returns_empty_for_nonempty_input(self):
        for full in PARTY_ABBREVIATIONS:
            assert abbreviate_party_name(full).strip(), f"{full!r} abbreviated to nothing"

    def test_leading_the_is_dropped(self):
        assert abbreviate_party_name("The Coca-Cola Company") == "Coca-Cola Co."


class TestNoOverAbbreviation:
    """Words that merely contain a Table 6 term must not be rewritten."""

    @pytest.mark.parametrize(
        "name",
        ["Coast Guard", "Trans Union", "Costco Wholesale", "Goodyear"],
    )
    def test_unrelated_names_are_untouched(self, name):
        assert abbreviate_party_name(name) == name
