"""Transforms used by citation templates.

Each one is a small pure function: (value, style) -> string. They are the only code
a citation type can call from its template, which is what keeps a type a piece of data.
The browser has an identical set in frontend/src/utils/transforms.js, and
shared/engine_conformance.json holds the expected answers both must produce.

The rules they implement, and the confidence behind each, are described inline. Where
a rule could not be verified against the Bluebook itself, the function says so rather
than implying certainty.
"""

from __future__ import annotations

import re

from ..utils.bluebook_patterns import STATE_ABBREVIATIONS, abbreviate_party_name
from .spec_engine import register_transform

# --- Roman numerals (Rule 11: articles and amendments) --------------------

_ROMAN = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def roman(value: str, style: str = "law_review") -> str:
    """Arabic numbers become roman numerals; anything else is upper-cased.

    The Constitution is cited with roman numerals, so "art. 1" is a mistake worth
    fixing. Values outside 1 to 3999 are left alone rather than guessed at.
    """
    value = value.strip()
    if value.isdigit():
        n = int(value)
        if not 1 <= n <= 3999:
            return value
        out = ""
        for size, letters in _ROMAN:
            while n >= size:
                out += letters
                n -= size
        return out
    return value.upper()


# --- Numbers (Rule 6.2) ----------------------------------------------------


def thousands(value: str, style: str = "law_review") -> str:
    """Put commas in runs of five or more digits: 50379 -> 50,379; 8977 stays.

    A four-digit number takes no comma. A page such as "H12455" gets one inside the
    digits only, and a number that already has commas is untouched.
    """
    # String-based on purpose, so very long numbers keep every digit and the browser
    # (which cannot hold them exactly as numbers) produces the same answer.
    return re.sub(r"\d{5,}", lambda m: re.sub(r"\B(?=(\d{3})+(?!\d))", ",", m.group()), value)


def ordinal(value: str, style: str = "law_review") -> str:
    """117 -> 117th. The Bluebook writes 2d and 3d, not 2nd and 3rd (Rule 6.2(b))."""
    m = re.fullmatch(r"\s*(\d+)(?:st|nd|rd|th|d)?\s*", value, re.I)
    if not m:
        return value
    n = int(m.group(1))
    if 11 <= n % 100 <= 13:
        suffix = "th"
    elif n % 10 == 1:
        suffix = "st"
    elif n % 10 in (2, 3):
        suffix = "d"
    else:
        suffix = "th"
    return f"{n}{suffix}"


# --- Dates (Table T12) -----------------------------------------------------

_MONTHS = {
    "jan": "Jan.", "january": "Jan.",
    "feb": "Feb.", "february": "Feb.",
    "mar": "Mar.", "march": "Mar.",
    "apr": "Apr.", "april": "Apr.",
    "may": "May",
    "jun": "June", "june": "June",
    "jul": "July", "july": "July",
    "aug": "Aug.", "august": "Aug.",
    "sep": "Sept.", "sept": "Sept.", "september": "Sept.",
    "oct": "Oct.", "october": "Oct.",
    "nov": "Nov.", "november": "Nov.",
    "dec": "Dec.", "december": "Dec.",
}
_MONTH_NUMBER = {i: m for i, m in enumerate(
    ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."], 1)}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))


def bbdate(value: str, style: str = "law_review") -> str:
    """Month names become Table T12 abbreviations: "September 29, 1995" -> "Sept. 29, 1995".

    Handles "Month D, YYYY", "Month D YYYY", "D Month YYYY", "Month YYYY" and ISO
    dates. A bare year, or anything not recognised as a date, is returned unchanged.
    """
    text = value.strip()

    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{_MONTH_NUMBER[month]} {day}, {year}"
        return value

    m = re.fullmatch(rf"({_MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", text, re.I)
    if m:
        return f"{_MONTHS[m.group(1).lower()]} {int(m.group(2))}, {m.group(3)}"

    m = re.fullmatch(rf"(\d{{1,2}})\s+({_MONTH_PATTERN})\.?,?\s+(\d{{4}})", text, re.I)
    if m:
        return f"{_MONTHS[m.group(2).lower()]} {int(m.group(1))}, {m.group(3)}"

    m = re.fullmatch(rf"({_MONTH_PATTERN})\.?,?\s+(\d{{4}})", text, re.I)
    if m:
        return f"{_MONTHS[m.group(1).lower()]} {m.group(2)}"

    return value


# --- Congress (Rule 13) ----------------------------------------------------


def chamber(value: str, style: str = "law_review") -> str:
    """HR / h.r. / H. R. -> H.R.; s -> S. Anything else is returned unchanged.

    Only the House and Senate are handled. Joint and concurrent resolutions use
    forms that could not be confirmed, so they are deliberately not guessed.
    """
    key = re.sub(r"[\s.]", "", value).upper()
    return {"HR": "H.R.", "S": "S."}.get(key, value)


# --- Authors and sources ---------------------------------------------------

# Beyond the Table T6 words already in the case-name table, these two appear in
# every source's GAO and CRS examples ("GOV'T ACCOUNTABILITY OFF.",
# "CONG. RSCH. SERV."). They are applied to institutional authors only.
_INSTITUTION_EXTRAS = {"Office": "Off.", "Congressional": "Cong."}


def institution(value: str, style: str = "law_review") -> str:
    """Abbreviate an institutional author with the Table T6 words.

    "Government Accountability Office" -> "Gov't Accountability Off."
    Text that is already abbreviated passes through unchanged, so this is safe to
    apply to what a user typed after they have abbreviated it themselves.
    """
    out = abbreviate_party_name(value)
    for full, abbrev in _INSTITUTION_EXTRAS.items():
        out = re.sub(rf"\b{full}\b", abbrev, out, flags=re.I)
    return out


_PAPERS = {
    "nytimes": "N.Y. Times", "newyorktimes": "N.Y. Times", "thenewyorktimes": "N.Y. Times",
    "washingtonpost": "Wash. Post", "thewashingtonpost": "Wash. Post", "washpost": "Wash. Post",
    "wallstreetjournal": "Wall St. J.", "thewallstreetjournal": "Wall St. J.", "wallstj": "Wall St. J.",
    "latimes": "L.A. Times", "losangelestimes": "L.A. Times", "thelosangelestimes": "L.A. Times",
    "usatoday": "USA Today",
    "bostonglobe": "Bos. Globe", "thebostonglobe": "Bos. Globe", "bosglobe": "Bos. Globe",
    "chicagotribune": "Chi. Trib.", "thechicagotribune": "Chi. Trib.", "chitrib": "Chi. Trib.",
}


def paper(value: str, style: str = "law_review") -> str:
    """Normalise a newspaper name to its Bluebook form; unknown papers pass through."""
    key = re.sub(r"[^a-z]", "", value.lower())
    return _PAPERS.get(key, value)


_STATES_BY_NAME = {name.lower(): abbr for name, abbr in STATE_ABBREVIATIONS.items()}


def state_abbr(value: str, style: str = "law_review") -> str:
    """Washington -> Wash. (Table T10). An abbreviation or unknown name is unchanged."""
    return _STATES_BY_NAME.get(value.strip().lower(), value)


# --- Title capitalisation (Rule 8) -----------------------------------------
#
# Rule 8, as every source consulted states it: capitalise the first word, the first
# word after a colon, and every word except articles, conjunctions and prepositions
# of four or fewer letters. So "with" and "the" are lower case mid-title.
#
# Limits, stated plainly. A word that is a preposition in one sentence and an adverb
# in another ("up", "out", "off", "over") cannot be told apart without parsing, so
# those are left capitalised. Words that already contain a capital after the first
# letter (ATF, NetChoice, iPhone) are left exactly as typed. A title typed entirely
# in capitals is returned unchanged, because "ATF" cannot be told from "DID".

_SMALL_WORDS = frozenset({
    "a", "an", "the",
    "and", "but", "or", "nor", "for", "as", "if", "than",
    "at", "by", "in", "of", "on", "to", "per", "via", "from", "into", "onto",
    "upon", "with", "amid", "atop", "unto",
})


def titlecase(value: str, style: str = "law_review") -> str:
    return _titlecase(value, first_forced=True)


def titlecase_mid(value: str, style: str = "law_review") -> str:
    """Rule 8 for a title that does not begin the citation.

    Identical to titlecase except the first word is not forced to a capital, so
    "of the Law Governing Lawyers" keeps its "the" while "torts" still becomes "Torts".
    """
    return _titlecase(value, first_forced=False)


def _titlecase(value: str, first_forced: bool) -> str:
    if not value or not re.search(r"[a-z]", value):
        return value  # empty, or typed entirely in capitals

    parts = re.split(r"(\s+)", value)
    out: list[str] = []
    capitalise_next = first_forced
    for part in parts:
        if not part or part.isspace():
            out.append(part)
            continue
        out.append(_case_word(part, capitalise_next))
        capitalise_next = part.endswith(":")
    return "".join(out)


def _case_word(token: str, force_capital: bool) -> str:
    # Split off leading and trailing punctuation so the word itself can be judged.
    m = re.fullmatch(r"([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)", token)
    lead, core, trail = m.group(1), m.group(2), m.group(3)
    if not core:
        return token

    if "-" in core:
        pieces = core.split("-")
        cased = [_case_piece(p, force_capital if i == 0 else True) for i, p in enumerate(pieces)]
        return lead + "-".join(cased) + trail
    return lead + _case_piece(core, force_capital) + trail


def _case_piece(word: str, force_capital: bool) -> str:
    # A capital anywhere after the first letter marks an acronym or a name.
    if any(c.isupper() for c in word[1:]):
        return word
    if not force_capital and word.lower() in _SMALL_WORDS:
        return word.lower()
    return word[:1].upper() + word[1:]


# Acronyms that must stay in capitals when text typed entirely in capitals is brought
# back to ordinary case. Deliberately a short, curated list of agencies and bodies that
# actually appear in citations: guessing at unknown acronyms would mangle them, so any
# acronym not listed here is capitalised like an ordinary word and the interface shows
# the result next to the input so it can be corrected.
_ACRONYMS = frozenset({
    "GAO", "CRS", "CBO", "OMB", "EPA", "FDA", "FTC", "SEC", "DOJ", "DOD", "HHS", "IRS",
    "NLRB", "FCC", "FERC", "NASA", "RAND", "OECD", "UN", "US", "ACLU", "ABA", "AALL",
    "NAACP", "ATF", "FBI", "CIA", "NSA", "DHS", "USDA", "HUD", "VA", "TSA", "ICE", "CDC",
    "NIH", "NSF", "OSHA", "EEOC", "FEMA", "FAA", "FHA", "SBA", "USPS", "DEA", "ATM",
    "NATO", "WHO", "IMF", "EU", "UK", "NCAA", "AARP", "AFL-CIO",
})


def decaps(value: str, style: str = "law_review") -> str:
    """Bring text typed entirely in capitals back to ordinary capitalisation.

    Law review style sets authors and titles in large and small capitals, so people
    paste them as capitals; a court document needs ordinary case. Text that already
    has a lower-case letter is returned untouched. Known acronyms (and anything with
    a period inside it, like U.S.) keep their capitals; everything else is lowered and
    then given Rule 8 capitalisation.
    """
    if not value or re.search(r"[a-z]", value):
        return value

    def lower_token(token: str) -> str:
        core = token.strip(".,;:()\"'")
        if re.search(r"\.[A-Za-z]", token) or core.upper() in _ACRONYMS:
            return token
        return token.lower()

    lowered = "".join(
        part if part.isspace() else lower_token(part) for part in re.split(r"(\s+)", value)
    )
    return _titlecase(lowered, first_forced=True)


def register_all() -> None:
    for name, fn in (
        ("roman", roman), ("thousands", thousands), ("ordinal", ordinal),
        ("bbdate", bbdate), ("chamber", chamber), ("institution", institution),
        ("paper", paper), ("state_abbr", state_abbr), ("titlecase", titlecase),
        ("titlecase_mid", titlecase_mid), ("decaps", decaps),
    ):
        register_transform(name, fn)


register_all()
