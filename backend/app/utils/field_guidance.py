"""What each citation field is, and which Bluebook rule governs it.

Telling someone a field is missing is a scolding. Telling them what the field
is, where it goes in the finished citation, and which rule to read is teaching.
This table is the difference.

Rule numbers are Bluebook 21st Edition. Keep them accurate: a wrong rule number
sends a reader to the wrong page and costs more time than saying nothing.
"""

# field -> (human label, rule, one-line explanation)
FIELD_GUIDANCE: dict[str, dict[str, str]] = {
    "parties": {
        "label": "party names",
        "rule": "10.2",
        "why": "The first-listed party on each side, separated by “v.”",
    },
    "volume": {
        "label": "volume number",
        "rule": "10.3",
        "why": "The reporter volume the case starts in, before the reporter name.",
    },
    "reporter": {
        "label": "reporter",
        "rule": "10.3",
        "why": "The abbreviated reporter, for example U.S., S. Ct. or F.4th. See Table 1.",
    },
    "page": {
        "label": "first page",
        "rule": "10.3",
        "why": "The page the opinion begins on, not the page you are quoting.",
    },
    "court": {
        "label": "court",
        "rule": "10.4",
        "why": "The deciding court, in the parenthetical. Omitted for the U.S. Supreme Court.",
    },
    "year": {
        "label": "year",
        "rule": "10.5",
        "why": "The year of decision, in the same parenthetical as the court.",
    },
    "title_number": {
        "label": "title number",
        "rule": "12",
        "why": "The code title, the number before U.S.C.",
    },
    "code": {
        "label": "code",
        "rule": "12",
        "why": "The code being cited, usually U.S.C.",
    },
    "section": {
        "label": "section",
        "rule": "12",
        "why": "The section number, after the § symbol.",
    },
    "author": {
        "label": "author",
        "rule": "15.1",
        "why": "The full name of the author, as it appears on the publication.",
    },
    "title": {
        "label": "title",
        "rule": "15",
        "why": "The full title of the work.",
    },
    "journal": {
        "label": "journal",
        "rule": "16",
        "why": "The abbreviated periodical name. See Table 13.",
    },
    "url": {
        "label": "URL",
        "rule": "18",
        "why": "The direct address of the source.",
    },
}

# How a complete citation of each type is laid out. Placeholders are the field
# names in braces, so a partial citation can be shown in its finished shape
# with the gaps marked rather than described in the abstract.
CITATION_TEMPLATES: dict[str, str] = {
    "case": "*{parties}*, {volume} {reporter} {page} ({court}{year}).",
    "statute": "{title_number} {code} § {section}.",
    "law_review": "{author}, *{title}*, {volume} {journal} {page} ({year}).",
    "book": "{author}, {title} ({year}).",
    "website": "{author}, *{title}*, {url}.",
}


def guidance_for(field: str) -> dict:
    """Label, rule and explanation for one field.

    `display_rule` is the rule that is safe to SHOW: the nearest verified one, never an
    unconfirmed number. See app/utils/rules.py.
    """
    from .rules import display_rule

    entry = FIELD_GUIDANCE.get(field)
    if entry is None:
        return {"field": field, "label": field, "rule": "", "display_rule": None, "why": ""}
    return {"field": field, **entry, "display_rule": display_rule(entry["rule"])}
