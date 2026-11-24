"""Normalise typographic punctuation before parsing.

Phone keyboards and word processors replace straight quotes and hyphens with
curly quotes and en dashes. A pasted "GAO–16–552" or "GOV’T" then fails
every pattern that expects "GAO-16-552" or "GOV'T", and the tool reports the
citation as unrecognised.

Every replacement is one character for one character. That keeps offsets in the
normalised text identical to offsets in the original, so a citation found in the
normalised text can still be highlighted in the document the user is looking at.
"""

# character -> replacement (always a single character)
NORMALIZATION: dict[str, str] = {
    # apostrophes and single quotes
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "ʼ": "'",
    "′": "'",
    # double quotes
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "″": '"',
    # dashes that mean "hyphen" inside identifiers, numbers and ranges
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "−": "-",
    # spaces that are not the ordinary space
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "　": " ",
}

_TABLE = str.maketrans(NORMALIZATION)


def normalize_text(text: str) -> str:
    """Return text with typographic punctuation replaced, same length."""
    return (text or "").translate(_TABLE)
