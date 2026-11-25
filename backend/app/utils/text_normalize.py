"""Normalise typographic punctuation before parsing.

Phone keyboards and word processors replace straight quotes and hyphens with
curly quotes and en dashes. A pasted "GAO–16–552" or "GOV’T" then fails
every pattern that expects "GAO-16-552" or "GOV'T", and the tool reports the
citation as unrecognised.

Every replacement is one character for one character. That keeps offsets in the
normalised text identical to offsets in the original, so a citation found in the
normalised text can still be highlighted in the document the user is looking at.
"""

import re
from bisect import bisect_right

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

# Characters that print as nothing: zero-width space, joiners and non-joiner, word joiner and
# the invisible operators beside it, the byte-order mark, the soft hyphen, the marks that set
# the direction of text, and NUL. Text copied from Westlaw, Lexis, a web page or many Word
# files carries them, and one inside a citation ("Roe<U+200B> v. Wade") made every pattern miss
# it: the citation vanished from the results without a word.
#
# They cannot be replaced one for one like the punctuation above (there is nothing to replace
# them with), so they are taken out for matching and the positions of what is found are mapped
# back onto the text the person gave. See strip_invisible.
INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad\x00]")


def normalize_text(text: str) -> str:
    """Return text with typographic punctuation replaced, same length."""
    return (text or "").translate(_TABLE)


class OffsetMap:
    """Positions in a text with its invisible characters removed, mapped back to the original.

    The cleaned text is a run of pieces of the original; for each piece the map holds where it
    starts in both, so a position is found by binary search and one subtraction.
    """

    def __init__(self, clean_starts: list[int], original_starts: list[int]):
        self._clean = clean_starts
        self._original = original_starts

    def start(self, position: int) -> int:
        """Where the character at `position` of the cleaned text is in the original."""
        i = bisect_right(self._clean, position) - 1
        return self._original[i] + position - self._clean[i]

    def end(self, position: int) -> int:
        """Where a span that ends (exclusively) at `position` ends in the original: just after
        its last character, not after any invisible characters that follow it."""
        return self.start(position - 1) + 1 if position > 0 else 0


def strip_invisible(text: str) -> tuple[str, OffsetMap | None]:
    """`text` without its invisible characters, and the map back to it (None if it had none)."""
    if not text or not INVISIBLE.search(text):
        return text, None
    pieces: list[str] = []
    clean_starts: list[int] = []
    original_starts: list[int] = []
    clean_length = 0
    cursor = 0
    for match in INVISIBLE.finditer(text):
        if match.start() > cursor:
            pieces.append(text[cursor:match.start()])
            clean_starts.append(clean_length)
            original_starts.append(cursor)
            clean_length += match.start() - cursor
        cursor = match.end()
    if cursor < len(text):
        pieces.append(text[cursor:])
        clean_starts.append(clean_length)
        original_starts.append(cursor)
    if not pieces:
        return "", OffsetMap([0], [0])
    return "".join(pieces), OffsetMap(clean_starts, original_starts)
