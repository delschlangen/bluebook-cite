"""
Bluebook 21st Edition formatting rules engine.

Two promises hold for everything this module prints. Nothing is invented: a formatted citation
is made only of what the document says or what a looked-up record says, and a part that is
missing is left out and named in `missing`, never filled with an empty pair of brackets or a
date nobody stated. And a citation that is not complete does not end with the full stop of a
finished one.
"""

import html
import re
from functools import lru_cache
from urllib.parse import urlparse

from ..models.citation import Citation, CitationContext, CitationType
from ..utils.bluebook_patterns import (
    abbreviate_party_name,
    get_court_abbreviation,
    get_journal_abbreviation,
    get_reporter_abbreviation,
)
from ..utils.field_guidance import guidance_for
from .citation_engine import ENGINE
from .transforms import bbdate, ordinal, titlecase

_TAGS = re.compile(r"<[^<>]{0,2000}>")
_SPACES = re.compile(r"\s+")


def clean_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities from text."""
    if not text:
        return text
    # Decode HTML entities like &lt; &gt; &amp;
    text = html.unescape(text)
    # Remove HTML tags like <i>, </i>, <b>, etc.
    text = _TAGS.sub("", text)
    return text.strip()


def _one_line(text: str) -> str:
    """A suggestion is one line: a line break carried in from a PDF's layout is a space."""
    return _SPACES.sub(" ", text).strip()


def _finished(text: str) -> str:
    """`text` with the full stop that ends a citation, unless it already ends with one
    ("et seq.", "Inc."): two in a row is never right."""
    return text if text.endswith(".") else text + "."


# Reporters that carry U.S. Supreme Court decisions, normalised. Rule 10.4: no court is named
# in the parenthetical of a citation to one of them.
_SCOTUS_REPORTERS = {"US", "SCT", "LED", "LED2D"}


def _is_scotus_reporter(reporter: str | None) -> bool:
    return bool(reporter) and "".join(c for c in reporter if c.isalnum()).upper() in _SCOTUS_REPORTERS


# The words of subsequent history set in italics (Rule 10.7, Table T8).
_HISTORY_PHRASE = re.compile(
    r"(?:cert\.|aff'd|rev'd|vacated|overruled|abrogated|superseded|reh'g|appeal|petition|review|modified|"
    r"enforced|remanded)[a-z'. ]{0,40}"
)
# More than one docket number: "14-1290, 14-1292", "08-4241/-4243", "22-2908(L)/22-2972".
_SEVERAL_DOCKETS = re.compile(r"[,/&]|\band\b")
# More than one section: a list or a range of section NUMBERS written with a word or an en dash
# ("553(b)–(c)" is a range within one section and takes one sign). A hyphen alone cannot be
# told from the hyphen inside one section number ("6-27-101"), so it does not count.
_SEVERAL_SECTIONS = re.compile(r"(?:,|–|\bto\b|\bthrough\b|\band\b) {0,2}-?\d")
_SECTION_SIGNS = re.compile(r"§{2}")


def missing_fields(citation: Citation) -> list[str]:
    """The parts a citation of this kind needs and this one does not have.

    For the kinds the data-driven engine recognised, the engine's own list stands. For the
    others (cases, statutes, articles, books, web pages) the answer depends on which form the
    citation takes: a case cited by docket number needs its court and the date of decision, not
    a volume and a page.
    """
    if citation.kind:
        return list(citation.missing or [])
    if citation.is_short_form:
        return []

    def lacks(*names: str) -> list[str]:
        return [n for n in names if getattr(citation, n, None) in (None, "", [])]

    if citation.type == CitationType.CASE:
        if not citation.parties:
            return ["parties"]
        if citation.volume and citation.reporter and citation.page:
            if citation.year:
                return []
            needs_court = not citation.court and not _is_scotus_reporter(citation.reporter)
            return (["court"] if needs_court else []) + ["year"]
        if citation.docket_number:
            return lacks("court") + ([] if citation.decision_date else ["date"])
        return lacks("volume", "reporter", "page", "year")
    if citation.type == CitationType.STATUTE:
        if citation.form == "session_law":
            return lacks("year", "code", "page")
        if citation.form == "public_law":
            return lacks("code", "section", "volume", "page")
        if (citation.code or "U.S.C.").replace(" ", "").upper().startswith("U.S.C"):
            return lacks("title_number", "section")
        # Rule 12.3.2: a state code is cited with the year of the code.
        return lacks("code", "section", "year")
    if citation.type == CitationType.LAW_REVIEW:
        return lacks("author", "title", "volume", "journal", "page", "year")
    if citation.type == CitationType.BOOK:
        return lacks("author", "title", "year")
    if citation.type == CitationType.WEBSITE:
        return lacks("title", "url")
    if citation.type == CitationType.LEGISLATIVE:
        # A committee print or report described in prose: its citation needs, at the least, the
        # number of the Congress, which a description does not give.
        return ["congress"]
    return []


_GAP_LABELS = {"date": "date of decision"}


def _gap(field: str) -> str:
    return f"[{_GAP_LABELS.get(field) or guidance_for(field)['label']}]"


class BluebookFormatter:
    """Formats citations according to Bluebook 21st Edition rules."""

    def format_citation(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format a citation based on its type.

        Also brings `missing` and `template` up to date for the kinds this module formats: a
        lookup may have filled a gap since the citation was found, and the list of what is
        still missing has to say so.
        """
        # Anything the data-driven engine recognised is rendered from its own template,
        # in the requested style. If a required part is missing there is nothing to
        # render, and the original text is returned rather than a citation with a hole.
        if citation.kind:
            style = "law_review" if is_law_review else "practitioner"
            rendered = ENGINE.render(citation.kind, citation.spec_fields or {}, style)
            return rendered if rendered is not None else _one_line(citation.raw_text)

        self.refresh_missing(citation)

        formatters = {
            CitationType.CASE: self.format_case,
            CitationType.STATUTE: self.format_statute,
            CitationType.LAW_REVIEW: self.format_law_review,
            CitationType.BOOK: self.format_book,
            CitationType.WEBSITE: self.format_website,
        }

        formatter = formatters.get(citation.type)
        if formatter:
            return _one_line(formatter(citation, is_law_review))
        return _one_line(citation.raw_text)

    # -- what is missing ------------------------------------------------------------------

    def refresh_missing(self, citation: Citation) -> None:
        """Set `missing` (and `template`, the finished shape with the gaps marked)."""
        if citation.kind:
            return
        citation.missing = missing_fields(citation)
        citation.template = self.gap_template(citation) if citation.missing else None

    def gap_template(self, citation: Citation) -> str | None:
        """The citation as it will read when finished, each missing part named in brackets."""
        gaps = set(citation.missing or [])

        def part(field: str, value) -> str:
            return _gap(field) if field in gaps or value in (None, "") else str(value)

        if citation.type == CitationType.CASE:
            name = f"*{self._case_name(citation)}*" if citation.parties else _gap("parties")
            if citation.docket_number and not (citation.volume and citation.reporter and citation.page):
                paren = " ".join(p for p in (part("court", citation.court), part("date", citation.decision_date)) if p)
                return f"{name}, {self._docket(citation.docket_number)} ({paren})."
            # Rule 10.4: the U.S. Supreme Court takes no court identifier, so the slot is
            # dropped rather than shown as a gap the reader must fill.
            if _is_scotus_reporter(citation.reporter):
                court = ""
            elif citation.court:
                court = f"{citation.court} "
            else:
                court = f"{_gap('court')} " if "court" in gaps or not citation.reporter else ""
            return (
                f"{name}, {part('volume', citation.volume)} {part('reporter', citation.reporter)} "
                f"{part('page', citation.page)} ({court}{part('year', citation.year)})."
            )
        if citation.type == CitationType.STATUTE:
            copy = citation.model_copy(update={"year": citation.year or _gap("year")}) if "year" in gaps else citation
            if "title_number" in gaps:
                copy = copy.model_copy(update={"title_number": _gap("title_number")})
            if "section" in gaps:
                copy = copy.model_copy(update={"section": _gap("section")})
            return _finished(self._statute_text(copy))
        if citation.type == CitationType.WEBSITE:
            head = ", ".join(p for p in (clean_html(citation.author or ""), f"*{part('title', citation.title)}*") if p)
            return f"{head}, {part('url', citation.url)}."
        if citation.type == CitationType.LAW_REVIEW:
            return (
                f"{part('author', citation.author)}, *{part('title', citation.title)}*, {part('volume', citation.volume)} "
                f"{part('journal', citation.journal)} {part('page', citation.page)} ({part('year', citation.year)})."
            )
        if citation.type == CitationType.BOOK:
            return f"{part('author', citation.author)}, {part('title', citation.title)} ({part('year', citation.year)})."
        return None

    # -- cases ----------------------------------------------------------------------------

    @staticmethod
    @lru_cache(maxsize=4096)
    def _party(party: str) -> str:
        """One party's name as Rule 10.2 sets it. (Remembered: abbreviating a name tries every
        word of Table T6 against it, and each case's name is needed twice, for the suggestion
        and for the template that marks what is missing.)"""
        words = party.split()
        if len(words) > 2 and words[-2] == "et" and words[-1] in ("al.", "al"):
            party = " ".join(words[:-2]).rstrip(",")              # Rule 10.2.1(a)
        # Rule 10.2.2: "United States" is written out when it is the whole of a party's name.
        if party in ("U.S.", "U. S.", "US"):
            return "United States"
        return abbreviate_party_name(party)

    def _case_name(self, citation: Citation) -> str:
        return " v. ".join(self._party(p) for p in (citation.parties or [])[:2] if p)

    @staticmethod
    def _docket(number: str) -> str:
        return f"{'Nos.' if _SEVERAL_DOCKETS.search(number) else 'No.'} {number}"

    def format_case(self, citation: Citation, is_law_review: bool = True) -> str:
        """
        Format case citation per Bluebook Rule 10.

        Law review format: Case Name, Vol. Reporter Page, Pincite (Court Year).
        Brief format: Case Name, Vol. Reporter Page, Pincite (Court Year)
        A case with no reporter yet is cited by docket: Case Name, No. X (Court Date) (Rule
        10.8.1). Whatever the document does not give is left out, never bracketed empty.
        """
        if not citation.parties or not any(citation.parties):
            return citation.raw_text

        # Format case name (Rule 10.2)
        case_name = self._case_name(citation)
        shown = f"*{case_name}*" if is_law_review else case_name

        if citation.is_short_form:
            # Rule 10.9: Name, Volume Reporter at Page.
            out = shown
            if citation.volume and citation.reporter:
                out += f", {citation.volume} {get_reporter_abbreviation(citation.reporter)}"
                if citation.pincite:
                    out += f" at {citation.pincite}"
            return _finished(out) if is_law_review else out

        pieces = [shown]
        has_reporter = bool(citation.volume and citation.reporter and citation.page)
        # "2020 WL 1234567" stands where a reporter would, and keeps its docket number in front.
        electronic = has_reporter and (citation.reporter == "WL" or "LEXIS" in citation.reporter)
        if citation.docket_number and (not has_reporter or electronic):
            pieces.append(self._docket(citation.docket_number))
        if citation.volume and citation.reporter and not citation.page:
            # "410 U.S. ___": decided, not yet paginated. The blank is the document's own.
            pieces.append(f"{citation.volume} {get_reporter_abbreviation(citation.reporter)} ___")
        if has_reporter:
            # Build reporter citation (Rule 10.3), with the pincite if present (Rule 10.3.2)
            cite = f"{citation.volume} {get_reporter_abbreviation(citation.reporter)} {citation.page}"
            if citation.pincite:
                cite += f", {citation.pincite}"
            pieces.append(cite)
        pieces.extend(citation.parallel_citations or [])
        out = ", ".join(pieces)

        # Build parenthetical (Rule 10.4). No year and no court: no parenthetical at all.
        paren = self._case_parenthetical(citation, has_reporter)
        if paren:
            out += f" ({paren})"
        if citation.subsequent_history:
            history = citation.subsequent_history
            phrase = _HISTORY_PHRASE.match(history) if is_law_review else None
            if phrase:
                history = f"*{phrase.group(0).rstrip()}*{history[len(phrase.group(0).rstrip()):]}"
            out += f", {history}"

        dated = bool(citation.year) and (has_reporter or bool(citation.docket_number))
        return _finished(out) if is_law_review and dated else out

    def _case_parenthetical(self, citation: Citation, has_reporter: bool) -> str:
        when = citation.decision_date or (str(citation.year) if citation.year else "")
        if has_reporter:
            court = self._format_court_year(citation.court, citation.year)
            if not court:
                return ""
            return court if not citation.decision_date else court.replace(str(citation.year), citation.decision_date)
        if not citation.court:
            return when
        return f"{get_court_abbreviation(citation.court)} {when}".strip()

    def _format_court_year(self, court: str | None, year: int | None) -> str:
        """Format court and year parenthetical per Rule 10.4."""
        if not year:
            return ""

        if not court:
            return str(year)

        # Get court abbreviation
        court_abbrev = get_court_abbreviation(court)

        # No court abbreviation needed for U.S. Supreme Court
        if court_abbrev == "" or "U.S." in (court or ""):
            return str(year)

        return f"{court_abbrev} {year}"

    # -- statutes -------------------------------------------------------------------------

    def _statute_text(self, citation: Citation) -> str:
        """A statute in the order its form requires, without the closing full stop."""
        code = citation.code or "U.S.C."
        section = str(citation.section or "")
        sign = "§§" if _SEVERAL_SECTIONS.search(section) or (
            "-" in section and _SECTION_SIGNS.search(citation.raw_text or "")
        ) else "§"
        year = citation.year
        paren = " ".join(str(p) for p in (citation.publisher, year) if p)
        form = citation.form

        if form == "session_law":
            base = " ".join(str(p) for p in (year, code, citation.page) if p)
            for parallel in citation.parallel_citations or []:
                base += f" (codified at {parallel})"
            return base
        if form == "public_law":
            base = f"{code}, {sign} {section}, {citation.volume} Stat. {citation.page}"
            if citation.pincite:
                base += f", {citation.pincite}"
            if year:
                base += f" ({year})"
            for parallel in citation.parallel_citations or []:
                base += f" (codified at {parallel})"
            return base
        if form in ("state_title", "state_chapter"):
            unit = "tit." if form == "state_title" else "ch."
            base = f"{code} {unit} {citation.title_number}, {sign} {section}"
        elif form == "no_sign":
            base = " ".join(str(p) for p in (citation.title_number, code, section) if p)
        elif citation.title_number:
            base = f"{citation.title_number} {code} {sign} {section}"
        else:
            base = f"{code} {sign} {section}"
        if citation.subsection:
            base += f"({citation.subsection})"
        return f"{base} ({paren})" if paren else base

    def format_statute(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format statute citation per Bluebook Rule 12."""
        if citation.form != "session_law" and not citation.section:
            return citation.raw_text
        if not citation.form and not citation.title_number and not citation.code:
            return citation.raw_text
        text = self._statute_text(citation)
        return text if missing_fields(citation) else _finished(text)

    # -- periodicals and books ------------------------------------------------------------

    def format_law_review(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format a periodical article: author, title, volume, journal, page, year.

        The journal is set in small capitals in law review footnotes, rendered here as
        capitals, and in ordinary type in a court document. The comma after the title
        is part of the form; leaving it out was a bug.
        """
        pieces: list[str] = []

        if citation.author:
            pieces.append(clean_html(citation.author))

        if citation.title:
            pieces.append(f"*{clean_html(citation.title)}*")

        if citation.volume and citation.journal and citation.page:
            journal = get_journal_abbreviation(citation.journal)
            if is_law_review:
                journal = journal.upper()
            cite = f"{citation.volume} {journal} {citation.page}"
            if citation.pincite:
                cite += f", {citation.pincite}"
            pieces.append(cite)

        if not pieces:
            return citation.raw_text

        out = ", ".join(pieces)
        if citation.year:
            out += f" ({citation.year})"
        return _finished(out)

    @staticmethod
    def _split_pinpoint(title: str) -> tuple[str, str]:
        """Separate a trailing pinpoint ("120", "§ 11.2", "at 45") from a title.

        The book pattern captures everything up to the parenthesis as the title, which
        swept the pinpoint in with it. The title is italic or capitalised on its own, and
        the pinpoint is always ordinary type, so the two have to be told apart.

        Done on the last two words of the title, not by searching the whole of it: the search
        retried from every run of spaces, which is quadratic (a 20 KB title held a request for
        nine seconds).
        """
        words = title.split()
        if len(words) < 2:
            return title.strip(), ""
        last = words[-1]
        if len(words) >= 3 and words[-2] in ("§", "§§", "¶", "¶¶", "at") and _PIN_WORD.fullmatch(last):
            return " ".join(words[:-2]), f"{words[-2]} {last}"
        if _PIN_WITH_SIGN.fullmatch(last):
            return " ".join(words[:-1]), last
        if last.isdigit() and len(last) <= 4:
            return " ".join(words[:-1]), last
        return title.strip(), ""

    def format_book(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format a book: author, title, pinpoint, edition and year.

        Law review footnotes set the author and the title in large and small capitals,
        rendered here as capitals. A court document uses ordinary type for the author
        and italics for the title. Both were wrong before: the author was left in
        ordinary type in law review style.
        """
        title, pin = self._split_pinpoint(clean_html(citation.title or ""))
        author = clean_html(citation.author or "")

        if is_law_review:
            author, title = author.upper(), title.upper()
        else:
            title = f"*{titlecase(title)}*" if title else title

        head = ", ".join(p for p in (author, title) if p)
        if pin:
            head += f" {pin}"

        paren = []
        if citation.edition:
            paren.append(f"{ordinal(citation.edition)} ed.")
        if citation.year:
            paren.append(str(citation.year))
        if paren:
            head += f" ({' '.join(paren)})"

        return _finished(head)

    # -- web pages ------------------------------------------------------------------------

    def format_website(self, citation: Citation, is_law_review: bool = True) -> str:
        """Format website citation per Bluebook Rule 18.2.2:
        Author, Title, Site Name (Mon. D, YYYY), URL.

        The date in the parenthetical is the page's own date of publication, from the page
        when it was looked up. "(last visited ...)" is printed only when the document itself
        says when its author looked at the page: a publication date printed under that label
        would state something nobody said.
        """
        parts = []

        if citation.author:
            parts.append(clean_html(citation.author))

        if citation.title:
            title = clean_html(citation.title)
            parts.append(f"*{title}*")

        published = bbdate(citation.publication_date) if citation.publication_date else ""
        site = clean_html(citation.site_name or "")
        if site and citation.url and site.lower() == urlparse(citation.url).netloc.lower():
            site = ""                 # the host name again is not the name of a site
        if site:
            site = site.upper() if is_law_review else site
            parts.append(f"{site} ({published})" if published else site)
        elif published and parts:
            parts[-1] += f" ({published})"

        if citation.url:
            address = citation.url
            if citation.access_date:
                address += f" (last visited {citation.access_date})"
            parts.append(address)

        if not parts:
            return citation.raw_text
        out = ", ".join(parts)
        # A bare address is not a finished citation and does not end like one.
        return out if missing_fields(citation) else _finished(out)


_PIN_WORD = re.compile(r"[\w.\-]{1,40}")
_PIN_WITH_SIGN = re.compile(r"[§¶]{1,2}[\w.\-]{1,40}")


class ShortFormManager:
    """
    Manages short form citations per Bluebook Rules 4 and 10.9.

    Key rules:
    - "Id." can only be used when citing to immediately preceding authority
    - "Id." cannot be used after a "see" or other signal citing multiple sources
    - Supra can be used after first full citation
    - Short case names must be distinctive
    """

    def __init__(self):
        self.citation_contexts: dict[str, CitationContext] = {}
        self.footnote_history: list[list[str]] = []
        self.current_footnote: int = 0

    def register_citation(self, citation: Citation, footnote_num: int) -> None:
        """Register a full citation for short form tracking."""
        context = CitationContext(
            citation_id=citation.id,
            first_occurrence_footnote=footnote_num,
            full_citation=citation.suggested_correction or citation.raw_text,
            last_used_footnote=footnote_num,
        )

        self.citation_contexts[citation.id] = context

        # Update footnote history
        while len(self.footnote_history) < footnote_num:
            self.footnote_history.append([])

        if footnote_num > 0:
            self.footnote_history[footnote_num - 1].append(citation.id)

    def can_use_id(
        self,
        citation_id: str,
        current_footnote: int,
        is_first_in_footnote: bool = True
    ) -> bool:
        """
        Check if "Id." can be used per Rule 4.1.

        Id. can be used when:
        1. Citing to immediately preceding citation (same footnote or previous)
        2. Previous footnote had only ONE source
        3. No intervening different citations
        """
        if current_footnote <= 0:
            return False

        if not is_first_in_footnote:
            # Check if previous citation in same footnote is the same source
            if current_footnote <= len(self.footnote_history):
                prev_cites = self.footnote_history[current_footnote - 1]
                if prev_cites and prev_cites[-1] == citation_id:
                    return True
            return False

        # Check previous footnote
        if current_footnote <= 1:
            return False

        prev_footnote_idx = current_footnote - 2
        if prev_footnote_idx >= len(self.footnote_history):
            return False

        prev_footnote_cites = self.footnote_history[prev_footnote_idx]

        # Id. requires exactly ONE citation in previous footnote
        if len(prev_footnote_cites) != 1:
            return False

        return prev_footnote_cites[0] == citation_id

    def get_short_form(
        self,
        citation: Citation,
        current_footnote: int,
        pincite: str | None = None
    ) -> tuple[str, str]:
        """
        Get appropriate short form for a citation.

        Returns: (short_form_type, formatted_citation)
        """
        context = self.citation_contexts.get(citation.id)
        if not context:
            return ("full", "")

        # Check for Id.
        if self.can_use_id(citation.id, current_footnote):
            if pincite:
                return ("id", f"Id. at {pincite}.")
            return ("id", "Id.")

        # For cases, use short case form
        if citation.type == CitationType.CASE:
            return ("short_case", self._format_short_case(citation, context, pincite))

        # For other types, use supra
        return ("supra", self._format_supra(citation, context, pincite))

    def _format_short_case(
        self,
        citation: Citation,
        context: CitationContext,
        pincite: str | None = None
    ) -> str:
        """Format short form case citation per Rule 10.9."""
        if not citation.parties:
            return f"supra note {context.first_occurrence_footnote}"

        # Use first party name if distinctive
        short_name = citation.parties[0]

        # Common non-distinctive names
        non_distinctive = ["United States", "State", "People", "Commonwealth", "City", "County"]

        if short_name in non_distinctive and len(citation.parties) > 1:
            short_name = citation.parties[1]

        # Abbreviate if needed
        short_name = abbreviate_party_name(short_name)

        if citation.volume and citation.reporter:
            base = f"*{short_name}*, {citation.volume} {citation.reporter}"
            if pincite:
                return f"{base} at {pincite}."
            elif citation.page:
                return f"{base} at {citation.page}."
            return f"{base}."

        return f"*{short_name}*, supra note {context.first_occurrence_footnote}."

    def _format_supra(
        self,
        citation: Citation,
        context: CitationContext,
        pincite: str | None = None
    ) -> str:
        """Format supra citation per Rule 4.2."""
        # Use hereinafter name if available
        if context.hereinafter_name:
            prefix = context.hereinafter_name
        elif citation.author:
            # Use author's last name
            prefix = citation.author.split()[-1]
        else:
            prefix = ""

        if prefix:
            base = f"{prefix}, supra note {context.first_occurrence_footnote}"
        else:
            base = f"supra note {context.first_occurrence_footnote}"

        if pincite:
            return f"{base}, at {pincite}."
        return f"{base}."
