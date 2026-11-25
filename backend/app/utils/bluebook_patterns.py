"""
Comprehensive Bluebook citation patterns and abbreviations.
Based on Bluebook 21st Edition.
"""

import re
from re import Pattern

# Reporter abbreviations that must never be mistaken for a footnote marker.
_REPORTER_LOOKAHEAD = (
    r"(?:U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.|F\.\s?(?:Supp\.|App'x|\dd|\dth)|F\.|"
    r"N\.\s?E\.|N\.\s?W\.|S\.\s?E\.|S\.\s?W\.|So\.|P\.\s?\dd|P\.|A\.\s?\dd|A\.|"
    r"Cal\.|N\.\s?Y\.|U\.\s?S\.\s?C|C\.\s?F\.\s?R|Stat\.|Fed\.)"
)

# --- Shapes shared by several patterns --------------------------------------------------------
#
# Every repetition below is bounded, and no two neighbouring repetitions can match the same
# characters. An unbounded one makes a failed match retry from each possible starting point,
# which is quadratic in the length of any run that never breaks: well under 100 KB of odd but
# plausible text (capitals with no punctuation, one very long token) took tens of seconds and
# froze the whole server, because a regular expression holds the interpreter lock for the whole
# of one match. tests/test_regex_floods.py runs every pattern here over floods of one repeated
# shape; add a flood there for every new shape a pattern accepts.

# A page or range of pages, with the footnote form the Bluebook uses for a pin cite to a note:
# "153", "842-43", "152 n.4", "152 & n.4", "140 nn.3-4". (En dashes are hyphens by the time a
# pattern sees them: see text_normalize.) The lookaheads stop the engine from giving back a digit
# to make a later part fit, and keep ", 93 S. Ct. 705" from being read as a pin cite of 93.
_PIN = (
    r"\d{1,6}(?:-\d{1,6})?(?![\d-])"
    r"(?:\s{1,2}(?:&\s)?nn?\.\s?\d{1,4}(?:-\d{1,4})?(?!\d))?"
    r"(?!\s{1,2}[A-Z])"
)
_PINS = rf"{_PIN}(?:,\s{{1,2}}{_PIN}){{0,5}}"

# A section number and the subsections after it: "922(g)(1)", "2C:58-33", "59.1-148.5", "898-a",
# "505/2DDDD". It starts with a digit and ends with a letter or digit, so a sentence's own full
# stop is never taken into it.
_SECTION = r"\d(?:[0-9A-Za-z.:/\-]{0,28}[0-9A-Za-z])?(?:\([0-9A-Za-z]{1,5}\)){0,8}"
# What may follow the first section: the end of a range ("to 898-e", "to -35", "-(c)", "through
# 706") or the next item of a list (", 1346(a)(2)", "and 1367"). A list item may not be followed
# by a capitalised word, which is how ", 134 Stat. 281" and ", 28 U.S.C." are left alone.
_SECTION_MORE = (
    rf"(?:\s{{0,2}}(?:-|\bto\b|\bthrough\b)\s{{0,2}}(?:-?{_SECTION}|(?:\([0-9A-Za-z]{{1,5}}\)){{1,8}})"
    rf"|,?\s{{1,2}}and\s{{1,2}}{_SECTION}(?!\s{{1,2}}[A-Z])"
    rf"|,\s{{1,2}}{_SECTION}(?!\s{{1,2}}[A-Z]))"
)
_SECTIONS = rf"{_SECTION}(?:{_SECTION_MORE}){{0,8}}"

# A reporter citation after a case name, read from where the name ends. The two patterns are only
# ever applied there (with .match), never searched for through a document.
_REPORTER_CITE = r"(\d{1,5})\s{1,3}([A-Z][a-zA-Z\.\s\d]{0,40}?[a-zA-Z\.\d])\s{1,3}(\d{1,6})"

# Citation detection patterns
PATTERNS: dict[str, Pattern] = {
    # ", Volume Reporter Page[, Pin] (Court Year)" after a case name.
    "case_tail_complete": re.compile(
        rf",\s{{0,3}}{_REPORTER_CITE}(?:,\s{{0,3}}(\d{{1,6}}(?:-\d{{1,6}})?))?\s{{0,3}}\(([^)]{{1,200}})\)"
    ),
    # A reporter citation with no year parenthetical, e.g. "Brandenburg v Ohio 395 US 444". The
    # volume, reporter and page are all present and must be recognised as such rather than
    # reported missing.
    "case_tail_no_year": re.compile(
        rf",?\s{{1,3}}{_REPORTER_CITE}(?!\s{{0,3}}[\d,]{{0,12}}\s{{0,3}}\()"
    ),

    # Federal statutes: Title U.S.C. § Section
    # The lookbehind keeps a match from starting in the middle of a run of digits. Without it a
    # failed match retried from every digit of the run, and each retry read to the end of it:
    # quadratic, so 32,000 digits took 7 s and 100,000 never finished, with the interpreter lock
    # held the whole time (nothing else on the server could run).
    "statute_usc": re.compile(
        r"(?<!\d)(\d+)\s+U\.?S\.?C\.?\s*§+\s*(\d+[a-z]?)(?:\(([^)]+)\))?"
    ),

    # State statutes (generic pattern)
    "statute_state": re.compile(
        r"([A-Z][a-z]{1,30}\.?\s+(?:Rev\.?\s+)?(?:Code|Stat)\.?\s*(?:Ann\.?)?\s*)"
        r"§+\s*(\d+(?:[-.]\d+)*)"
    ),

    # Law review articles: Author, Title, Volume Journal Page (Year)
    "law_review": re.compile(
        r"([A-Z][a-zA-Z\.\s]{1,100}),\s+"
        r"([^,]{1,250}),\s+"
        r"(\d+)\s+([A-Z][a-zA-Z\.\s&]{1,100}(?:L\.|Law|J\.|Journal|Rev\.|Review)[a-zA-Z\.\s]{0,40})\s+"
        r"(\d+)(?:,\s*(\d+(?:-\d+)?))?\s*"
        r"\((\d{4})\)"
    ),

    # Books: Author, Title (Edition Year) - captures full ordinal like "6th"
    "book": re.compile(
        # "&" and apostrophes/hyphens are allowed in the author. Without "&", the first
        # author of "Roy M. Mersky & Donald J. Dunn, Title (8th ed. 2002)" was silently
        # dropped and the citation attributed to the second author alone.
        r"([A-Z][a-zA-Z\.\s&'\-]{1,100}),\s+"
        r"([A-Z][^(]{1,250})\s*"
        # Bluebook ordinals are "2d" and "3d", not "2nd" and "3rd"
        # (Rule 6.2(b)), so both spellings must be accepted.
        r"\((?:(\d+(?:st|nd|rd|th|d))\s+ed\.\s+)?(\d{4})\)"
    ),

    # Short forms - Id.
    "id_citation": re.compile(
        r"\bId\.(?:\s+at\s+(\d+(?:-\d+)?))?"
    ),

    # Short forms - Supra
    "supra_citation": re.compile(
        r"([A-Za-z]{1,60}),?\s+supra\s+note\s+(\d+)(?:,\s+at\s+(\d+(?:-\d+)?))?"
    ),

    # Hereinafter designation
    "hereinafter": re.compile(
        r"\[hereinafter\s+([^\]]+)\]"
    ),

    # URL citations
    "url": re.compile(
        r"https?://[^\s<>\"\'\)]{1,2000}(?:\([^\s<>\"\'\)]{0,2000}\))?[^\s<>\"\'\)\.,;:]{0,2000}"
    ),

    # Pincites
    "pincite": re.compile(
        r"at\s+(\d+)(?:-(\d+))?"
    ),

    # Footnote markers.
    #
    # Anchored to the start of a line. The old pattern matched any 1-3 digit
    # number followed by a capital anywhere in the text, so reporter volumes
    # and statute titles were read as footnote numbers: "47 U.S.C. § 230" was
    # labelled "Note 47" and "395 U.S. 444" became "Note 395". The reporter
    # lookahead is a second guard for numbered lines that begin a citation.
    # Written by the Word parser in front of each real footnote, e.g. "[^4] ".
    # Endnotes use "[^e4]". When these are present they are authoritative and
    # the digit-at-line-start heuristic below is not consulted at all.
    "footnote_marker_explicit": re.compile(r"(?m)^[ \t]*\[\^(e?)(\d{1,4})\][ \t]*"),

    "footnote_marker": re.compile(
        rf"(?m)^[ \t]*(\d{{1,3}})[.)]?[ \t]+(?!{_REPORTER_LOOKAHEAD})(?=[A-Z\"'])"
    ),
}

# Reporter abbreviations (Bluebook Table 1)
REPORTER_ABBREVIATIONS: dict[str, str] = {
    "United States Reports": "U.S.",
    "Supreme Court Reporter": "S. Ct.",
    "Lawyers Edition": "L. Ed.",
    "Lawyers Edition Second": "L. Ed. 2d",
    "Federal Reporter": "F.",
    "Federal Reporter Second Series": "F.2d",
    "Federal Reporter Third Series": "F.3d",
    "Federal Reporter Fourth Series": "F.4d",
    "Federal Supplement": "F. Supp.",
    "Federal Supplement Second Series": "F. Supp. 2d",
    "Federal Supplement Third Series": "F. Supp. 3d",
    "Federal Rules Decisions": "F.R.D.",
    "Bankruptcy Reporter": "B.R.",
    "Federal Claims Reporter": "Fed. Cl.",
    "Veterans Appeals Reporter": "Vet. App.",
    "Military Justice Reporter": "M.J.",
    "Atlantic Reporter": "A.",
    "Atlantic Reporter Second Series": "A.2d",
    "Atlantic Reporter Third Series": "A.3d",
    "North Eastern Reporter": "N.E.",
    "North Eastern Reporter Second Series": "N.E.2d",
    "North Eastern Reporter Third Series": "N.E.3d",
    "North Western Reporter": "N.W.",
    "North Western Reporter Second Series": "N.W.2d",
    "Pacific Reporter": "P.",
    "Pacific Reporter Second Series": "P.2d",
    "Pacific Reporter Third Series": "P.3d",
    "South Eastern Reporter": "S.E.",
    "South Eastern Reporter Second Series": "S.E.2d",
    "South Western Reporter": "S.W.",
    "South Western Reporter Second Series": "S.W.2d",
    "South Western Reporter Third Series": "S.W.3d",
    "Southern Reporter": "So.",
    "Southern Reporter Second Series": "So. 2d",
    "Southern Reporter Third Series": "So. 3d",
    "California Reporter": "Cal. Rptr.",
    "California Reporter Second Series": "Cal. Rptr. 2d",
    "California Reporter Third Series": "Cal. Rptr. 3d",
    "New York Supplement": "N.Y.S.",
    "New York Supplement Second Series": "N.Y.S.2d",
    "New York Supplement Third Series": "N.Y.S.3d",
}

# Court abbreviations (Bluebook Table 7)
COURT_ABBREVIATIONS: dict[str, str] = {
    "Supreme Court of the United States": "",
    "Supreme Court": "",
    "United States Court of Appeals for the First Circuit": "1st Cir.",
    "First Circuit": "1st Cir.",
    "United States Court of Appeals for the Second Circuit": "2d Cir.",
    "Second Circuit": "2d Cir.",
    "United States Court of Appeals for the Third Circuit": "3d Cir.",
    "Third Circuit": "3d Cir.",
    "United States Court of Appeals for the Fourth Circuit": "4th Cir.",
    "Fourth Circuit": "4th Cir.",
    "United States Court of Appeals for the Fifth Circuit": "5th Cir.",
    "Fifth Circuit": "5th Cir.",
    "United States Court of Appeals for the Sixth Circuit": "6th Cir.",
    "Sixth Circuit": "6th Cir.",
    "United States Court of Appeals for the Seventh Circuit": "7th Cir.",
    "Seventh Circuit": "7th Cir.",
    "United States Court of Appeals for the Eighth Circuit": "8th Cir.",
    "Eighth Circuit": "8th Cir.",
    "United States Court of Appeals for the Ninth Circuit": "9th Cir.",
    "Ninth Circuit": "9th Cir.",
    "United States Court of Appeals for the Tenth Circuit": "10th Cir.",
    "Tenth Circuit": "10th Cir.",
    "United States Court of Appeals for the Eleventh Circuit": "11th Cir.",
    "Eleventh Circuit": "11th Cir.",
    "United States Court of Appeals for the District of Columbia Circuit": "D.C. Cir.",
    "D.C. Circuit": "D.C. Cir.",
    "United States Court of Appeals for the Federal Circuit": "Fed. Cir.",
    "Federal Circuit": "Fed. Cir.",
    "District of Columbia": "D.D.C.",
    "Eastern District of New York": "E.D.N.Y.",
    "Southern District of New York": "S.D.N.Y.",
    "Northern District of California": "N.D. Cal.",
    "Central District of California": "C.D. Cal.",
    "Eastern District of Virginia": "E.D. Va.",
    "District of Massachusetts": "D. Mass.",
    "Northern District of Illinois": "N.D. Ill.",
    "Eastern District of Pennsylvania": "E.D. Pa.",
    "District of Delaware": "D. Del.",
}

# Journal abbreviations (Bluebook Table 13)
JOURNAL_ABBREVIATIONS: dict[str, str] = {
    "Harvard Law Review": "Harv. L. Rev.",
    "Yale Law Journal": "Yale L.J.",
    "Stanford Law Review": "Stan. L. Rev.",
    "Columbia Law Review": "Colum. L. Rev.",
    "Michigan Law Review": "Mich. L. Rev.",
    "Virginia Law Review": "Va. L. Rev.",
    "California Law Review": "Calif. L. Rev.",
    "Georgetown Law Journal": "Geo. L.J.",
    "Texas Law Review": "Tex. L. Rev.",
    "University of Pennsylvania Law Review": "U. Pa. L. Rev.",
    "Duke Law Journal": "Duke L.J.",
    "Northwestern University Law Review": "Nw. U. L. Rev.",
    "University of Chicago Law Review": "U. Chi. L. Rev.",
    "New York University Law Review": "N.Y.U. L. Rev.",
    "Cornell Law Review": "Cornell L. Rev.",
    "Minnesota Law Review": "Minn. L. Rev.",
    "Vanderbilt Law Review": "Vand. L. Rev.",
    "Boston University Law Review": "B.U. L. Rev.",
    "George Washington Law Review": "Geo. Wash. L. Rev.",
    "Notre Dame Law Review": "Notre Dame L. Rev.",
    "UCLA Law Review": "UCLA L. Rev.",
    "Southern California Law Review": "S. Cal. L. Rev.",
    "Wisconsin Law Review": "Wis. L. Rev.",
    "Indiana Law Journal": "Ind. L.J.",
    "Iowa Law Review": "Iowa L. Rev.",
    "Washington Law Review": "Wash. L. Rev.",
    "American Journal of International Law": "Am. J. Int'l L.",
    "Journal of Law and Economics": "J.L. & Econ.",
    "Law and Contemporary Problems": "Law & Contemp. Probs.",
}

# State abbreviations (Bluebook Table 10)
STATE_ABBREVIATIONS: dict[str, str] = {
    "Alabama": "Ala.",
    "Alaska": "Alaska",
    "Arizona": "Ariz.",
    "Arkansas": "Ark.",
    "California": "Cal.",
    "Colorado": "Colo.",
    "Connecticut": "Conn.",
    "Delaware": "Del.",
    "District of Columbia": "D.C.",
    "Florida": "Fla.",
    "Georgia": "Ga.",
    "Hawaii": "Haw.",
    "Idaho": "Idaho",
    "Illinois": "Ill.",
    "Indiana": "Ind.",
    "Iowa": "Iowa",
    "Kansas": "Kan.",
    "Kentucky": "Ky.",
    "Louisiana": "La.",
    "Maine": "Me.",
    "Maryland": "Md.",
    "Massachusetts": "Mass.",
    "Michigan": "Mich.",
    "Minnesota": "Minn.",
    "Mississippi": "Miss.",
    "Missouri": "Mo.",
    "Montana": "Mont.",
    "Nebraska": "Neb.",
    "Nevada": "Nev.",
    "New Hampshire": "N.H.",
    "New Jersey": "N.J.",
    "New Mexico": "N.M.",
    "New York": "N.Y.",
    "North Carolina": "N.C.",
    "North Dakota": "N.D.",
    "Ohio": "Ohio",
    "Oklahoma": "Okla.",
    "Oregon": "Or.",
    "Pennsylvania": "Pa.",
    "Rhode Island": "R.I.",
    "South Carolina": "S.C.",
    "South Dakota": "S.D.",
    "Tennessee": "Tenn.",
    "Texas": "Tex.",
    "Utah": "Utah",
    "Vermont": "Vt.",
    "Virginia": "Va.",
    "Washington": "Wash.",
    "West Virginia": "W. Va.",
    "Wisconsin": "Wis.",
    "Wyoming": "Wyo.",
}

# Party name abbreviations (Bluebook Table 6)
PARTY_ABBREVIATIONS: dict[str, str] = {
    "Administration": "Admin.",
    "Administrative": "Admin.",
    "Administrator": "Adm'r",
    "Administratrix": "Adm'x",
    "America": "Am.",
    "American": "Am.",
    "and": "&",
    "Association": "Ass'n",
    "Atlantic": "Atl.",
    "Authority": "Auth.",
    "Automobile": "Auto.",
    "Automotive": "Auto.",
    "Avenue": "Ave.",
    "Board": "Bd.",
    "Brotherhood": "Bhd.",
    "Brothers": "Bros.",
    "Building": "Bldg.",
    "Center": "Ctr.",
    "Central": "Cent.",
    "Chemical": "Chem.",
    "Commission": "Comm'n",
    "Commissioner": "Comm'r",
    "Committee": "Comm.",
    "Communication": "Commc'n",
    "Communications": "Commc'ns",
    "Community": "Cmty.",
    "Company": "Co.",
    "Consolidated": "Consol.",
    "Construction": "Constr.",
    "Corporation": "Corp.",
    "County": "Cnty.",
    "Department": "Dep't",
    "Development": "Dev.",
    "Director": "Dir.",
    "Distributor": "Distrib.",
    "Distributors": "Distribs.",
    "District": "Dist.",
    "Division": "Div.",
    "East": "E.",
    "Eastern": "E.",
    "Economic": "Econ.",
    "Education": "Educ.",
    "Educational": "Educ.",
    "Electric": "Elec.",
    "Electrical": "Elec.",
    "Electronic": "Elec.",
    "Electronics": "Elecs.",
    "Engineering": "Eng'g",
    "Enterprise": "Enter.",
    "Enterprises": "Enters.",
    "Entertainment": "Ent.",
    "Environment": "Env't",
    "Environmental": "Envtl.",
    "Equipment": "Equip.",
    "Exchange": "Exch.",
    "Executor": "Ex'r",
    "Executrix": "Ex'x",
    "Export": "Exp.",
    "Federal": "Fed.",
    "Federation": "Fed'n",
    "Financial": "Fin.",
    "Foundation": "Found.",
    "General": "Gen.",
    "Government": "Gov't",
    "Guaranty": "Guar.",
    "Hospital": "Hosp.",
    "Housing": "Hous.",
    "Import": "Imp.",
    "Incorporated": "Inc.",
    "Indemnity": "Indem.",
    "Independent": "Indep.",
    "Industrial": "Indus.",
    "Industries": "Indus.",
    "Industry": "Indus.",
    "Information": "Info.",
    "Institute": "Inst.",
    "Institution": "Inst.",
    "Insurance": "Ins.",
    "International": "Int'l",
    "Investment": "Inv.",
    "Investor": "Inv.",
    "Laboratory": "Lab.",
    "Laboratories": "Labs.",
    "Liability": "Liab.",
    "Limited": "Ltd.",
    "Litigation": "Litig.",
    "Machine": "Mach.",
    "Machinery": "Mach.",
    "Maintenance": "Maint.",
    "Management": "Mgmt.",
    "Manager": "Mgr.",
    "Manufacturer": "Mfr.",
    "Manufacturers": "Mfrs.",
    "Manufacturing": "Mfg.",
    "Market": "Mkt.",
    "Marketing": "Mktg.",
    "Mechanical": "Mech.",
    "Medical": "Med.",
    "Memorial": "Mem'l",
    "Merchant": "Merch.",
    "Metropolitan": "Metro.",
    "Municipal": "Mun.",
    "Mutual": "Mut.",
    "National": "Nat'l",
    "North": "N.",
    "Northeast": "Ne.",
    "Northern": "N.",
    "Northwest": "Nw.",
    "Number": "No.",
    "Organization": "Org.",
    "Pacific": "Pac.",
    "Partnership": "P'ship",
    "Petroleum": "Pet.",
    "Pharmaceutical": "Pharm.",
    "President": "Pres.",
    "Product": "Prod.",
    "Products": "Prods.",
    "Production": "Prod.",
    "Professional": "Prof'l",
    "Property": "Prop.",
    "Protection": "Prot.",
    "Public": "Pub.",
    "Publication": "Publ'n",
    "Publications": "Publ'ns",
    "Publishing": "Publ'g",
    "Railroad": "R.R.",
    "Railway": "Ry.",
    "Regional": "Reg'l",
    "Reproduction": "Reprod.",
    "Research": "Rsch.",
    "Resource": "Res.",
    "Resources": "Res.",
    "Restaurant": "Rest.",
    "Road": "Rd.",
    "Savings": "Sav.",
    "School": "Sch.",
    "Science": "Sci.",
    "Scientific": "Sci.",
    "Secretary": "Sec'y",
    "Security": "Sec.",
    "Service": "Serv.",
    "Services": "Servs.",
    "Society": "Soc'y",
    "South": "S.",
    "Southeast": "Se.",
    "Southern": "S.",
    "Southwest": "Sw.",
    "Standard": "Stand.",
    "State": "State",
    "Steamship": "S.S.",
    "Street": "St.",
    "Subcommittee": "Subcomm.",
    "Superintendent": "Supt.",
    "Surety": "Sur.",
    "System": "Sys.",
    "Systems": "Sys.",
    "Technical": "Tech.",
    "Technology": "Tech.",
    "Telecommunications": "Telecomms.",
    "Telephone": "Tel.",
    "Television": "T.V.",
    "Temporary": "Temp.",
    "Textile": "Textile",
    "Transcontinental": "Transcon.",
    "Transport": "Transp.",
    "Transportation": "Transp.",
    "Trustee": "Tr.",
    "Uniform": "Unif.",
    "United": "United",
    "United States": "United States",
    "University": "Univ.",
    "Utility": "Util.",
    "Utilities": "Utils.",
    "Village": "Vill.",
    "West": "W.",
    "Western": "W.",
}

def get_reporter_abbreviation(reporter: str) -> str:
    """Get the Bluebook abbreviation for a reporter."""
    return REPORTER_ABBREVIATIONS.get(reporter, reporter)

def get_court_abbreviation(court: str) -> str:
    """Get the Bluebook abbreviation for a court."""
    return COURT_ABBREVIATIONS.get(court, court)

def get_journal_abbreviation(journal: str) -> str:
    """Get the Bluebook abbreviation for a journal."""
    return JOURNAL_ABBREVIATIONS.get(journal, journal)

def abbreviate_party_name(party: str) -> str:
    """Abbreviate a party name per Bluebook Table 6.

    Protects state names from being incorrectly abbreviated (e.g.,
    "North Carolina" should not become "N. Carolina").
    """
    result = party

    # Remove "The" at beginning (Rule 10.2.1(e))
    if result.lower().startswith("the "):
        result = result[4:]

    # Protect state names from being abbreviated.
    # Replace them with placeholders, then restore after other abbreviations.
    #
    # Longest first: "Virginia" is itself a state, so protecting it before
    # "West Virginia" leaves a bare "West" for Table 6 to turn into "W.",
    # yielding "W. Virginia".
    protected = {}
    placeholder_idx = 0
    for state_name in sorted(STATE_ABBREVIATIONS, key=len, reverse=True):
        if state_name in result:
            placeholder = f"__STATE_{placeholder_idx}__"
            result = result.replace(state_name, placeholder)
            protected[placeholder] = state_name
            placeholder_idx += 1

    # Apply abbreviations
    for full, abbrev in PARTY_ABBREVIATIONS.items():
        # Use word boundaries for replacement
        pattern = re.compile(r'\b' + re.escape(full) + r'\b', re.IGNORECASE)
        result = pattern.sub(abbrev, result)

    # Restore protected state names
    for placeholder, state_name in protected.items():
        result = result.replace(placeholder, state_name)

    return result.strip()


# =============================================================================================
# What a party name is made of
# =============================================================================================
#
# A case name used to be "any run of up to eight words that starts with a capital", which took
# the prose on both sides of the name with it. The extractor now reads a name word by word
# (extractor.py, "Party names"); these tables are what it knows about the words.

# --- Words that end in a full stop without ending a sentence ---------------------------------
#
# Table T6 (case names), T7 (court names) and T10 (geographical terms) abbreviations, plus the
# titles, entity suffixes and months that appear inside names and citations. The tables above
# hold the T6 and T10 entries this tool APPLIES; the list here is wider, because recognising an
# abbreviation someone else applied is a different job from applying one. Word length is not
# evidence either way: "Roe." and "Ohio." end sentences, "Indep." and "Envtl." do not.
_ABBREVIATIONS_SEEN_IN_NAMES = """
Acad. Admin. Adm. Advert. Advoc. Aff. Afr. Agric. All. Alt. Am. Amend. Anc. Ann. App. Arb. Assoc.
Assocs. Assn. Atl. Auth. Auto. Ave. Bankr. Bd. Behav. Bhd. Bros. Broad. Bldg. Bus. Cap. Cas. Cath.
Ctr. Cent. Chem. Child. Chron. Cir. Civ. Coal. Coll. Com. Comm. Cmty. Co. Cos. Comp. Comput.
Condo. Conf. Cong. Consol. Const. Constr. Cont. Contemp. Conv. Coop. Corp. Corr. Cosm. Couns.
Cnty. Cty. Ct. Cts. Crim. Def. Delinq. Dept. Det. Dev. Dig. Dipl. Dir. Disc. Disp. Distrib.
Distribs. Dist. Div. Dr. E. Econ. Ed. Educ. Elec. Elecs. Emp. Enter. Enters. Ent. Envtl. Equal.
Equip. Est. Eur. Exch. Exec. Explor. Exp. Fac. Fam. Fed. Fid. Fin. Found. Gen. Glob. Grp. Guar.
Hist. Hosp. Hous. Hum. Immigr. Imp. Inc. Indem. Indep. Indus. Ineq. Info. Inj. Inst. Ins. Intell.
Int. Intl. Inv. Invs. Jud. Jurid. Juris. Just. Juv. Lab. Labs. Legis. Liab. Libr. Ltd. Litig. Loc.
Mach. Mag. Maint. Mgmt. Mgr. Mfr. Mfrs. Mfg. Mar. Mkt. Mktg. Matrim. Mech. Med. Merch. Metro. Mil.
Min. Mod. Mortg. Mun. Mut. Nat. Natl. Negl. Negot. N. Ne. Nw. No. Nos. Off. Op. Ord. Org. Pac.
Parl. Pat. Pers. Pharm. Phil. Plan. Pol. Prac. Pres. Priv. Prob. Probs. Proc. Prod. Prods. Prof.
Prop. Prot. Psych. Pub. Ry. Rec. Ref. Refin. Regul. Rehab. Rel. Rep. Reprod. Rsch. Rsrv. Resol.
Res. Resp. Rest. Ret. Rev. Rts. Rd. Sav. Sch. Sci. Scot. Sec. Serv. Servs. Soc. Socio. Sol. S.
Se. Sw. St. Ste. Stat. Sts. Subcomm. Supt. Sup. Super. Sur. Surv. Symp. Sys. Tchr. Tech.
Telecomm. Telecomms. Tel. Temp. Twp. Transcon. Transp. Tr. Tpk. Unif. Univ. Urb. Util. Utils.
Vill. W. Commw. Cl. Eq. Magis. Par. Terr. Trib. Pl.
Mr. Mrs. Ms. Messrs. Hon. Sen. Gov. Col. Capt. Lt. Sgt. Jr. Sr. Esq. Mt. Ft. Pt. Blvd. Hwy.
Jan. Feb. Apr. Jun. Jul. Aug. Sept. Sep. Oct. Nov. Dec.
Ida. Calif. Penn. Penna. Wisc. Ore. Kans. Nebr. Balt. Bos. Chi. Dall. Phila. Phx.
rel. al. cf. etc. viz. vs. v. art. cl. ch. pt. tit. vol. eds. supp. sess.
"""


def _abbreviation_tokens() -> frozenset[str]:
    tokens = {t.lower() for t in _ABBREVIATIONS_SEEN_IN_NAMES.split()}
    for table in (PARTY_ABBREVIATIONS, STATE_ABBREVIATIONS, COURT_ABBREVIATIONS, REPORTER_ABBREVIATIONS):
        for value in table.values():
            tokens.update(t.lower() for t in value.split() if t.endswith("."))
    return frozenset(tokens)


ABBREVIATION_TOKENS: frozenset[str] = _abbreviation_tokens()
# The Table T6 words among them (the capitalised ones; not months, titles or "art."), which are
# the only ones whose plural is formed by adding "s".
_PLURAL_STEMS: frozenset[str] = frozenset(
    t.lower() for t in _ABBREVIATIONS_SEEN_IN_NAMES.split("Mr. Mrs.")[0].split() if len(t) > 3
) | frozenset(t.lower() for v in PARTY_ABBREVIATIONS.values() for t in v.split() if t.endswith(".") and len(t) > 3)

# "U.S.", "L.A.", "N.Y.", "Ges.m.b.H.": a full stop INSIDE the token is the mark of an
# abbreviation, and so is a single capital initial ("John F. Kennedy").
_INTERNAL_FULL_STOP = re.compile(r"[A-Za-z]\.[A-Za-z]")


def is_abbreviation(token: str) -> bool:
    """True when `token`, which ends in a full stop, is an abbreviation and not the last word of
    a sentence. Decided from the tables and from the token's shape, never from its length."""
    if not token.endswith("."):
        return False
    low = token.lower()
    if low in ABBREVIATION_TOKENS:
        return True
    # Table T6 forms a plural by adding "s": "Cmtys.", "Indus.", "Hosps.", "Sch." -> "Schs."
    if token[0].isupper() and low.endswith("s.") and low[:-2] + "." in _PLURAL_STEMS:
        return True
    if _INTERNAL_FULL_STOP.search(token, 0, len(token) - 1):
        return True
    return len(token) == 2 and token[0].isalpha() and token[0].isupper()


# --- Entity suffixes --------------------------------------------------------------------------
#
# Compared against a whole token. The old pattern tried them as prefixes, so the "Co" of
# "Colo. Ct. App." was read as a company suffix and the defendant became "Hickenlooper, Co".
ENTITY_SUFFIXES: frozenset[str] = frozenset(
    "inc. inc incorporated llc llc. l.l.c. corp. corp corporation co. ltd. ltd limited l.p. lp llp "
    "l.l.p. lllp pllc p.l.l.c. p.c. pc n.a. s.a. plc p.a. gmbh ag n.v. b.v. s.p.a. pty. pte.".split()
)
# What may follow a comma INSIDE a name: an entity suffix or a personal one ("Fallon, Jr.").
COMMA_SUFFIXES: frozenset[str] = ENTITY_SUFFIXES | frozenset("jr. sr. ii iii iv m.d. esq. ph.d.".split())

# --- Lower-case words that belong inside a name -----------------------------------------------
#
# Only BETWEEN two name words: "Board of Education", "Friends of the Earth", "Students for Fair
# Admissions", "City and County of San Francisco", "United States ex rel. Schutte", "Smith d/b/a
# Acme", "de la Cruz". Left dangling at either edge of a name they are prose and are dropped.
NAME_CONNECTORS: frozenset[str] = frozenset(
    "of the for and & de la las los le del della der den van von du di da des dos el al y "
    "ex rel. d/b/a a/k/a f/k/a n/k/a o/b/o et al.".split()
)
# Particles that may BEGIN the second party: "Hernandez v. de la Cruz", "Treasury Employees v.
# Von Raab" (capitalised there, lower case in many names).
NAME_PARTICLES: frozenset[str] = frozenset("de la las los le del della der den van von du di da des dos el al".split())

# "on", "in", "to" and "against" are ordinary prose far more often than they are part of a name
# ("the Second Circuit in National Shooting Sports Foundation v. James", "press statement on
# McDonald v. City of Chicago", "according to Smith v. Jones"). They are read as part of a name
# only straight after the kind of word that heads an organisation's name. The lists come from
# reported captions: Committee on Children's Television, Council on American-Islamic Relations,
# Commission on Human Rights, Leadership Conference on Civil Rights, Center on Budget & Policy
# Priorities, Institute on Taxation & Economic Policy, Task Force on ..., Coalition on
# Homelessness, Project on Government Oversight; People in Interest of A.B., Committee in
# Solidarity with the People of El Salvador, Women in City Government United; Citizens to
# Preserve Overton Park, Committee to Defend Reproductive Rights, Coalition to Defend
# Affirmative Action, Campaign to ...; Mothers against Drunk Driving, Citizens against ....
CONDITIONAL_CONNECTORS: dict[str, frozenset[str]] = {
    "on": frozenset(
        "committee comm. subcommittee subcomm. council commission comm'n conference conf. board bd. "
        "center ctr. centre institute inst. force coalition coal. alliance all. project panel forum "
        "campaign consortium bureau office off. initiative".split()
    ),
    "in": frozenset("people committee comm. women".split()),
    "to": frozenset(
        "committee comm. citizens coalition coal. campaign alliance all. council society soc'y "
        "project people association ass'n americans".split()
    ),
    "against": frozenset("mothers citizens coalition coal. people americans students parents women".split()),
}
# "Citizens for a Better Environment": an article is part of a name only straight after one of
# the prepositions above or below.
NAME_ARTICLES: frozenset[str] = frozenset({"a", "an"})
_ARTICLE_AFTER: frozenset[str] = frozenset({"for", "of", "on", "in", "to", "against"})

# --- Capitalised words that are prose, not the start of a name --------------------------------
#
# What can stand directly in front of a case name at the start of a sentence or clause: signals,
# prepositions, conjunctions and the participles lawyers introduce a citation with. A party
# whose own name begins with one of these ("Under Armour, Inc.") loses that word; that is rare,
# and "In Brown v. Board" and "Under Chevron" are on every page. "The" is here because Rule
# 10.2.1(d) drops it from the front of a party's name.
LEFT_STOP_WORDS: frozenset[str] = frozenset(
    "See Also But Cf. Compare Accord Contra E.g. In Under After Since Before Following Unlike Like "
    "Per Until By From With On At To Of About And Or Both Either Neither When While Although Though "
    "Because If As That Whether Thus Hence Then Even Only Citing Quoting Applying Overruling "
    "Reversing Affirming Distinguishing Discussing Cases The This These Those Its His Her Their Our "
    "Indeed However Moreover Furthermore Similarly Likewise Instead Rather Yet So Notably "
    "Specifically Finally Later Earlier Recently Here There Where Whereas Despite Given Consider "
    "Considering Regarding Concerning Unless Absent Beyond Between Among Within Without Through "
    "Throughout During Upon Nor Recall Contrast Relying Echoing Invoking Extending Revisiting "
    "Overturning Upholding Rejecting Adopting Interpreting Construing Limiting Clarifying "
    "Reaffirming Decided Held Source Context Generally".split()
)
# After an abbreviation's full stop the next capitalised word normally continues the name
# ("Mut. Auto. Ins. Co."), unless it is one of the words a new sentence begins with.
SENTENCE_STARTERS: frozenset[str] = LEFT_STOP_WORDS | frozenset(
    "It He She We They You I A An Such Each Every Some Many Most All No None Not Neither Another "
    "Other Others Congress Justice Justices Judge Judges Plaintiff Plaintiffs Defendant Defendants "
    "Petitioner Petitioners Respondent Respondents Appellant Appellants Appellee Appellees Amici "
    "Amicus Courts Therefore Accordingly Nevertheless Nonetheless Still Now Today Next First Second "
    "Third Fourth Fifth Lastly Further Additionally Importantly Conversely Otherwise Meanwhile "
    "Ultimately Subsequently Previously Initially Originally Historically Traditionally Typically "
    "Usually Often Sometimes Perhaps Certainly Clearly Obviously Arguably Presumably Apparently "
    "What Which Who Whose How Why Whatever Whenever Wherever Once Again Twice Nothing Something "
    "Everything Anything Nobody Everyone Anyone Someone".split()
)
# A capitalised word that follows a complete name in running prose and is not part of it: "In
# Roe v. Wade Justice Blackmun wrote".
RIGHT_STOP_TITLES: frozenset[str] = frozenset({"Justice", "Justices", "Judge", "Judges"})

# "Ohio's Arnold v. Cleveland framework", "the Court's Heller decision", "Justice Scalia's
# ...": a possessive place, court or government body directly in front of a name is prose.
# Possessives that are part of a name stay ("Children's Hospital", "Sportsmen's Clubs",
# "L.A. Sheriff's Dept."), which is why this is a list of possessors and not a rule about "'s".
PROSE_POSSESSORS: frozenset[str] = frozenset(
    {name.lower() for name in STATE_ABBREVIATIONS}
    | {abbr.lower() for abbr in STATE_ABBREVIATIONS.values()}
    | set(
        "court circuit district state city county government congress legislature nation country "
        "commonwealth agency department majority dissent panel plaintiff plaintiffs defendant "
        "defendants petitioner petitioners respondent respondents appellant appellants appellee "
        "appellees amici brief america states".split()
    )
)
# Titles whose bearer's possessive is prose too: "Justice Blackmun's Roe v. Wade opinion".
PERSON_TITLES: frozenset[str] = frozenset("justice judge chief president senator governor professor".split())

# Procedural case-name forms where the leading words ARE the name and must survive cleanup.
LEGAL_NAME_PREFIXES: tuple[str, ...] = (
    "in re ",
    "ex parte ",
    "ex rel. ",
    "in the matter of ",
    "matter of ",
    "estate of ",
)

# A word of a name: it starts with a capital, or with digits and then a capital ("3M"), or is one
# of the few names written with a lower-case first letter and a capital inside ("eBay"). A
# purely numeric token is never part of a name: allowing one let "Brandenburg v Ohio 395 US 444"
# absorb the volume, reporter and page into the defendant.
NAME_WORD = re.compile(r"(?:[A-Z]|[0-9]{1,10}[A-Z]|[a-z]{1,2}[A-Z])[A-Za-z0-9.'&\-]{0,60}\Z")

# "v." between two names, as a token of its own. Lower case only: "V." is an initial.
V_ANCHOR = re.compile(r"(?<=\s)v\.?(?=\s)")
