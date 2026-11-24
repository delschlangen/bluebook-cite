"""The citation spec: every kind of citation the engine understands, as data.

Adding a citation type means adding an entry here. Nothing else changes: the same
spec is read by the Python engine and exported to the browser, so the two cannot
disagree about what a type is.

Each type has:
  id, label, family, citation_type   identity, and how documents classify it
  confidence                         high | medium | low  (see below)
  patterns                           how to recognise it (empty = guidance only)
  fields                             each part, the rule claimed for it, why it is there
  templates                          law_review, and practitioner where it differs
  example                            field values the interface renders as a worked example
  notes                              caveats worth showing next to a result

CONFIDENCE is a statement about how well the FORMAT is established, not about the code:
  high    the form is the same in every source consulted and matches an AALL, Bluebook
          quick-reference or library-guide example
  medium  consistent in the sources found, but typeface or a detail could not be checked
  low     taken from search summaries; shown as guidance, never as a correction

A field's `rule` is the number the sources gave. What a user SEES is decided by
app/utils/rules.py, which only displays verified numbers.

Template syntax is documented in app/services/spec_engine.py. Every optional field must
sit inside an <<optional block>>, or a missing one would be shown as a gap.
"""

from __future__ import annotations

import re

from .bluebook_patterns import STATE_ABBREVIATIONS
from .rules import EDITION_NOTE, VERIFIED_RULES

# --- building blocks -------------------------------------------------------


def field(name, label, rule, why, required=False):
    return {"name": name, "label": label, "rule": rule, "why": why, "required": required}


def pat(regex, flags="i", paste_only=False):
    return {"regex": regex, "flags": flags, "paste_only": paste_only}


_MONTH = r"[A-Za-z]{3,9}\.?"
_DATE = rf"{_MONTH}\s*\d{{1,2}},?\s*\d{{4}}"
_DATE_OR_ISO = rf"(?:{_DATE}|\d{{4}}-\d{{2}}-\d{{2}})"
_ROMAN_OR_NUM = r"[IVXLCivxlc]+|\d{1,2}"
_SUB = r"(?:\([A-Za-z0-9]+\))*"
_NUM_COMMA = r"\d{1,3}(?:,\d{3})+|\d+"

# Where a citation that begins with free text (an author's or agency's name) may start:
# the start of the input, a sentence or clause boundary, a new line, or straight after a
# signal. Without this, a pattern whose first group is "any capitalised words" starts at
# the first capital in the paragraph and swallows the prose in front of the citation.
# Each lookbehind is fixed-width, which both Python and JavaScript require.
_START = (
    r"(?:^|(?<=[.;:!?)]\s)|(?<=\n)|(?<=See )|(?<=See also )|(?<=Cf\. )"
    r"|(?<=Compare )|(?<=But see )|(?<=Accord )"
    r"|(?<=\bin )|(?<=\bby )|(?<=\bfrom )|(?<=\bto )|(?<=\bwith )|(?<=\bat )|(?<=\bof )|(?<=\band ))"
    # ...and the name itself may not BEGIN with a signal word. Otherwise the earliest
    # allowed start is the "S" of "See" and the signal is swallowed into the author.
    r"(?!(?:See|also|Cf|Compare|But|see|Accord)\b)"
)


def _state_alternation() -> str:
    names = list(STATE_ABBREVIATIONS) + list(STATE_ABBREVIATIONS.values())
    # Longest first so "North Carolina" is tried before "North", then alphabetical.
    # The tie-break matters: sorting out of a set leaves equal-length names in an order
    # that changes between runs, which made the exported spec differ every time.
    ordered = sorted(set(names), key=lambda n: (-len(n), n))
    return "|".join(re.escape(n) for n in ordered)


# --- families (grouping for the "browse citation types" view) --------------

FAMILIES = [
    {"id": "constitutions_rules", "label": "Constitutions and court rules"},
    {"id": "statutes", "label": "Statutes and session laws"},
    {"id": "admin", "label": "Regulations and executive materials"},
    {"id": "legislative", "label": "Legislative materials"},
    {"id": "reports", "label": "Reports"},
    {"id": "periodicals", "label": "Newspapers and periodicals"},
    {"id": "model_codes", "label": "Restatements and model codes"},
    {"id": "other", "label": "Treaties, court documents and unpublished works"},
]

CAUTION_LOW = (
    "This format comes from search summaries of law library guides, not from the Bluebook "
    "itself. Treat it as a starting point and confirm it against your edition."
)


def _federal_rule(rule_id, label, set_regex, short, example_rule, example_sub=""):
    """Federal rules of procedure and evidence share one shape."""
    return {
        "id": rule_id, "label": label, "family": "constitutions_rules",
        "citation_type": "statute", "confidence": "high",
        "patterns": [
            pat(rf"Fed(?:eral|\.)?\s*R(?:ules?|\.)?\s*(?:of\s+)?{set_regex}\s*(?P<rule>\d+)(?P<sub>{_SUB})"),
            pat(rf"\bFR{short[0]}\s*(?P<rule>\d+)(?P<sub>{_SUB})"),
        ],
        "fields": [
            field("rule", "rule number", "12.9.3", "The number of the rule.", True),
            field("sub", "subdivision", "12.9.3", "A subdivision such as (b)(6), written without spaces."),
        ],
        "templates": {"law_review": f"Fed. R. {short[1]} {{rule}}<<{{sub}}>>."},
        "example": {"rule": example_rule, "sub": example_sub},
        "notes": [],
    }


TYPES = [
    # --- constitutions -----------------------------------------------------
    {
        "id": "us_const_article", "label": "U.S. Constitution, article",
        "family": "constitutions_rules", "citation_type": "constitution", "confidence": "high",
        "patterns": [pat(
            rf"U\.?\s?S\.?\s*Const(?:itution|\.)?\s*,?\s*art(?:icle|\.)?\s*(?P<article>{_ROMAN_OR_NUM})"
            r"(?:\s*,?\s*(?:§+|sec(?:tion|\.)?)\s*(?P<section>\d+))?"
            r"(?:\s*,?\s*cl(?:ause|\.)?\s*(?P<clause>\d+))?"
        )],
        "fields": [
            field("article", "article number", "11", "Articles are cited in roman numerals: art. I, not art. 1.", True),
            field("section", "section", "11", "The section, after the § symbol."),
            field("clause", "clause", "11", "The clause, written cl. and the number."),
        ],
        "templates": {"law_review": "U.S. Const. art. {article|roman}<<, § {section}>><<, cl. {clause}>>."},
        "example": {"article": "I", "section": "8", "clause": "3"},
        "notes": [],
    },
    {
        "id": "us_const_amendment", "label": "U.S. Constitution, amendment",
        "family": "constitutions_rules", "citation_type": "constitution", "confidence": "high",
        "patterns": [pat(
            rf"U\.?\s?S\.?\s*Const(?:itution|\.)?\s*,?\s*amend(?:ment|\.)?\s*(?P<amendment>{_ROMAN_OR_NUM})"
            r"(?:\s*,?\s*(?:§+|sec(?:tion|\.)?)\s*(?P<section>\d+))?"
            r"(?:\s*,?\s*cl(?:ause|\.)?\s*(?P<clause>\d+))?"
        )],
        "fields": [
            field("amendment", "amendment number", "11", "Amendments are cited in roman numerals: amend. XIV, not amend. 14.", True),
            field("section", "section", "11", "The section, after the § symbol."),
            field("clause", "clause", "11", "The clause, written cl. and the number."),
        ],
        "templates": {"law_review": "U.S. Const. amend. {amendment|roman}<<, § {section}>><<, cl. {clause}>>."},
        "example": {"amendment": "XIV", "section": "1"},
        "notes": [],
    },
    {
        "id": "state_const", "label": "State constitution",
        "family": "constitutions_rules", "citation_type": "constitution", "confidence": "medium",
        "patterns": [pat(
            rf"(?P<state>{_state_alternation()})\s*Const(?:itution|\.)?\s*,?\s*art(?:icle|\.)?\s*(?P<article>{_ROMAN_OR_NUM})"
            r"(?:\s*,?\s*(?:§+|sec(?:tion|\.)?)\s*(?P<section>\d+))?"
        )],
        "fields": [
            field("state", "state", "11", "The state, abbreviated per Table T10.", True),
            field("article", "article number", "11", "Articles are cited in roman numerals.", True),
            field("section", "section", "11", "The section, after the § symbol."),
        ],
        "templates": {"law_review": "{state|state_abbr} Const. art. {article|roman}<<, § {section}>>."},
        "example": {"state": "Washington", "article": "I", "section": "7"},
        "notes": ["Amendments to a state constitution use \"amend.\" in place of \"art.\"; only articles are recognised here."],
    },
    # --- federal rules -----------------------------------------------------
    _federal_rule("fed_r_civ_p", "Federal Rules of Civil Procedure", r"Civ(?:il|\.)?\s*P(?:rocedure|\.)?", ("CP", "Civ. P."), "12", "(b)(6)"),
    _federal_rule("fed_r_crim_p", "Federal Rules of Criminal Procedure", r"Crim(?:inal|\.)?\s*P(?:rocedure|\.)?", ("CrP", "Crim. P."), "7", "(b)"),
    _federal_rule("fed_r_evid", "Federal Rules of Evidence", r"Evid(?:ence|\.)?", ("E", "Evid."), "801", "(d)(2)"),
    _federal_rule("fed_r_app_p", "Federal Rules of Appellate Procedure", r"App(?:ellate|\.)?\s*P(?:rocedure|\.)?", ("AP", "App. P."), "4", "(a)(1)"),
    # --- statutes ----------------------------------------------------------
    {
        "id": "public_law", "label": "Federal session law (Public Law)",
        "family": "statutes", "citation_type": "statute", "confidence": "medium",
        "patterns": [
            pat(
                r"^(?:See(?:\s+also)?,?\s+)?(?P<act>[A-Z][^,()]{3,120}?),\s*Pub(?:lic|\.)?\s*L(?:aw|\.)?\s*(?:No\.?\s*)?"
                r"(?P<pl>\d{2,3}-\d{1,4}),\s*(?P<volume>\d{1,3})\s*Stat\.?\s*(?P<page>\d+)"
                r"(?:,\s*(?P<pin>\d+))?(?:\s*\((?P<year>\d{4})\))?",
                paste_only=True,
            ),
            pat(
                r"Pub(?:lic|\.)?\s*L(?:aw|\.)?\s*(?:No\.?\s*)?(?P<pl>\d{2,3}-\d{1,4}),\s*(?P<volume>\d{1,3})\s*Stat\.?\s*(?P<page>\d+)"
                r"(?:,\s*(?P<pin>\d+))?(?:\s*\((?P<year>\d{4})\))?"
            ),
        ],
        "fields": [
            field("act", "name of the Act", "12.4", "The Act's name, when you are citing it by name."),
            field("pl", "Public Law number", "12.4", "The Congress and law number, such as 111-148.", True),
            field("volume", "Statutes at Large volume", "12.4", "The volume of the Statutes at Large.", True),
            field("page", "first page", "12.4", "The page the law begins on in the Statutes at Large.", True),
            field("pin", "pinpoint page", "12.4", "The page you are relying on."),
            field("year", "year", "12.4", "The year of enactment. Leave it out only if the Act's name already contains the year."),
        ],
        "templates": {"law_review": "<<{act}, >>Pub. L. No. {pl}, {volume} Stat. {page}<<, {pin}>><< ({year})>>."},
        "example": {"act": "Department of Transportation Act", "pl": "89-670", "volume": "80", "page": "931", "year": "1966"},
        "notes": [
            "Cite the codified statute (U.S.C.) instead unless the law is too new, uncodified, or repealed.",
            "The year is required unless the Act's name already includes it, so it is not demanded here.",
        ],
    },
    # --- regulations and executive materials -------------------------------
    {
        "id": "cfr", "label": "Code of Federal Regulations",
        "family": "admin", "citation_type": "regulation", "confidence": "high",
        "patterns": [pat(
            rf"(?P<title>\d{{1,2}})\s*C\.?\s?F\.?\s?R\.?\s*(?:§+)?\s*(?P<section>\d+(?:\.\d+)?)(?P<sub>{_SUB})"
            r"(?:\s*\((?P<year>\d{4})\))?"
        )],
        "fields": [
            field("title", "title number", "14.2", "The C.F.R. title, the number before C.F.R.", True),
            field("section", "section", "14.2", "The section, after the § symbol.", True),
            field("sub", "subdivision", "14.2", "A subdivision such as (a)(1), written without spaces."),
            field("year", "year", "14.2", "The year of the C.F.R. edition. Unlike the U.S. Code, it is required.", True),
        ],
        "templates": {"law_review": "{title} C.F.R. § {section}<<{sub}>> ({year})."},
        "example": {"title": "40", "section": "261.4", "sub": "(b)", "year": "2021"},
        "notes": ["The year is the year of the C.F.R. edition you consulted, not the year the rule was issued."],
    },
    {
        "id": "federal_register", "label": "Federal Register",
        "family": "admin", "citation_type": "regulation", "confidence": "high",
        "patterns": [
            pat(
                r"^(?:See(?:\s+also)?,?\s+)?(?P<name>[A-Z][^()]{3,160}?),\s*(?P<volume>\d{1,3})\s*Fed\.?\s*Reg\.?\s*"
                rf"(?P<page>{_NUM_COMMA})(?:,\s*(?P<pin>{_NUM_COMMA}))?(?:\s*\((?P<date>{_DATE_OR_ISO})\))?",
                paste_only=True,
            ),
            pat(
                rf"(?P<volume>\d{{1,3}})\s*Fed\.?\s*Reg\.?\s*(?P<page>{_NUM_COMMA})"
                rf"(?:,\s*(?P<pin>{_NUM_COMMA}))?(?:\s*\((?P<date>{_DATE_OR_ISO})\))?"
            ),
        ],
        "fields": [
            field("name", "name of the rule", "14.2", "The title of the rule or notice."),
            field("volume", "volume number", "14.2", "The Federal Register volume.", True),
            field("page", "first page", "14.2", "The page the document begins on.", True),
            field("pin", "pinpoint page", "14.2", "The page you are relying on."),
            field("date", "full date", "14.2", "The complete date of publication. A year alone is not enough.", True),
        ],
        "templates": {"law_review": "<<{name}, >>{volume} Fed. Reg. {page|thousands}<<, {pin|thousands}>> ({date|bbdate})."},
        "example": {"name": "Importation of Fruits and Vegetables", "volume": "60", "page": "50379", "pin": "50381", "date": "Sept. 29, 1995"},
        "notes": [],
    },
    {
        "id": "executive_order", "label": "Executive order",
        "family": "admin", "citation_type": "regulation", "confidence": "medium",
        # More specific than a bare Federal Register cite, which would otherwise tie
        # with it by reading "Exec. Order No. 13,769" as the name of a rule.
        "priority": 5,
        "patterns": [pat(
            rf"(?:Executive\s+Order|Exec\.?\s*Order)\s*(?:No\.?\s*)?(?P<number>\d{{1,3}}(?:,\d{{3}})+|\d{{3,5}})"
            rf"(?:,\s*(?P<volume>\d{{1,3}})\s*Fed\.?\s*Reg\.?\s*(?P<page>{_NUM_COMMA})(?:\s*\((?P<date>{_DATE_OR_ISO})\))?)?"
        )],
        "fields": [
            field("number", "order number", "14.2", "The executive order number.", True),
            field("volume", "Federal Register volume", "14.2", "The volume where the order was published.", True),
            field("page", "Federal Register page", "14.2", "The page where the order begins.", True),
            field("date", "full date", "14.2", "The complete date of publication.", True),
        ],
        "templates": {"law_review": "Exec. Order No. {number|thousands}, {volume} Fed. Reg. {page|thousands} ({date|bbdate})."},
        "example": {"number": "13769", "volume": "82", "page": "8977", "date": "Feb. 1, 2017"},
        "notes": ["Older orders are cited to 3 C.F.R. instead of the Federal Register; that form is not covered here."],
    },
    # --- legislative -------------------------------------------------------
    {
        "id": "bill", "label": "Federal bill (unenacted)",
        "family": "legislative", "citation_type": "legislative", "confidence": "high",
        "patterns": [pat(
            r"(?<![A-Za-z.])(?P<chamber>H\.?\s?R\.?|S\.?)\s*(?P<number>\d{1,5}),?\s*(?P<congress>\d{2,3})(?:st|nd|rd|th|d)?\s*Cong\.?"
            r"(?:\s*§+\s*(?P<section>\d+))?(?:\s*\((?P<year>\d{4})\))?"
        )],
        "fields": [
            field("chamber", "chamber", "13.2", "H.R. for the House, S. for the Senate.", True),
            field("number", "bill number", "13.2", "The number of the bill.", True),
            field("congress", "Congress", "13.2", "Which Congress, such as 117th.", True),
            field("section", "section", "13.2", "A section of the bill, if you are citing one."),
            field("year", "year", "13.2", "The year the bill was introduced.", True),
        ],
        "templates": {"law_review": "{chamber|chamber} {number}, {congress|ordinal} Cong.<< § {section}>> ({year})."},
        "example": {"chamber": "S.", "number": "516", "congress": "105", "section": "2", "year": "1997"},
        "notes": ["Resolutions (H.J. Res., S. Con. Res. and the like) use forms that could not be confirmed and are not covered."],
    },
    {
        "id": "committee_report", "label": "Congressional committee report",
        "family": "legislative", "citation_type": "legislative", "confidence": "high",
        "patterns": [pat(
            r"(?<![A-Za-z.])(?P<chamber>H\.?\s?R\.?|S\.?)\s*Rep\.?\s*(?:No\.?\s*)?(?P<number>\d{2,3}-\d{1,4})"
            r"(?:,\s*(?:at\s+)?(?P<pin>\d+(?:-\d+)?))?(?:\s*\((?P<year>\d{4})\))?"
        )],
        "fields": [
            field("chamber", "chamber", "13.4", "H.R. for a House report, S. for a Senate report.", True),
            field("number", "report number", "13.4", "The Congress and report number, such as 116-123.", True),
            field("pin", "pinpoint page", "13.4", "The page you are relying on."),
            field("year", "year", "13.4", "The year the report was issued.", True),
        ],
        "templates": {"law_review": "{chamber|chamber} Rep. No. {number}<<, at {pin}>> ({year})."},
        "example": {"chamber": "H.R.", "number": "109-447", "year": "2006"},
        "notes": [],
    },
    {
        "id": "cong_rec_daily", "label": "Congressional Record (daily edition)",
        "family": "legislative", "citation_type": "legislative", "confidence": "high",
        "patterns": [pat(
            rf"(?P<volume>\d{{2,3}})\s*Cong\.?\s*Rec\.?\s*(?P<page>[A-Z]\d[\d,]*|\d[\d,]*)\s*\(\s*daily\s*ed\.?\s*(?P<date>{_DATE})\s*\)"
        )],
        "fields": [
            field("volume", "volume number", "13.5", "The Congressional Record volume.", True),
            field("page", "page", "13.5", "The page, including its letter prefix in the daily edition.", True),
            field("date", "full date", "13.5", "The complete date of the daily issue.", True),
        ],
        "templates": {"law_review": "{volume} Cong. Rec. {page|thousands} (daily ed. {date|bbdate})."},
        "example": {"volume": "168", "page": "H3", "date": "Jan. 6, 2022"},
        "notes": ["Cite the bound edition once it is published."],
    },
    {
        "id": "cong_rec_bound", "label": "Congressional Record (bound edition)",
        "family": "legislative", "citation_type": "legislative", "confidence": "high",
        "patterns": [pat(
            r"(?P<volume>\d{2,3})\s*Cong\.?\s*Rec\.?\s*(?P<page>\d[\d,]*)(?:\s*\((?P<year>\d{4})\))?"
        )],
        "fields": [
            field("volume", "volume number", "13.5", "The Congressional Record volume.", True),
            field("page", "page", "13.5", "The page number.", True),
            field("year", "year", "13.5", "The year of the bound volume.", True),
        ],
        "templates": {"law_review": "{volume} Cong. Rec. {page|thousands} ({year})."},
        "example": {"volume": "123", "page": "12455", "year": "1977"},
        "notes": [],
    },
    # --- reports -----------------------------------------------------------
    {
        "id": "agency_report", "label": "Government report (GAO, CRS)",
        "family": "reports", "citation_type": "other", "confidence": "high",
        "patterns": [
            pat(
                _START + r"(?P<author>[A-Z][A-Za-z'&.\-]*(?:\s+(?:(?:of|for|and|the|on|&)\s+)*[A-Z][A-Za-z'&.\-]*){0,9}?)\s*,\s*(?P<number>GAO-\d{2}-\d+[A-Za-z]*|R[LS]?\d{5}|IF\d{5}|IN\d{5})\s*,\s*"
                r"(?P<title>[^()]+?)\s*\((?P<year>\d{4})\)",
                flags="",
            ),
            pat(
                r"^(?:See\s+(?:also\s+)?)?(?P<author>[A-Z][A-Za-z'&.\-]*(?:\s+(?:(?:of|for|and|the|on|&)\s+)*[A-Z][A-Za-z'&.\-]*){0,9}?)\s*,\s*(?P<number>GAO-\d{2}-\d+[A-Za-z]*|R[LS]?\d{5}|IF\d{5}|IN\d{5})\s*,\s*"
                r"(?P<title>[A-Za-z0-9\"'][^()\n]*?[A-Za-z0-9\"'?!])\.?\s*$",
                flags="",
                paste_only=True,
            ),
            pat(r"(?P<number>GAO-\d{2}-\d+[A-Za-z]*)", flags="", paste_only=True),
        ],
        "fields": [
            field("author", "agency", "15.1", "The agency that issued the report, abbreviated per Table T6.", True),
            field("number", "report number", "15", "The agency's own number for the report, such as GAO-16-552.", True),
            field("title", "title", "15", "The full title as printed on the report, capitalized per Rule 8.", True),
            field("year", "year", "15", "The year the report was issued.", True),
        ],
        "templates": {
            "law_review": "{author|institution|smallcaps}, {number}, {title|titlecase|smallcaps} ({year}).",
            "practitioner": "{author|decaps|institution}, {number}, {title|decaps|titlecase|italic} ({year}).",
        },
        "example": {
            "author": "U.S. Gov't Accountability Off.", "number": "GAO-16-552",
            "title": "Firearms Data: ATF Did Not Always Comply with the Appropriations Act Restrictions", "year": "2016",
        },
        "notes": [
            "The agency name is kept as you typed it, apart from standard Table T6 abbreviations.",
            "Text typed in capitals is converted to ordinary case in court-document style. Acronyms the tool does not recognise may need their capitals restored.",
        ],
    },
    # --- periodicals -------------------------------------------------------
    {
        "id": "newspaper_article", "label": "Newspaper article",
        "family": "periodicals", "citation_type": "newspaper", "confidence": "medium",
        "patterns": [pat(
            r"^(?:(?P<author>[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3}(?:\s*(?:&|and)\s*[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})?),\s*)?"
            r"(?P<title>.{3,200}?),\s*(?P<paper>(?:The\s+)?(?:New York Times|N\.?\s?Y\.? Times|Washington Post|Wash\. Post|Wall Street Journal|Wall St\. J\.|"
            r"Los Angeles Times|L\.?\s?A\.? Times|USA Today|Boston Globe|Bos\. Globe|Chicago Tribune|Chi\. Trib\.)),\s*"
            rf"(?P<date>{_DATE}),\s*at\s*(?P<page>[A-Z]?\d{{1,3}})",
            paste_only=True,
        )],
        "fields": [
            field("author", "author", "16", "The reporter's full name, if the article is signed."),
            field("title", "article title", "16", "The headline, capitalized per Rule 8.", True),
            field("paper", "newspaper", "16", "The newspaper's name, abbreviated, without a leading \"The\".", True),
            field("date", "full date", "16", "The full date the article ran.", True),
            field("page", "page", "16", "The page, with its section letter, such as A1.", True),
        ],
        "templates": {
            "law_review": "<<{author}, >>*{title|titlecase}*, {paper|paper|smallcaps}, {date|bbdate}, at {page}.",
            "practitioner": "<<{author}, >>*{title|titlecase}*, {paper|paper}, {date|bbdate}, at {page}.",
        },
        "example": {"author": "Jane Doe", "title": "Court Rules on Speech Case", "paper": "N.Y. Times", "date": "June 15, 1990", "page": "A1"},
        "notes": ["Online-only articles use a different form, with a URL; it is not covered here."],
    },
    # --- restatements and model codes --------------------------------------
    {
        "id": "restatement", "label": "Restatement",
        "family": "model_codes", "citation_type": "other", "confidence": "medium",
        "patterns": [pat(
            r"Restatement\s*\((?P<series>First|Second|Third|Fourth)\)\s*(?:of\s+)?(?P<subject>[A-Za-z][A-Za-z&'\- ]{2,70}?)\s*§+\s*(?P<section>[\w.\-]+)"
            r"(?:\s*cmt\.?\s*(?P<comment>[A-Za-z0-9]+))?(?:\s*\((?:Am\.?\s*L\.?\s*Inst\.?|A\.?L\.?I\.?)\s*(?P<year>\d{4})\))?"
        )],
        "fields": [
            field("series", "series", "12", "First, Second, Third or Fourth.", True),
            field("subject", "subject", "12", "The subject, such as Torts or Contracts.", True),
            field("section", "section", "12", "The section, after the § symbol.", True),
            field("comment", "comment", "12", "A comment, written cmt. and its letter."),
            field("year", "year", "12", "The year the Restatement was adopted.", True),
        ],
        "templates": {
            "law_review": "RESTATEMENT ({series|upper}) OF {subject|upper} § {section}<< cmt. {comment}>> (Am. L. Inst. {year}).",
            "practitioner": "Restatement ({series|titlecase}) of {subject|titlecase_mid} § {section}<< cmt. {comment}>> (Am. L. Inst. {year}).",
        },
        "example": {"series": "Second", "subject": "Torts", "section": "402A", "year": "1965"},
        "notes": ["The 22nd edition may abbreviate the institution as A.L.I.; confirm in your edition."],
    },
    {
        "id": "model_penal_code", "label": "Model Penal Code",
        "family": "model_codes", "citation_type": "other", "confidence": "medium",
        "patterns": [pat(
            r"Model\s*Penal\s*Code\s*§+\s*(?P<section>[\w.\-]+)(?:\s*cmt\.?\s*(?P<comment>[A-Za-z0-9]+))?"
            r"(?:\s*\((?:Am\.?\s*L\.?\s*Inst\.?|A\.?L\.?I\.?)\s*(?P<year>\d{4})\))?"
        )],
        "fields": [
            field("section", "section", "12", "The section, after the § symbol.", True),
            field("comment", "comment", "12", "A comment, written cmt. and its letter."),
            field("year", "year", "12", "The year of the version you are citing.", True),
        ],
        "templates": {
            "law_review": "MODEL PENAL CODE § {section}<< cmt. {comment}>> (Am. L. Inst. {year}).",
            "practitioner": "Model Penal Code § {section}<< cmt. {comment}>> (Am. L. Inst. {year}).",
        },
        "example": {"section": "2.02", "year": "1985"},
        "notes": ["The 22nd edition may abbreviate the institution as A.L.I.; confirm in your edition."],
    },
    {
        "id": "ucc", "label": "Uniform Commercial Code",
        "family": "model_codes", "citation_type": "other", "confidence": "medium",
        "patterns": [pat(
            r"U\.?\s?C\.?\s?C\.?\s*§+\s*(?P<section>\d[\w.\-]*)"
            r"(?:\s*\(Am\.?\s*L\.?\s*Inst\.?\s*&\s*Unif\.?\s*L\.?\s*Comm['’]n\s*(?P<year>\d{4})\))?"
        )],
        "fields": [
            field("section", "section", "12", "The section, such as 2-207.", True),
            field("year", "year", "12", "The year of the version you are citing.", True),
        ],
        "templates": {"law_review": "U.C.C. § {section} (Am. L. Inst. & Unif. L. Comm'n {year})."},
        "example": {"section": "2-207", "year": "1977"},
        "notes": [],
    },
    # --- guidance only: shown in the browse view, never used to "correct" input ---
    {
        "id": "hearing", "label": "Congressional hearing",
        "family": "legislative", "citation_type": "legislative", "confidence": "medium",
        "patterns": [],
        "fields": [
            field("title", "hearing title", "13.3", "The title of the hearing.", True),
            field("bill", "bill number", "13.3", "The bill the hearing concerned, if any."),
            field("committee", "committee", "13.3", "The committee, abbreviated.", True),
            field("congress", "Congress", "13.3", "Which Congress, such as 117th.", True),
            field("page", "page", "13.3", "The page you are relying on."),
            field("year", "year", "13.3", "The year of the hearing.", True),
        ],
        "templates": {
            "law_review": "{title|titlecase}<<: Hearing on {bill}>> Before the {committee}, {congress|ordinal} Cong.<< {page}>> ({year}).",
            "practitioner": "*{title|titlecase}*<<: Hearing on {bill}>> Before the {committee}, {congress|ordinal} Cong.<< {page}>> ({year}).",
        },
        "example": {"title": "The Safe Port Act", "bill": "H.R. 4954", "committee": "Subcomm. on Economic Security, Infrastructure Protection, and Cybersecurity of the H. Comm. on Homeland Security", "congress": "109", "year": "2006"},
        "notes": [CAUTION_LOW, "Subcommittee and committee names are abbreviated per Table T6."],
    },
    {
        "id": "state_statute", "label": "State statute",
        "family": "statutes", "citation_type": "statute", "confidence": "low",
        "patterns": [],
        "fields": [
            field("code", "code name", "12", "The state code, abbreviated as in Table T1.", True),
            field("section", "section", "12", "The section, after the § symbol.", True),
            field("year", "year", "12", "The year of the code. Unlike the federal code, it is required for state codes.", True),
        ],
        "templates": {"law_review": "{code} § {section} ({year})."},
        "example": {"code": "Ohio Rev. Code Ann.", "section": "3503.06", "year": "2022"},
        "notes": [CAUTION_LOW, "Table T1 gives each state's code name and whether a publisher appears in the parenthetical."],
    },
    {
        "id": "treaty_bilateral", "label": "Treaty (bilateral)",
        "family": "other", "citation_type": "other", "confidence": "low",
        "patterns": [],
        "fields": [
            field("name", "name of the agreement", "21.4", "The title of the treaty.", True),
            field("parties", "parties", "21.4", "The countries, joined by a dash and abbreviated.", True),
            field("date", "date of signing", "21.4", "The full date the treaty was signed.", True),
            field("source", "treaty source", "21.4", "Where it is published, such as T.I.A.S. No. 12345.", True),
        ],
        "templates": {"law_review": "{name}, {parties}, {date|bbdate}, {source}."},
        "example": {"name": "Agreement on Trade", "parties": "U.S.-U.K.", "date": "Mar. 3, 1990", "source": "T.I.A.S. No. 11,000"},
        "notes": [CAUTION_LOW, "The source order changed between the 21st and 22nd editions."],
    },
    {
        "id": "record_cite", "label": "Record citation (brief)",
        "family": "other", "citation_type": "other", "confidence": "low",
        "patterns": [],
        "fields": [
            field("record", "record abbreviation", "B17", "The record's abbreviation, such as J.A. or R.", True),
            field("page", "page", "B17", "The page of the record.", True),
        ],
        "templates": {"law_review": "{record} at {page}."},
        "example": {"record": "J.A.", "page": "12"},
        "notes": [CAUTION_LOW, "Used in briefs and court documents (Bluepages), not in law review footnotes."],
    },
]


def build_spec() -> dict:
    """The complete spec as plain data, ready to export to the browser."""
    return {
        "types": TYPES,
        "families": FAMILIES,
        "rules": VERIFIED_RULES,
        "edition_note": EDITION_NOTE,
    }


SPEC = build_spec()
