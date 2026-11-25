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
from ..utils.text_normalize import normalize_text
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
        text = normalize_text(text)
        citations = []

        # Track positions to avoid duplicate matches (and to bound how many citations are built)
        matched_spans = SpanIndex(limit=limits.MAX_CITATIONS_ANALYZED)

        # The data-driven types go first so they claim their spans before the older,
        # looser patterns can read part of the same text as something else (a book,
        # for instance, out of "Agency, GAO-16-552, Title (2016)").
        if include_spec:
            citations.extend(self._extract_spec_types(text, matched_spans))

        # Extract each citation type in priority order
        citations.extend(self._extract_cases(text, matched_spans))
        citations.extend(self._extract_statutes(text, matched_spans))
        citations.extend(self._extract_law_reviews(text, matched_spans))
        citations.extend(self._extract_books(text, matched_spans))
        citations.extend(self._extract_short_forms(text, matched_spans))
        citations.extend(self._extract_urls(text, matched_spans))

        # Sort by position
        citations.sort(key=lambda c: c.position_start)

        # Assign footnote numbers based on context
        self._assign_footnotes(citations, text)

        return citations

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

            complete = bool(fields.pop("complete", False))
            citations.append(Citation(
                type=CitationType.CASE,
                status=CitationStatus.COMPLETE if complete else CitationStatus.INCOMPLETE,
                raw_text=text[name_start:end],
                position_start=name_start,
                position_end=end,
                parties=[collapse(text[name_start:anchor.start()]), collapse(text[anchor.end():name_end])],
                **fields,
            ))

        return citations

    def _case_tail(self, text: str, position: int) -> dict:
        """What follows a case name at `position`: its reporter citation, if it has one.

        Returns the fields found and `end`, where the citation stops (`position` itself when
        the name is all there is).
        """
        match = PATTERNS["case_tail_complete"].match(text, position)
        if match:
            # Parse court and year from the parenthetical
            court_year = match.group(5)
            year = court = None
            year_match = re.search(r"(\d{4})", court_year)
            if year_match:
                year = int(year_match.group(1))
                court = collapse(court_year.replace(year_match.group(1), "")) or None
            return {
                "volume": match.group(1),
                "reporter": collapse(match.group(2)),
                "page": match.group(3),
                "pincite": match.group(4),
                "court": court,
                "year": year,
                "complete": True,
                "end": match.end(),
            }

        # Then a reporter citation but no year parenthetical. These are mostly complete and must
        # not be reported as though the volume, reporter and page were absent.
        match = PATTERNS["case_tail_no_year"].match(text, position)
        if match:
            return {
                "volume": match.group(1),
                "reporter": collapse(match.group(2)),
                "page": match.group(3),
                "end": match.end(),
            }

        return {"end": position}

    def _extract_statutes(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract statute citations."""
        citations = []

        # U.S.C. citations
        for match in PATTERNS["statute_usc"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.STATUTE,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                title_number=match.group(1),
                code="U.S.C.",
                section=match.group(2),
                subsection=match.group(3) if match.lastindex >= 3 else None,
            ))

        # State statute citations
        for match in PATTERNS["statute_state"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.STATUTE,
                status=CitationStatus.NEEDS_VERIFICATION,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                code=match.group(1).strip(),
                section=match.group(2),
            ))

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
        """Extract book citations."""
        citations = []

        for match in PATTERNS["book"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.BOOK,
                status=CitationStatus.COMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                author=match.group(1).strip(),
                title=match.group(2).strip(),
                edition=match.group(3) if match.lastindex >= 3 and match.group(3) else None,
                year=int(match.group(4)) if match.lastindex >= 4 else None,
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
                pincite=match.group(1),
            ))

        # Supra citations
        for match in PATTERNS["supra_citation"].finditer(text):
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
                short_form_type="supra",
                author=match.group(1).strip(),
                footnote_number=int(match.group(2)) if match.group(2) else None,
                pincite=match.group(3) if match.lastindex >= 3 else None,
            ))

        return citations

    def _extract_urls(self, text: str, spans: list[tuple[int, int]]) -> list[Citation]:
        """Extract URL citations."""
        citations = []

        for match in PATTERNS["url"].finditer(text):
            if self._overlaps(match.start(), match.end(), spans):
                continue

            spans.append((match.start(), match.end()))

            citations.append(Citation(
                type=CitationType.WEBSITE,
                status=CitationStatus.INCOMPLETE,
                raw_text=match.group(0),
                position_start=match.start(),
                position_end=match.end(),
                url=match.group(0),
            ))

        return citations

    def _assign_footnotes(self, citations: list[Citation], text: str) -> None:
        """Assign footnote numbers to citations based on document structure."""
        # A Word document carries real footnote numbers, written in front of each
        # note by the parser. When any are present they are the truth, and the
        # guess below, which would misread numbered headings and lines that begin
        # with a reporter volume, is skipped entirely.
        footnote_positions = []
        explicit = list(PATTERNS["footnote_marker_explicit"].finditer(text))
        if explicit:
            # Endnotes are numbered separately and would collide with footnotes.
            footnote_positions = [
                (int(m.group(2)), m.start()) for m in explicit if not m.group(1)
            ]
            endnote_positions = [
                (int(m.group(2)), m.start()) for m in explicit if m.group(1)
            ]
            footnote_positions += endnote_positions
        else:
            for match in PATTERNS["footnote_marker"].finditer(text):
                footnote_positions.append((int(match.group(1)), match.start()))

        footnote_positions.sort(key=lambda x: x[1])
        fn_positions = [pos for _, pos in footnote_positions]
        fn_numbers = [num for num, _ in footnote_positions]

        # Nearest footnote marker at or before each citation: a binary search per
        # citation instead of a scan from the top of the document.
        for citation in citations:
            i = bisect_right(fn_positions, citation.position_start) - 1
            current_footnote = fn_numbers[i] if i >= 0 else 0
            if current_footnote > 0:
                citation.footnote_number = current_footnote
