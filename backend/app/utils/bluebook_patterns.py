"""
Comprehensive Bluebook citation patterns and abbreviations.
Based on Bluebook 21st Edition.
"""

import re
from typing import Dict, List, Pattern

# Citation detection patterns
PATTERNS: Dict[str, Pattern] = {
    # Cases: Party v. Party, Volume Reporter Page (Court Year)
    # Party names: capitalized words, can include LLC/Inc/Corp, no greedy whitespace
    "case_complete": re.compile(
        r"([A-Z][a-zA-Z\.\'\-]+(?:\s+[A-Za-z\.\'\-]+){0,5})\s+v\.\s+"
        r"([A-Z][a-zA-Z\.\'\-]+(?:\s+[A-Za-z\.\'\-]+){0,5}),\s*"
        r"(\d+)\s+([A-Z][a-zA-Z\.\s\d]+?)\s+(\d+)"
        r"(?:,\s*(\d+(?:-\d+)?))?\s*"
        r"\(([^)]+)\)"
    ),

    # Incomplete case: just Party v. Party (missing reporter info)
    # Limited to reasonable party name length (max 5 words per party)
    "case_incomplete": re.compile(
        r"([A-Z][a-zA-Z\.\'\-]+(?:\s+[A-Za-z\.\'\-]+){0,5})\s+v\.\s+"
        r"([A-Z][a-zA-Z\.\'\-]+(?:\s+[A-Za-z\.\'\-]+){0,5})"
        r"(?!\s*,\s*\d+\s+[A-Z])"
    ),
    
    # Federal statutes: Title U.S.C. § Section
    "statute_usc": re.compile(
        r"(\d+)\s+U\.?S\.?C\.?\s*§+\s*(\d+[a-z]?)(?:\(([^)]+)\))?"
    ),
    
    # State statutes (generic pattern)
    "statute_state": re.compile(
        r"([A-Z][a-z]+\.?\s+(?:Rev\.?\s+)?(?:Code|Stat)\.?\s*(?:Ann\.?)?\s*)"
        r"§+\s*(\d+(?:[-.]\d+)*)"
    ),
    
    # Federal regulations: Title C.F.R. § Section
    "regulation_cfr": re.compile(
        r"(\d+)\s+C\.?F\.?R\.?\s*§+\s*(\d+(?:\.\d+)?)"
    ),
    
    # Law review articles: Author, Title, Volume Journal Page (Year)
    "law_review": re.compile(
        r"([A-Z][a-zA-Z\.\s]+),\s+"
        r"([^,]+),\s+"
        r"(\d+)\s+([A-Z][a-zA-Z\.\s&]+(?:L\.|Law|J\.|Journal|Rev\.|Review)[a-zA-Z\.\s]*)\s+"
        r"(\d+)(?:,\s*(\d+(?:-\d+)?))?\s*"
        r"\((\d{4})\)"
    ),
    
    # Books: Author, Title (Edition Year) - captures full ordinal like "6th"
    "book": re.compile(
        r"([A-Z][a-zA-Z\.\s]+),\s+"
        r"([A-Z][^(]+)\s*"
        r"\((?:(\d+(?:st|nd|rd|th))\s+ed\.\s+)?(\d{4})\)"
    ),
    
    # Short forms - Id.
    "id_citation": re.compile(
        r"\bId\.(?:\s+at\s+(\d+(?:-\d+)?))?"
    ),
    
    # Short forms - Supra
    "supra_citation": re.compile(
        r"([A-Za-z]+),?\s+supra\s+note\s+(\d+)(?:,\s+at\s+(\d+(?:-\d+)?))?"
    ),
    
    # Hereinafter designation
    "hereinafter": re.compile(
        r"\[hereinafter\s+([^\]]+)\]"
    ),
    
    # URL citations
    "url": re.compile(
        r"https?://[^\s<>\"\'\)]+(?:\([^\s<>\"\'\)]*\))?[^\s<>\"\'\)\.,;:]*"
    ),
    
    # Pincites
    "pincite": re.compile(
        r"at\s+(\d+)(?:-(\d+))?"
    ),
    
    # Footnote markers
    "footnote_marker": re.compile(
        r"(?:^|\s)(\d{1,3})(?=\s+[A-Z]|\s*$)"
    ),
}

# Reporter abbreviations (Bluebook Table 1)
REPORTER_ABBREVIATIONS: Dict[str, str] = {
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
COURT_ABBREVIATIONS: Dict[str, str] = {
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
JOURNAL_ABBREVIATIONS: Dict[str, str] = {
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
STATE_ABBREVIATIONS: Dict[str, str] = {
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
PARTY_ABBREVIATIONS: Dict[str, str] = {
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
    """Abbreviate a party name per Bluebook Table 6."""
    result = party
    
    # Remove "The" at beginning (Rule 10.2.1(e))
    if result.lower().startswith("the "):
        result = result[4:]
    
    # Apply abbreviations
    for full, abbrev in PARTY_ABBREVIATIONS.items():
        # Use word boundaries for replacement
        pattern = re.compile(r'\b' + re.escape(full) + r'\b', re.IGNORECASE)
        result = pattern.sub(abbrev, result)
    
    return result.strip()
