"""Bluebook rule numbers that are safe to show a user.

A wrong rule number sends a reader to the wrong page, which is worse than naming no
rule at all. The research behind this tool could not read the Bluebook itself, so
sub-rule numbers (10.3.2, 12.9.4, 15.7 and so on) came from search summaries that
often disagree with each other.

The policy that follows from that: a rule is only DISPLAYED if it appears in
VERIFIED_RULES below. Any other number is shown as its nearest verified ancestor, so
"10.3.2" is presented as "Rule 10.3 (Reporters and Services)". Fields may still claim
the more specific number in the spec; the display layer will not repeat the claim
until someone has confirmed it.

Every entry here is either a top-level rule whose title is certain, or a sub-rule that
the research marked high confidence from more than one source. Edition: the numbers
follow the 21st edition. The 22nd edition (2025) is current, and the research found
most of these unchanged, but a few (14.4, T10) are known to differ. The interface says
so alongside any rule it shows.
"""

from __future__ import annotations

VERIFIED_RULES: dict[str, str] = {
    "8": "Capitalization",
    "10": "Cases",
    "10.1": "Basic Citation Forms",
    "10.2": "Case Names",
    "10.3": "Reporters and Services",
    "10.4": "Court and Jurisdiction",
    "10.5": "Date or Year",
    "10.7": "Prior and Subsequent History",
    "11": "Constitutions",
    "12": "Statutes",
    "12.3.2": "Year of Code",
    "13": "Legislative Materials",
    "13.2": "Bills and Resolutions",
    "13.3": "Hearings",
    "13.4": "Reports, Documents, and Committee Prints",
    "13.5": "Debates",
    "14": "Administrative and Executive Materials",
    "14.2": "Rules, Regulations, and Other Publications",
    "14.3": "Administrative Adjudications and Arbitrations",
    "15": "Books, Reports, and Other Nonperiodic Materials",
    "15.1": "Author",
    "16": "Periodicals",
    "17": "Unpublished and Forthcoming Sources",
    "17.3": "Forthcoming Publications",
    "18": "The Internet, Electronic Media, and Other Nonprint Resources",
    "20": "Foreign Materials",
    "21": "International Materials",
    "21.4": "Treaties and Other International Agreements",
    "B17": "Court and Litigation Documents",
    "T6": "Table T6: Case Names",
    "T10": "Table T10: Geographical Terms",
}

EDITION_NOTE = (
    "Rule numbers follow the Bluebook 21st edition. If your journal or court uses the "
    "22nd edition, confirm the number there."
)


def _ancestors(number: str):
    """'10.3.2' -> '10.3.2', '10.3', '10'. A letter prefix ('B17.1') is kept."""
    parts = number.split(".")
    for end in range(len(parts), 0, -1):
        yield ".".join(parts[:end])


def display_rule(number: str | None) -> dict[str, str] | None:
    """The nearest verified rule at or above `number`, or None if none is verified.

    Anything after the first parenthesis is ignored, so "15.1(c)" resolves via "15.1".
    """
    if not number:
        return None
    base = number.split("(")[0].strip()
    for candidate in _ancestors(base):
        if candidate in VERIFIED_RULES:
            return {"number": candidate, "title": VERIFIED_RULES[candidate]}
    return None
