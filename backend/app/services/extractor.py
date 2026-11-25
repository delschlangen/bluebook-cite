"""
Citation extraction engine.

Most kinds of citation are found by a pattern. Case names are not: a party name has no shape a
regular expression can describe without also describing the prose around it, so it is read word
by word from the "v." outwards (see "Party names" below).
"""

import re
from bisect import bisect_left, bisect_right

from .. import limits
from ..models.citation import Citation, CitationStatus, CitationType
from ..utils import bluebook_patterns as bp
from ..utils.bluebook_patterns import LEGAL_NAME_PREFIXES, PATTERNS
from ..utils.text_normalize import normalize_text, strip_invisible
from .bluebook_rules import BluebookFormatter, missing_fields
from .citation_engine import ENGINE

__all__ = ["CitationExtractor", "LEGAL_NAME_PREFIXES", "SpanIndex", "TooManyCitationsError"]


class TooManyCitationsError(Exception):
    """The text holds more citations than one analysis will build."""

    def __init__(self, limit: int):
        super().__init__(f"more than {limit:,} citations")
        self.limit = limit


class SpanIndex:
    """Disjoint [start, end) spans kept sorted, so an overlap test is O(log n).

    Every caller only appends a span after _overlaps() said no, so the spans are
    pairwise disjoint and sorting by start also sorts by end.

    Every citation found claims one span, so `limit` is also a limit on how many citations are
    built. Each costs about 2 KB, and a text at the size limit can hold 375,000 bare "Id."
    (about 800 MB) before the 2,000 shown are chosen; real documents hold a few thousand.
    """

    def __init__(self, limit: int | None = None):
        self.starts: list[int] = []
        self.ends: list[int] = []
        self.limit = limit

    def append(self, span: tuple[int, int]) -> None:
        if self.limit is not None and len(self.starts) >= self.limit:
            raise TooManyCitationsError(self.limit)
        start, end = span
        i = bisect_left(self.starts, start)
        self.starts.insert(i, start)
        self.ends.insert(i, end)

    def overlaps(self, start: int, end: int) -> bool:
        i = bisect_left(self.starts, end)      # spans that begin before `end`
        return i > 0 and self.ends[i - 1] > start

    def end_before(self, position: int) -> int:
        """Where the nearest span that begins before `position` ends (0 if there is none)."""
        i = bisect_left(self.starts, position)
        return self.ends[i - 1] if i > 0 else 0

    def start_after(self, position: int, default: int) -> int:
        """Where the nearest span that begins at or after `position` begins."""
        i = bisect_left(self.starts, position)
        return self.starts[i] if i < len(self.starts) else default

    def __len__(self) -> int:
        return len(self.starts)


# --- Party names -----------------------------------------------------------------------------
#
# A name is read one whitespace-separated token at a time, outwards from "v.". The rules:
#
#   * A name is made of name words: capitalised words, abbreviations and initials.
#   * A lower-case word belongs to it only as a connector BETWEEN two name words ("of", "the",
#     "for", "and", "&", "ex rel.", "de la" ...). "on", "in", "to" and "against" count only
#     straight after the head noun of an organisation's name ("Committee on ..."). Any other
#     lower-case word ends the name on the right and blocks it on the left, and a connector
#     left dangling at either edge is dropped.
#   * A token ending in a full stop that is not an abbreviation ends the sentence: the name
#     stops there and the full stop is not part of it. So do ; : ? ! and a closing bracket.
#   * A comma ends the name unless an entity suffix follows it ("NetChoice, LLC").
#   * A name may run over ONE line break left by a PDF's layout, and only where the line above
#     is long enough to have been wrapped. It never crosses a blank line. (The citation may:
#     "v." cannot end a page's last sentence, so a page break straight before or after it
#     leaves the two names on either side of the break, each whole.)
#   * A possessive place or court in front of the name ("Ohio's", "the Court's") is prose.
#   * Capitalised words that only introduce a citation ("See", "In", "Under") are not its start.
#
# Each scan looks at a bounded number of tokens in a bounded window, so the cost of a document
# is linear in its length however many "v." it holds.

_TOKEN = re.compile(r"\S+")
_MONTHS = frozenset("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())
# Between two parallel citations: the comma before a volume number and a reporter.
_PARALLEL_SPLIT = re.compile(r",\s{1,2}(?=\d{1,4}\s{1,2}[A-Z])")
_SPACES = re.compile(r"\s+")
_LEAD_CHARS = "([{\"'*_"
_TRAIL_CHARS = ",;:.!?)]}\"'*_"
# How far from "v." a name may reach, in characters and in tokens. Far beyond any real name.
_NAME_WINDOW = 400
_MAX_NAME_TOKENS = 30
# A line shorter than this was ended by its author (a heading, a table cell, a caption), not
# wrapped by the page's width, so a name does not continue from it onto the next line.
_MIN_WRAPPED_LINE = 30

_NAME, _CONNECTOR, _CONDITIONAL, _ARTICLE, _STOP = range(5)


def _split_token(token: str) -> tuple[str, str, str]:
    """(opening punctuation, the word, closing punctuation) of one token.

    The full stop of an abbreviation stays on the word ("Inc.", "U.S."); the full stop that
    ends a sentence does not ("Chicago" + ".").
    """
    i, n = 0, len(token)
    while i < n and token[i] in _LEAD_CHARS:
        i += 1
    j = n
    while j > i and token[j - 1] in _TRAIL_CHARS:
        j -= 1
    core, trail = token[i:j], token[j:]
    if trail[:1] == "." and bp.is_abbreviation(core + "."):
        core += "."
        trail = trail[1:]
    return token[:i], core, trail


def _kind(core: str) -> int:
    if not core or core == "Id.":
        # A standalone "Id." is the short form for the authority just cited. It is never a word
        # in a party name: "Id. Brown v. Board" is not a party called "Id. Brown". "Idaho",
        # "Ida." and "Idle Hour" are other tokens and are unaffected.
        return _STOP
    if bp.NAME_WORD.match(core):
        return _NAME
    low = core.lower()
    if low in bp.NAME_CONNECTORS:
        return _CONNECTOR
    if low in bp.CONDITIONAL_CONNECTORS:
        return _CONDITIONAL
    if low in bp.NAME_ARTICLES:
        return _ARTICLE
    return _STOP


def _is_bracketed_name(lead: str, core: str, trail: str) -> bool:
    """"(TOC)" in "Laidlaw Environmental Services (TOC), Inc.": one bracketed word of capitals."""
    return lead == "(" and trail[:1] == ")" and core[:1].isupper() and bool(bp.NAME_WORD.match(core)) and (
        core.isupper() or core.endswith(".")
    )


def _line_was_wrapped(text: str, line_end: int) -> bool:
    """True when the line ending at `line_end` is long enough to have been broken by the page."""
    return line_end - (text.rfind("\n", 0, line_end) + 1) >= _MIN_WRAPPED_LINE


def _is_prose_possessive(core: str, word_before: str | None) -> bool:
    low = core.lower()
    if low.endswith("'s"):
        owner = low[:-2]
    elif low.endswith("s'"):
        owner = low[:-1]
    else:
        return False
    return owner in bp.PROSE_POSSESSORS or (word_before or "").lower() in bp.PERSON_TITLES


# Punctuation that ends a sentence or a quotation and is never the last character of an address
# someone meant to cite, and the brackets that are only if they close nothing inside it.
_AFTER_URL = ".,;:!?'\"*"
_URL_BRACKETS = {")": "(", "]": "[", "}": "{"}


def trim_url(candidate: str) -> str:
    """`candidate` without the sentence punctuation at its end.

    Full stops and brackets INSIDE the address stay: "https://example.org/a.b/c_(d)" is whole.
    A closing bracket at the end goes only when the address has no opening bracket for it, as
    in "(see https://example.org/a)".
    """
    end = len(candidate)
    unmatched = {
        closer: candidate.count(closer) - candidate.count(opener) for closer, opener in _URL_BRACKETS.items()
    }
    while end:
        last = candidate[end - 1]
        if last in _AFTER_URL:
            end -= 1
        elif unmatched.get(last, 0) > 0:
            unmatched[last] -= 1
            end -= 1
        else:
            break
    return candidate[:end]


def sections_of(match, original: str) -> dict:
    """The section, year and publisher fields of a statute match that names its groups."""
    section = collapse(original[match.start("sections"):match.end("sections")])
    return {
        "section": section + (" et seq." if match.groupdict().get("et_seq") else ""),
        "year": int(match.group("year")) if match.group("year") else None,
        "publisher": collapse(match.group("publisher")) if match.group("publisher") else None,
    }


def collapse(text: str) -> str:
    """Whitespace runs, including the line breaks a PDF's layout leaves, as single spaces."""
    return _SPACES.sub(" ", text).strip()


def read_party_left(text: str, anchor: int, floor: int = 0) -> int | None:
    """Where the party that ends just before `anchor` begins, or None if nothing there is a name.

    `floor` is as far left as the name may reach (the end of the previous citation).
    """
    low_edge = max(floor, anchor - _NAME_WINDOW)
    tokens = [m.span() for m in _TOKEN.finditer(text, low_edge, anchor)]
    if tokens and low_edge > floor and not text[low_edge - 1].isspace():
        tokens = tokens[1:]          # cut in half by the window's edge: not a token
    tokens = tokens[-(_MAX_NAME_TOKENS + 4):]

    # Accepted tokens, right to left: (where the word starts, the word, its kind).
    accepted: list[tuple[int, str, int]] = []
    pending: list[tuple[int, str, int]] = []      # connectors waiting for a name word to their left
    head_needed: str | None = None                # "on"/"in"/"to": needs an organisation's head noun
    preposition_needed = False                    # "a"/"an": needs a preposition to its left
    line_breaks = 0
    next_start = anchor
    right_word = ""                               # the name word to the right of the current token

    for index in range(len(tokens) - 1, -1, -1):
        start, end = tokens[index]
        gap_breaks = text.count("\n", end, next_start)
        if gap_breaks and (accepted or pending):  # a break next to "v." is not inside the name
            if gap_breaks > 1 or line_breaks or not _line_was_wrapped(text, end):
                break
            line_breaks += 1
        token = text[start:end]
        if token in ("v.", "v"):
            break
        lead, core, trail = _split_token(token)
        first = not accepted and not pending
        bracketed = _is_bracketed_name(lead, core, trail)
        if bracketed:
            lead, trail = "", trail[1:]
        if trail:
            if trail == "'" and core.endswith("s"):
                core += "'"                        # plural possessive: "Veterans' Ass'n"
            elif first or not (trail == "," and not pending and right_word.lower() in bp.COMMA_SUFFIXES):
                break
        kind = _kind(core)
        if preposition_needed and not (kind in (_CONNECTOR, _CONDITIONAL) and core.lower() in bp._ARTICLE_AFTER):
            break
        preposition_needed = False

        if bracketed:
            if first:
                break
            pending.append((start, token, _CONNECTOR))
        elif kind == _NAME:
            word_before = _split_token(text[slice(*tokens[index - 1])])[1] if index else None
            if _is_prose_possessive(core, word_before):
                break
            if head_needed and core.lower() not in bp.CONDITIONAL_CONNECTORS[head_needed]:
                break
            # "...Acme Corp. Smith v. Jones": an entity suffix straight before a plain word is
            # the end of another name, not the middle of this one.
            if (
                accepted and not pending and core.endswith(".") and core.lower() in bp.ENTITY_SUFFIXES
                and not right_word.endswith(".") and right_word.lower() not in bp.COMMA_SUFFIXES
            ):
                break
            accepted.extend(pending)
            pending.clear()
            head_needed = None
            accepted.append((start + len(lead), core, _NAME))
            right_word = core
            if lead:
                break                              # "(Smith v. Jones)": the name starts at the bracket
        elif kind == _STOP or lead:
            break
        else:
            if first and core.lower() != "al.":
                break                              # "of v. Jones" is not a name; "Smith et al. v." is
            if head_needed:
                break
            if kind == _CONDITIONAL:
                if pending:
                    break
                head_needed = core.lower()
            elif kind == _ARTICLE:
                preposition_needed = True
            pending.append((start, core, kind))
        next_start = start
        if len(accepted) + len(pending) >= _MAX_NAME_TOKENS:
            break

    names = accepted[::-1]
    # Words that only introduce a citation are not its first word, unless the name is one of the
    # procedural forms that really do begin with them ("In re", "Ex parte").
    lowered = " ".join(word.lower() for _, word, _ in names[:5]) + " "
    if not lowered.startswith(LEGAL_NAME_PREFIXES):
        while names and (names[0][1] in bp.LEFT_STOP_WORDS or names[0][2] != _NAME):
            names.pop(0)
    return names[0][0] if names else None


def read_party_right(text: str, position: int, ceiling: int | None = None) -> tuple[int, bool] | None:
    """Where the party that begins at `position` ends, and whether another case's name follows.

    Returns None if nothing there is a name. `ceiling` is as far right as the name may reach.
    """
    high_edge = min(len(text), position + _NAME_WINDOW, ceiling if ceiling is not None else len(text))
    tokens = [m.span() for m in _TOKEN.finditer(text, position, high_edge)][: _MAX_NAME_TOKENS + 4]

    # Accepted tokens, left to right: (where the word ends, the word, its kind).
    accepted: list[tuple[int, str, int]] = []
    pending: list[tuple[int, str, int]] = []
    line_breaks = 0
    previous_end = position
    last_word = ""
    collision = False

    index, count = 0, len(tokens)
    while index < count:
        start, end = tokens[index]
        gap_breaks = text.count("\n", previous_end, start)
        if gap_breaks and (accepted or pending):  # a break next to "v." is not inside the name
            if gap_breaks > 1 or line_breaks or not _line_was_wrapped(text, previous_end):
                break
            line_breaks += 1
        token = text[start:end]
        if token in ("v.", "v"):
            collision = True                       # the next case has begun
            break
        lead, core, trail = _split_token(token)
        bracketed = bool(accepted) and not pending and _is_bracketed_name(lead, core, trail)
        if bracketed:
            lead, trail = "", trail[1:]
            core = f"({core})"
        elif lead:
            break
        kind = _NAME if bracketed else _kind(core)

        if kind == _NAME:
            if accepted and not pending and not bracketed:
                if core in bp.RIGHT_STOP_TITLES:
                    break
                if last_word.endswith("."):
                    # After an abbreviation's full stop: a new sentence, or more of the name?
                    after_suffix = last_word.lower() in bp.ENTITY_SUFFIXES
                    continues = core.endswith(".") or core.lower() in bp.COMMA_SUFFIXES
                    if (after_suffix and not continues) or core in bp.SENTENCE_STARTERS:
                        break
            accepted.extend(pending)
            pending.clear()
            word_end = start + len(lead) + len(core) if not bracketed else end - len(trail)
            if trail == "'" and core.endswith("s") and index + 1 < count:
                # plural possessive inside a name: "Veterans' Ass'n"
                if _kind(_split_token(text[slice(*tokens[index + 1])])[1]) == _NAME:
                    word_end, trail = word_end + 1, ""
            accepted.append((word_end, core, _NAME))
            last_word = core
            if trail:
                # A comma inside a name is followed by an entity suffix; anything else ends it.
                follows = _split_token(text[slice(*tokens[index + 1])])[1] if index + 1 < count else ""
                if trail != "," or follows.lower() not in bp.COMMA_SUFFIXES:
                    break
        elif kind == _STOP or trail:
            break
        else:
            low = core.lower()
            if not accepted:
                if low not in bp.NAME_PARTICLES:
                    break                          # "v. the" is not a name; "v. de la Cruz" is
            elif kind == _CONDITIONAL:
                if pending or last_word.lower() not in bp.CONDITIONAL_CONNECTORS[low]:
                    break
            elif kind == _ARTICLE and not (pending and pending[-1][1].lower() in bp._ARTICLE_AFTER):
                break
            pending.append((end, core, kind))
        previous_end = end
        index += 1
        if len(accepted) + len(pending) >= _MAX_NAME_TOKENS:
            break

    if collision and accepted:
        # "NRA v. Oak Park & McDonald v. City of Chicago": the words between two "v." belong to
        # two cases. The last "and" or "&" is where one stops and the next starts; with none,
        # the final word is the next case's first party.
        cut = max((i for i, (_, word, _) in enumerate(accepted) if word.lower() in ("and", "&")), default=None)
        if cut is not None:
            accepted = accepted[:cut]
        elif len(accepted) > 1:
            accepted = accepted[:-1]
    while accepted and accepted[-1][2] != _NAME:
        accepted.pop()
    if not accepted:
        return None
    return accepted[-1][0], collision


# A book's title is a title. The book pattern accepts "Author, anything (Year)", and in a catalog
# of statements that was a whole entry: two names, then a description, a quotation, a line
# labelled "Context:" and a report's name, reported as a book and set in a book's capitals. A
# title does not contain a labelled line ("Context: ...", "Source: ..." at the start of a line).
# Length is NOT the test: real titles run to fifty words, and a bound on length once dropped
# them without a word.
_LABELLED_LINE = re.compile(r"\n[ \t]{0,8}[A-Z][A-Za-z]{2,20}:[ \t]")


def _reads_as_a_title(title: str) -> bool:
    return not _LABELLED_LINE.search(title)


class CitationExtractor:
    """Extracts citations from legal text using Bluebook patterns."""

    def _clean_party_name(self, name: str) -> str:
        """The party name at the end of `name`, without any prose in front of it.

        "The Supreme Court in Moody" is "Moody"; "See also Brown" is "Brown". Procedural forms
        are the name and are kept whole ("In re Grand Jury Subpoena").
        """
        name = collapse(name)
        if not name or (name.lower() + " ").startswith(LEGAL_NAME_PREFIXES):
            return name
        start = read_party_left(name + " ", len(name) + 1)
        return name[start:] if start is not None else name

    def extract_all(self, text: str, include_spec: bool = True) -> list[Citation]:
        """Extract all citations from text.

        `include_spec` turns the data-driven types (constitutions, rules, regulations,
        reports and so on) on or off. The repair endpoint turns it off when it wants
        only the older case, statute and book readings to compare against.
        """
        # Curly quotes and en dashes from phones and word processors defeat the
        # patterns. The replacement is one character for one character, so every
        # offset still points at the same place in the original document.
        # Characters that print as nothing are taken out for matching, and every position found
        # is mapped back at the end, so the page still highlights the right stretch of the text
        # it was given.
        original, offsets = strip_invisible(text or "")
        text = normalize_text(original)
        citations = []

        # Track positions to avoid duplicate matches (and to bound how many citations are built)
        matched_spans = SpanIndex(limit=limits.MAX_CITATIONS_ANALYZED)

        # Web addresses first: an address is one unbroken token, so nothing else can be inside
        # one, and no other pattern should be allowed to read a piece of one as something else.
        citations.extend(self._extract_urls(text, matched_spans))

        # The data-driven types go next so they claim their spans before the older,
        # looser patterns can read part of the same text as something else (a book,
        # for instance, out of "Agency, GAO-16-552, Title (2016)").
        if include_spec:
            citations.extend(self._extract_spec_types(text, matched_spans))

        # Extract each citation type in priority order
        citations.extend(self._extract_cases(text, matched_spans))
        citations.extend(self._extract_other_cases(text, matched_spans))
        citations.extend(self._extract_statutes(text, matched_spans, original))
        citations.extend(self._extract_law_reviews(text, matched_spans))
        citations.extend(self._extract_books(text, matched_spans))
        citations.extend(self._extract_short_forms(text, matched_spans))

        # Sort by position
        citations.sort(key=lambda c: c.position_start)

        # Assign footnote numbers based on context
        self._assign_footnotes(citations, text)

        for citation in citations:
            self._finish(citation)
            if offsets is not None:
                citation.position_start = offsets.start(citation.position_start)
                citation.position_end = offsets.end(citation.position_end)
        return citations

    # Fields that hold text taken from the document.
    _TEXT_FIELDS = (
        "raw_text", "reporter", "court", "pincite", "author", "title", "journal", "publisher", "code",
        "section", "subsection", "docket_number", "decision_date", "subsequent_history",
    )

    def _finish(self, citation: Citation) -> None:
        """Make one citation fit to show.

        Every piece of text is put on one line: a PDF's layout leaves a line break wherever a
        line was full, and it was being carried into the card, the fields and the suggestion
        ("Civ. Code §\n3273.50"). `raw_text` is what the document says between
        `position_start` and `position_end`, with each run of white space as one space; the
        positions themselves are exact and are what the page highlights.

        Then what is missing is worked out, and the status follows from it: a citation with a
        gap is never "complete".
        """
        for name in self._TEXT_FIELDS:
            value = getattr(citation, name)
            if value and ("\n" in value or "  " in value or value != value.strip()):
                setattr(citation, name, collapse(value))
        if citation.kind or citation.is_short_form:
            return
        # (`template`, the finished shape with the gaps marked, is made when the citation is
        # formatted: it needs the abbreviated case name, which is the costly part of formatting.)
        citation.missing = missing_fields(citation)
        if not citation.missing:
            if citation.status != CitationStatus.NEEDS_VERIFICATION:
                citation.status = CitationStatus.COMPLETE
        elif citation.status == CitationStatus.COMPLETE:
            citation.status = CitationStatus.INCOMPLETE

    def _overlaps(self, start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        """Check if span overlaps with any existing span."""
        if isinstance(spans, SpanIndex):
            return spans.overlaps(start, end)
        for s_start, s_end in spans:
            if not (end <= s_start or start >= s_end):
                return True
        return False

    def _extract_cases(self, text: str, spans: SpanIndex) -> list[Citation]:
        """Extract case citations: every "v." with a party name on each side of it."""
        citations = []
        floor = 0          # where the previous case citation ended: no name reaches back past it

        for anchor in bp.V_ANCHOR.finditer(text):
            if anchor.start() < floor or spans.overlaps(anchor.start(), anchor.end()):
                continue
            name_start = read_party_left(text, anchor.start(), max(floor, spans.end_before(anchor.start())))
            if name_start is None:
                continue
            right = read_party_right(text, anchor.end(), spans.start_after(anchor.end(), len(text)))
            if right is None:
                continue
            name_end, _ = right

            fields = self._case_tail(text, name_end)
            end = fields.pop("end")
            if spans.overlaps(name_start, end):
                fields, end = {}, name_end
                if spans.overlaps(name_start, end):
                    continue
            spans.append((name_start, end))
            floor = end

            citations.append(Citation(
                type=CitationType.CASE,
                status=CitationStatus.INCOMPLETE,          # settled by what is missing, in _finish
                raw_text=text[name_start:end],
                position_start=name_start,
                position_end=end,
                parties=[collapse(text[name_start:anchor.start()]), collapse(text[anchor.end():name_end])],
                **fields,
            ))

        return citations

    def _extract_other_cases(self, text: str, spans: SpanIndex) -> list[Citation]:
        """The case citations that have no "v.": "In re Winship", and the short form of Rule
        10.9, "Bruen, 597 U.S. at 29 n.7"."""
        citations = []
        patterns = bp.CASE_PATTERNS

        if " re " in text or " parte " in text or "atter of " in text:
            for match in patterns["procedural"].finditer(text):
                if spans.overlaps(match.start(), match.end()):
                    continue
                right = read_party_right(text, match.end(), spans.start_after(match.end(), len(text)))
                if right is None:
                    continue
                name_end = right[0]
                fields = self._case_tail(text, name_end)
                end = fields.pop("end")
                # "In re" and "Ex parte" are case names wherever they stand; "Matter of ..." is
                # one only with a citation after it.
                if end == name_end and "atter" in match.group("prefix"):
                    continue
                if spans.overlaps(match.start(), end):
                    continue
                spans.append((match.start(), end))
                fields.pop("complete", None)
                citations.append(Citation(
                    type=CitationType.CASE, status=CitationStatus.INCOMPLETE, raw_text=text[match.start():end],
                    position_start=match.start(), position_end=end,
                    parties=[collapse(text[match.start():name_end])], **fields,
                ))

        if " at " in text or " at\n" in text:
            for match in patterns["short_form"].finditer(text):
                if "." not in match.group("reporter") or spans.overlaps(match.start(), match.end()):
                    continue
                start, parties = match.start(), None
                # the name the short form goes by, if one stands in front of it: "Bruen, 597 ..."
                before = text[max(0, match.start() - 3):match.start()].rstrip()
                comma = match.start() - 3 + len(before) - 1 if match.start() >= 3 else -1
                if before.endswith(","):
                    name_start = read_party_left(text, comma, spans.end_before(comma))
                    if name_start is not None and not spans.overlaps(name_start, match.end()):
                        start, parties = name_start, [collapse(text[name_start:comma])]
                spans.append((start, match.end()))
                citations.append(Citation(
                    type=CitationType.CASE, status=CitationStatus.COMPLETE, raw_text=text[start:match.end()],
                    position_start=start, position_end=match.end(), parties=parties,
                    volume=match.group("volume"), reporter=collapse(match.group("reporter")),
                    pincite=collapse(match.group("pin")), is_short_form=True, short_form_type="short_case",
                ))

        return citations

    @staticmethod
    def _court_and_date(paren: str, year: str) -> tuple[str | None, str | None] | None:
        """The court and the full date from the words before the year in a parenthetical, or None
        if they are not a court and a date at all ("(decided in 1990)" is a remark)."""
        words = paren.split()
        date = None
        if len(words) >= 2 and words[-1][:-1].isdigit() and words[-1].endswith(",") and words[-2][:3] in _MONTHS:
            date = f"{words[-2]} {words[-1]} {year}"
            words = words[:-2]
        if any(not (word[0].isupper() or word[0].isdigit()) for word in words):
            return None
        return (" ".join(words) or None), date

    def _case_tail(self, text: str, position: int) -> dict:
        """What follows a case name at `position`.

        Returns the fields found and `end`, where the citation stops (`position` itself when
        the name is all there is). In order: a docket number in the Bluebook's own form (Rule
        10.8.1), an electronic citation, a reporter citation, a court and docket number in the
        order filings are listed, a court alone, a year alone.
        """
        patterns = bp.CASE_PATTERNS

        def court_year(match, fields: dict) -> int:
            """Add court, year and date from the parenthetical, if it is one; where it ends."""
            if not match.group("year"):
                return match.end()
            read = self._court_and_date(match.group("paren"), match.group("year"))
            if read is None:
                end = match.start("paren") - 1       # a remark in brackets, not a court and year
                while end > position and text[end - 1].isspace():
                    end -= 1
                return end
            fields["court"], fields["decision_date"] = read
            fields["year"] = int(match.group("year"))
            return match.end()

        def electronic(match, fields: dict) -> None:
            words = match.group("electronic").split()   # "2020 WL 1234567", "2020 U.S. Dist. LEXIS 12345"
            fields.update(volume=words[0], reporter=" ".join(words[1:-1]), page=words[-1])
            if match.group("star"):
                fields["pincite"] = f"at {match.group('star')}"

        match = patterns["docket"].match(text, position)
        if match:
            fields = {"docket_number": collapse(match.group("docket"))}
            if match.group("electronic"):
                electronic(match, fields)
            fields["end"] = court_year(match, fields)
            return fields

        match = patterns["electronic"].match(text, position)
        if match:
            fields = {}
            electronic(match, fields)
            fields["end"] = court_year(match, fields)
            return fields

        match = patterns["reporter"].match(text, position)
        if match:
            page = match.group("page")
            fields = {
                "volume": match.group("volume"),
                "reporter": collapse(match.group("reporter")),
                "page": None if page.startswith("_") else page,       # "410 U.S. ___": not yet paginated
                "pincite": collapse(match.group("pin")) if match.group("pin") else None,
            }
            if match.group("parallel"):
                fields["parallel_citations"] = [
                    collapse(p) for p in _PARALLEL_SPLIT.split(match.group("parallel")) if p.strip(" ,\n")
                ]
            end = court_year(match, fields)
            if fields.get("year") and end == match.end():
                history = patterns["history"].match(text, end)
                if history:
                    fields["subsequent_history"] = collapse(history.group("history"))
                    end = history.end()
            fields["end"] = end
            return fields

        match = patterns["court_docket"].match(text, position)
        if match:
            return {
                "court": collapse(match.group("court")) if match.group("court") else None,
                "docket_number": collapse(match.group("docket")),
                "end": match.end(),
            }

        match = patterns["court"].match(text, position)
        if match:
            return {"court": collapse(match.group("court")), "end": match.end()}

        match = patterns["year"].match(text, position)
        if match:
            fields = {}
            end = court_year(match, fields)
            if fields:
                fields["end"] = end
                return fields

        return {"end": position}

    def _extract_statutes(self, text: str, spans: SpanIndex, original: str | None = None) -> list[Citation]:
        """Extract statute citations: the U.S. Code, every state's code, and session laws.

        A codified statute is found from its section sign. The code is read from the few words
        in front of the sign (Table T1.3 for the states) and the sections from what follows:
        every subsection, a range ("§§ 898-a to 898-e", "§§ 6-27-101 to -106"), a list, "et
        seq." and the "(Publisher Year)" of the code. `original` is the text before its dashes
        were made plain, so that a range is reported with the dash its author typed.
        """
        citations: list[Citation] = []
        patterns = bp.STATUTE_PATTERNS
        original = text if original is None else original

        def add(start: int, end: int, **fields) -> None:
            if spans.overlaps(start, end):
                return
            spans.append((start, end))
            citations.append(Citation(
                type=CitationType.STATUTE,
                status=fields.pop("status", CitationStatus.INCOMPLETE),
                raw_text=text[start:end],
                position_start=start,
                position_end=end,
                **fields,
            ))

        # Session laws first: the code in "(codified at ...)" is part of the session law's
        # citation, not a second one.
        if "Laws" in text or "Acts" in text or "Stat." in text or "Serv." in text:
            for match in patterns["session_law"].finditer(text):
                codified = match.group("codified")
                add(
                    match.start(), match.end(), form="session_law", year=int(match.group("year")),
                    code=collapse(match.group("code")), page=collapse(match.group("what")),
                    parallel_citations=[collapse(codified)] if codified else None,
                )

        if "Pub." in text:
            for match in patterns["public_law_section"].finditer(text):
                codified = match.group("codified")
                add(
                    match.start(), match.end(), form="public_law", code=f"Pub. L. No. {match.group('law')}",
                    section=collapse(original[match.start("sections"):match.end("sections")]),
                    volume=match.group("volume"), reporter="Stat.", page=match.group("page"), pincite=match.group("pin"),
                    year=int(match.group("year")) if match.group("year") else None,
                    parallel_citations=[collapse(codified)] if codified else None,
                )

        for sign in patterns["section_sign"].finditer(text):
            if spans.overlaps(sign.start(), sign.end()):
                continue
            low = max(sign.start() - 110, spans.end_before(sign.start()), 0)
            fields: dict = {}
            head = patterns["head_usc"].search(text, low, sign.start())
            if head:
                written = head.group("code").replace(" ", "").replace(".", "").upper()
                fields = {"title_number": head.group("title"), "code": {"USCA": "U.S.C.A.", "USCS": "U.S.C.S."}.get(written, "U.S.C.")}
                start = head.start()
            else:
                head = patterns["head_state"].search(text, low, sign.start())
                if head:
                    code = collapse(head.group("code"))
                    fields = {"code": code, "form": "state"}
                    start = head.start("code")
                    if head.group("title") and code.startswith(("Pa.", "Ill.")):
                        fields["title_number"] = head.group("title")      # "42 Pa. Cons. Stat. § 9711"
                        start = head.start()
                    if head.group("unit") in ("tit.", "ch."):
                        fields["title_number"] = head.group("unit_number")
                        fields["form"] = "state_title" if head.group("unit") == "tit." else "state_chapter"
                else:
                    head = patterns["head_other"].search(text, low, sign.start())
                    if not head:
                        continue                   # a bare "§ 922(g)(9)": no code to cite it to
                    fields = {"code": collapse(head.group("code")), "form": "state",
                              "status": CitationStatus.NEEDS_VERIFICATION}
                    start = head.start()
            tail = patterns["sections_many" if len(sign.group()) > 1 else "sections_one"].match(text, sign.end())
            if not tail:
                continue
            add(start, tail.end(), **fields, **sections_of(tail, original))

        if "Comp." in text:
            for match in patterns["illinois"].finditer(text):
                add(match.start(), match.end(), form="no_sign", title_number=match.group("title"),
                    code=collapse(match.group("code")), **sections_of(match, original))

        if any(style in text for style in bp.LOCAL_CODE_STYLES):
            for match in patterns["local_style"].finditer(text):
                add(match.start(), match.end(), form="state", code=bp.LOCAL_CODE_STYLES[match.group("code")],
                    **sections_of(match, original))

        return citations

    def _extract_spec_types(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Citations of every kind described by the spec.

        These are never sent to an outside lookup: for most of them no free source can
        verify a record, so the honest output is the corrected form and a list of what
        is missing.
        """
        citations: list[Citation] = []
        for match in ENGINE.find_all(text):
            if self._overlaps(match.start, match.end, spans):
                continue
            spans.append((match.start, match.end))

            spec = ENGINE.type_spec(match.type_id)
            missing = ENGINE.missing(match.type_id, match.fields)
            citations.append(Citation(
                type=CitationType(spec.get("citation_type", "other")),
                status=CitationStatus.INCOMPLETE if missing else CitationStatus.COMPLETE,
                raw_text=text[match.start:match.end],
                position_start=match.start,
                position_end=match.end,
                kind=match.type_id,
                kind_label=spec["label"],
                spec_fields=match.fields,
                missing=missing,
                template=ENGINE.render(match.type_id, match.fields, gaps=True) if missing else None,
                format_confidence=spec.get("confidence"),
            ))
        return citations

    def _extract_law_reviews(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract law review article citations."""
        citations = []

        for match in PATTERNS["law_review"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.LAW_REVIEW,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                author=match.group(1).strip(),
                title=match.group(2).strip(),
                volume=match.group(3),
                journal=match.group(4).strip(),
                page=match.group(5),
                pincite=match.group(6) if match.lastindex >= 6 and match.group(6) else None,
                year=int(match.group(7)) if match.lastindex >= 7 else None,
            ))

        return citations

    def _extract_books(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract book citations.

        The pattern is "Author, Title (Year)" and will take almost anything with a comma and a
        year, so what it calls the author is checked: it must read as a name (the same reading
        a party name gets, which also drops prose in front of it), and it may not be a code, a
        reporter or a section sign. A legislative body as "author" is a committee print or
        report described in prose: it is reported as legislative material, as written, and is
        never set in a book's capitals.
        """
        citations = []

        for match in PATTERNS["book"].finditer(text):
            start = read_party_left(text, match.end(1), match.start(1))
            if start is None:
                continue
            author = collapse(text[start:match.end(1)])
            title = match.group(2).strip()
            # (A pinpoint at the end of a title, "... Policies § 11.2", is not a section sign in
            # the title: the formatter separates the two.)
            if bp.NOT_AN_AUTHOR.search(author) or "§" in BluebookFormatter._split_pinpoint(title)[0]:
                continue
            if not _reads_as_a_title(title):
                continue
            if self._overlaps(start, match.end(), spans):
                continue

            spans.append((start, match.end()))
            year = int(match.group(4)) if match.lastindex >= 4 else None

            if bp.LEGISLATIVE_AUTHOR.search(author):
                citations.append(Citation(
                    type=CitationType.LEGISLATIVE,
                    status=CitationStatus.INCOMPLETE,
                    raw_text=text[start:match.end()],
                    position_start=start,
                    position_end=match.end(),
                    author=author,
                    title=title,
                    year=year,
                    form="described",
                ))
                continue

            citations.append(Citation(
                type=CitationType.BOOK,
                status=CitationStatus.COMPLETE,
                raw_text=text[start:match.end()],
                position_start=start,
                position_end=match.end(),
                author=author,
                title=title,
                edition=match.group(3) if match.lastindex >= 3 and match.group(3) else None,
                year=year,
            ))

        return citations

    def _extract_short_forms(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract short form citations (Id., supra)."""
        citations = []

        # Id. citations
        for match in PATTERNS["id_citation"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.OTHER,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                is_short_form=True,
                short_form_type="id",
                # A bare "Id." has no groups at all, so lastindex is None, not 0. Comparing
                # None to an int raised TypeError, which made every document containing a
                # bare "Id." fail (the most common short form in legal writing).
                pincite=match.group(1) or match.group(2),
            ))

        # Supra citations: found from the word "supra", then the name in front of it.
        if "supra" in text:
            for match in PATTERNS["supra_citation"].finditer(text):
                named = PATTERNS["supra_author"].search(text, max(0, match.start() - 70), match.start())
                if not named:
                    continue
                start = named.start()
                if self._overlaps(start, match.end(), spans):
                    continue

                spans.append((start, match.end()))

                citations.append(Citation(
                    type=CitationType.OTHER,
                    status=CitationStatus.COMPLETE,
                    raw_text=text[start:match.end()],
                    position_start=start,
                    position_end=match.end(),
                    is_short_form=True,
                    short_form_type="supra",
                    author=named.group(1),
                    footnote_number=int(match.group(1)),
                    pincite=match.group(2),
                ))

        return citations

    def _extract_urls(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract URL citations.

        The address is what the pattern found less the sentence punctuation after it: the full
        stop that ends "Source: https://example.org/a.html." is the sentence's, and was being
        reported as part of the address (and then printed twice in the suggestion).
        """
        citations = []

        for match in PATTERNS["url"].finditer(text):
            start = match.start()
            url = trim_url(match.group(0))
            end = start + len(url)

            # An address the page's width broke just before its file extension: "...12.23.25."
            # at the end of one line and "pdf." alone at the start of the next. Only this one
            # shape is rejoined here; anything less certain is the PDF reader's to repair.
            if match.group(0).endswith(".") and len(url) == len(match.group(0)) - 1:
                wrapped = PATTERNS["url_wrapped_extension"].match(text, match.end())
                if wrapped:
                    url = match.group(0) + wrapped.group(1)
                    end = wrapped.end(1)

            # "(last visited Mar. 3, 2024)": the day the author says they looked at the page.
            access_date = None
            visited = PATTERNS["url_visited"].match(text, end)
            if visited:
                access_date = collapse(visited.group(1))
                end = visited.end()

            if len(url) <= len("https://") or self._overlaps(start, end, spans):
                continue
            spans.append((start, end))

            citations.append(Citation(
                type=CitationType.WEBSITE,
                status=CitationStatus.INCOMPLETE,
                # as one address, even where the page broke it over two lines
                raw_text=url + (" " + collapse(visited.group(0)) if visited else ""),
                position_start=start,
                position_end=end,
                url=url,
                access_date=access_date,
            ))

        return citations

    def _assign_footnotes(self, citations: list[Citation], text: str) -> None:
        """Say which note each citation is in, if it is in one.

        A note runs from its marker to the next marker or the next blank line, whichever comes
        first. What follows a blank line is body text again: the next page of a PDF, or the next
        block of a Word file (whose notes are written one to a line after the body). The number
        used to be carried forward until the next marker, however far away: in a paper whose
        only markers were notes 1 and 2, every one of the 300 citations after them, 56 pages of
        body text, was reported as note 2.
        """
        # A Word document carries real footnote numbers, written in front of each
        # note by the parser. When any are present they are the truth, and the
        # guess below, which would misread numbered headings and lines that begin
        # with a reporter volume, is skipped entirely.
        explicit = list(PATTERNS["footnote_marker_explicit"].finditer(text))
        if explicit:
            # Endnotes are numbered separately from footnotes: "[^e3]" is not note 3 again.
            markers = [(m.start(), int(m.group(2)), "endnote" if m.group(1) else "footnote") for m in explicit]
        else:
            markers = [(m.start(), int(m.group(1)), "footnote") for m in PATTERNS["footnote_marker"].finditer(text)]
        if not markers:
            return

        marker_starts = [start for start, _, _ in markers]
        blank_lines = [m.start() for m in PATTERNS["blank_line"].finditer(text)]

        # Nearest marker at or before each citation: a binary search per citation instead of a
        # scan from the top of the document. Then the first blank line after that marker.
        for citation in citations:
            i = bisect_right(marker_starts, citation.position_start) - 1
            if i < 0:
                continue
            start, number, note_type = markers[i]
            j = bisect_left(blank_lines, start)
            if j < len(blank_lines) and blank_lines[j] < citation.position_start:
                # the note ended before this citation: it is in the body
                citation.footnote_number = None
                continue
            if number > 0:
                citation.footnote_number = number
                citation.note_type = note_type
