"""Repairing what PDF producers do to text: ligature code points, line-end hyphens, soft
hyphens, the marker pdfium writes where it removed a hyphen, and wrapped URLs."""

import json
import random
import re

import pytest

import app.services.pdf_text as P
from app.services.pdf_text import repair_text as r
from tests.hostile import run_pdf, run_python


def test_ligature_code_points_are_expanded():
    assert r("oﬃce ﬁnal ﬂoor eﬀect") == "office final floor effect"


def test_line_end_hyphen_inside_a_word_is_dropped_and_joined():
    assert r("the regu-\nlation applies") == "the regulation applies"
    assert r("the regu‐\n  lation") == "the regulation"
    assert r("the regu\u00ad\nlation") == "the regulation"


def test_real_hyphens_in_numbers_and_identifiers_are_kept():
    assert r("GAO-\n16-552") == "GAO-16-552"
    assert r("Pub. L. No. 111-\n148") == "Pub. L. No. 111-148"
    assert r("Ohio-\nBased") == "Ohio-Based"


def test_soft_hyphen_inside_a_word_is_removed():
    assert r("sta\u00adndard") == "standard"


def test_pdfium_hyphen_markers():
    assert r("Enterpris\x02es v. Raimondo") == "Enterprises v. Raimondo"
    assert r("Enterpris￾es") == "Enterprises"
    assert r("GAO\x0216-552") == "GAO-16-552"
    assert r("Enterpris\x02\nes v.") == "Enterprises v."
    assert r("GAO\x02\n16-552") == "GAO-16-552"


def test_control_characters_are_removed_and_crlf_normalised():
    assert r("a\x01b\r\nc\rd") == "ab\nc\nd"


def test_wrapped_url_is_rejoined_only_on_strong_evidence():
    assert r("as in https://www.fr.gov/documents/2020/07/23\n/2020-15432/rules, the") == "as in https://www.fr.gov/documents/2020/07/23/2020-15432/rules, the"
    assert r("see https://www.gao.gov/products/\ngao-24-106481 for") == "see https://www.gao.gov/products/gao-24-106481 for"
    assert r("see https://orionpolicy.org/\nId. at 4") == "see https://orionpolicy.org/\nId. at 4"
    assert r("see https://orionpolicy.org/ and\nthe next") == "see https://orionpolicy.org/ and\nthe next"
    assert r("at https://x.org/a-\nregulations is") == "at https://x.org/a-\nregulations is"


def test_idempotent_and_plain_text_untouched():
    s = "Brandenburg v. Ohio, 395 U.S. 444, 447 (1969).\n§ 1983 — “quoted”\n"
    assert r(s) == s and r(r(s)) == s


# --- line-end hyphens: which are the typesetter's and which are part of the spelling ---------------
#
# The rule is in pdf_text.py above _decide_line_end_hyphens. These are the cases that decide it:
# the ones a reviewer found corrupted (a name, a compound, a paragraph break) and the ones that must
# go on working. Each row here is a document with nothing else in it, so only the page's own
# evidence and the old guesses apply (rules 1, 2, 3a, 3e, 3g); what the rest of a document changes
# is in the tables further down.

JOINED = [          # the hyphen was added to break the word: dropped, the halves joined
    ("regu-\nlation", "regulation"),
    ("the regu-\n  lation applies", "the regulation applies"),
    ("Enter-\nprises", "Enterprises"),
    ("impor-\ntant", "important"),
    ("sub-\nstantial", "substantial"),
    ("re-\nview", "review"),
    ("re-\nquirement", "requirement"),
    ("Sulli-\nvan, 376 U.S. 254", "Sullivan, 376 U.S. 254"),       # "van" is a name particle, and also a syllable
    ("Gar-\nden of Eden", "Garden of Eden"),
    ("or-\nder of the court", "order of the court"),
    ("pris-\non officials", "prison officials"),
    ("mo-\ndel rules", "model rules"),
    ("regu\u00ad\nlation", "regulation"),                           # a soft hyphen is never part of a spelling
    ("non\u00ad\nprofit", "nonprofit"),                             # not even after a prefix that usually keeps its hyphen
    ("State-\nment", "Statement"),
]

KEPT = [            # part of the spelling: the hyphen stays and the line break goes
    ("GAO-\n16-552", "GAO-16-552"),
    ("Pub. L. No. 111-\n148", "Pub. L. No. 111-148"),
    ("10-\nK", "10-K"),
    ("Smith-\nJones", "Smith-Jones"),
    ("Ohio-\nBased", "Ohio-Based"),
    ("1981-\n1983", "1981-1983"),
    ("e-\nmail", "e-mail"),
    ("5-\nyear plan", "5-year plan"),
    ("FDA-\napproved", "FDA-approved"),
    ("COVID-\nrelated costs", "COVID-related costs"),
    ("GAO-\nreport", "GAO-report"),
    ("X-\nray", "X-ray"),
    ("T-\nshirt", "T-shirt"),
    ("state-\nof-the-art", "state-of-the-art"),
    ("mother-\nin-law", "mother-in-law"),
    ("United States v. Lopez-\nde la Cruz", "United States v. Lopez-de la Cruz"),
    ("Garcia-\nde Leon", "Garcia-de Leon"),
    ("re-\nenacted", "re-enacted"),
    ("co-\noperate", "co-operate"),
    ("non-\nprofit", "non-profit"),
    ("self-\ncontained", "self-contained"),
    ("well-\nknown", "well-known"),
    ("pre-\nand post-trial", "pre- and post-trial"),                # a suspended hyphen: the space stays too
    ("first-\nor second-degree", "first- or second-degree"),
]

UNTOUCHED = [       # no join at all
    ("five-\n\nyear", "five-\n\nyear"),                              # never across a paragraph break
    ("regu-\n  \nlation", "regu-\n  \nlation"),
    ("see Fig. 3-\n(a) below", "see Fig. 3-\n(a) below"),            # the next line does not start with a word
    ("a hyphen-\n“quoted”", "a hyphen-\n“quoted”"),
    ("at https://x.org/a-\nregulations is", "at https://x.org/a-\nregulations is"),   # inside a URL
    ("words and-\nx", "words and-\nx"),                              # one lower-case letter is not a word
]


@pytest.mark.parametrize("text,expected", JOINED, ids=[t.replace("\n", "|") for t, _ in JOINED])
def test_a_typesetters_hyphen_is_dropped_and_the_word_joined(text, expected):
    assert r(text) == expected


@pytest.mark.parametrize("text,expected", KEPT, ids=[t.replace("\n", "|") for t, _ in KEPT])
def test_a_hyphen_that_is_part_of_the_spelling_is_kept(text, expected):
    assert r(text) == expected


@pytest.mark.parametrize("text,expected", UNTOUCHED, ids=[t.replace("\n", "|") for t, _ in UNTOUCHED])
def test_a_hyphen_is_left_alone_when_nothing_can_be_decided(text, expected):
    assert r(text) == expected


# --- line-end hyphens: what the rest of the document says -------------------------------------------
#
# Each row is a whole document. The hyphenated form on one line elsewhere keeps the hyphen (3b), the
# joined form elsewhere drops it (3c), and only then do the guesses apply. These are the cases a
# 58-page paper written in Word showed: every line-end hyphen in it was the author's, and 80 of
# them were dropped (70 inside web addresses).

KEPT_BY_THE_DOCUMENT = [
    ("a concealed-\ncarry permit; the concealed-carry law", "a concealed-carry permit; the concealed-carry law"),      # 3b
    ("Own-\nvoice accounts, in an own-voice account", "Own-voice accounts, in an own-voice account"),                  # 3b, whatever the case
    ("non-\nprofit and nonprofit and non-profit", "non-profit and nonprofit and non-profit"),                          # 3b before 3c
    ("safe-\nstorage rules: a safe place, in storage", "safe-storage rules: a safe place, in storage"),                # 3f: both halves are words
    ("lost-or-\nstolen guns, lost or found", "lost-or-stolen guns, lost or found"),                                    # 3f: inside a compound
    ("gun-\npolicy; a gun, a policy, www.gunpolicy.org/a", "gun-policy; a gun, a policy, www.gunpolicy.org/a"),        # a URL is not evidence for 3c
    # 3d: two compounds the document also writes on one line, and no broken word anywhere: nothing
    # in this document is hyphenated, so the compound it uses only once keeps its hyphen too
    (
        "red-\nflag laws, red-flag orders, safe-\nstorage rules, safe-storage laws, evidence-\nbacked policy",
        "red-flag laws, red-flag orders, safe-storage rules, safe-storage laws, evidence-backed policy",
    ),
    ("an ex-\namination", "an ex-amination"),            # 3e: with nothing else to go on the old guesses stand
    ("roy-\nalty-free", "roy-alty-free"),
    ("FDA-\nAPPROVED drugs", "FDA-APPROVED drugs"),      # capitals: kept unless the document shows the word whole
]

JOINED_BY_THE_DOCUMENT = [
    ("ex-\nplained; he explained", "explained; he explained"),                    # 3c before the prefix guess of 3e
    ("non-\nprofit groups; a nonprofit", "nonprofit groups; a nonprofit"),
    ("re-\nenact it; to reenact", "reenact it; to reenact"),                      # 3c before the same-vowel guess
    ("deci-\nsion-making; the decision", "decision-making; the decision"),        # 3c before "next token is hyphenated"
    ("there-\nof the; thereof", "thereof the; thereof"),                          # 3c before "of"
    ("Mary-\nland law. Mary went by land.", "Maryland law. Mary went by land."),  # 3f never takes a capitalised fragment
    ("in-\nformation; in formation", "information; in formation"),                # 3f needs three letters
    ("evidence-\nbacked policy", "evidencebacked policy"),                        # 3g: nothing to go on
    ("WARRANTY OF MERCHANTABILI-\nTY; its merchantability", "WARRANTY OF MERCHANTABILITY; its merchantability"),
    # a hyphen kept at a line end is not evidence for the next one, and two breaks of one word are not
    # evidence for each other
    ("Second-\nAmendment rights, second-\namendment rights", "Second-Amendment rights, secondamendment rights"),
    ("regu-\nlation and regu-\nlation", "regulation and regulation"),
    # more broken words than compounds: a typesetter hyphenated this document, and then "ex" and a
    # hyphenated next token need words of the document after them
    ("regu-\nlation, regulation; statu-\ntory, statutory; an ex-\namination", "regulation, regulation; statutory, statutory; an examination"),
    ("regu-\nlation, regulation; statu-\ntory, statutory; roy-\nalty-free", "regulation, regulation; statutory, statutory; royalty-free"),
]

FFFE, SHY, HYPHEN = chr(0xFFFE), chr(0xAD), chr(0x2010)

# pdfium's marker inside a web address: the hyphen is part of the address, the halves are joined
URL_HYPHENS = [
    ("https://www.example.com/wp\x02\ndyn/content/a.html.", "https://www.example.com/wp-dyn/content/a.html."),
    ("see https://example.org/gun-industry\x02\naccountable. Next", "see https://example.org/gun-industry-accountable. Next"),
    (f"https://example.org/a-b{FFFE}\nc-d{FFFE}\ne-f g", "https://example.org/a-b-c-d-e-f g"),
    ("(https://example.org/wp\x02\ncontent/)", "(https://example.org/wp-content/)"),
    (f"www.example.org/semi{FFFE}automatic\x02rifles", "www.example.org/semi-automatic-rifles"),          # no line break left
    ("https://example.org/over2nd\x02\namendment-act.", "https://example.org/over2nd-amendment-act."),
    ("https://example.org/Brief-McKay\x02\nv.-Hutchens.pdf.", "https://example.org/Brief-McKay-v.-Hutchens.pdf."),
    # the address began on the line above: known once the lines are joined, and then its hyphens stay
    ("see https://example.org/press/\ngun-industry\x02\naccountable. Next", "see https://example.org/press/gun-industry-accountable. Next"),
    ("see https://example.org/press/\nvictory-for-moms\x02\ndemand-action. Next", "see https://example.org/press/victory-for-moms-demand-action. Next"),
    # and prose after an address is prose
    ("https://example.org/a and regu\x02\nlation", "https://example.org/a and regulation"),
]


@pytest.mark.parametrize("text,expected", KEPT_BY_THE_DOCUMENT, ids=[t.replace("\n", "|")[:60] for t, _ in KEPT_BY_THE_DOCUMENT])
def test_the_document_shows_that_a_hyphen_is_part_of_the_spelling(text, expected):
    assert r(text) == expected


@pytest.mark.parametrize("text,expected", JOINED_BY_THE_DOCUMENT, ids=[t.replace("\n", "|")[:60] for t, _ in JOINED_BY_THE_DOCUMENT])
def test_the_document_shows_that_a_hyphen_is_the_typesetters(text, expected):
    assert r(text) == expected


@pytest.mark.parametrize("text,expected", URL_HYPHENS, ids=[t.replace("\n", "|")[:60] for t, _ in URL_HYPHENS])
def test_a_marked_hyphen_inside_a_web_address_is_kept_and_the_address_joined(text, expected):
    assert r(text) == expected


# pdfium has usually replaced the hyphen with its marker before the rule runs, with or without the
# line break. Every row of the tables must come out the same in each of those forms: before, the
# marker was simply deleted before a lower-case letter and the rule above never saw it.
LITERAL_BREAK = re.compile("[-" + HYPHEN + "]\n[ \t]*")
MARKER_FORMS = {
    "U+0002": "\x02", "U+FFFE": FFFE, "U+0002 and a line break": "\x02\n", "U+FFFE, spaces and a line break": FFFE + " \n  ",
}
MARKED = [
    pytest.param(LITERAL_BREAK.sub(lambda m, form=form: form, text), expected, id=f"{name}: {text.replace(chr(10), '|')[:50]}")
    for text, expected in JOINED + KEPT + KEPT_BY_THE_DOCUMENT + JOINED_BY_THE_DOCUMENT
    if SHY not in text
    for name, form in MARKER_FORMS.items()
]


@pytest.mark.parametrize("text,expected", MARKED)
def test_a_hyphen_that_pdfium_marked_is_decided_like_a_literal_one(text, expected):
    assert "-\n" not in text and r(text) == expected


def test_a_delete_character_in_the_file_is_never_taken_for_the_readers_own_mark():
    """The reader marks an undecided hyphen with U+007F between the stages. One that comes from the
    file is a control character like any other: removed, never read as a hyphen to settle."""
    assert r("gun\x7fcontrol; gun control; gun-control") == "guncontrol; gun control; gun-control"
    assert r("gun\x7f-control") == "gun-control"
    assert P._PENDING not in r("a\x7f\x7fb regu-\nlation \x7f")


def test_no_private_mark_is_left_in_random_text():
    rng = random.Random(11)
    for _ in range(3000):
        text = "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 18)))
        out = r(text)
        assert P._PENDING not in out and "\x02" not in out and FFFE not in out, repr(text)


def test_the_pdfium_hyphen_marker_does_not_join_across_a_blank_line_either():
    assert r("Enterpris\x02\n\nes v.") == "Enterpris-\n\nes v."


# --- a range broken after its en dash -------------------------------------------------------------
#
# "152" + en dash at the end of a line and "53 (1973)" on the next: every producer breaks a line
# there, and the citation then stopped at the dash, with no pin cite and no year.

EN = chr(0x2013)

RANGE_JOINED = [
    (f"Roe v. Wade, 410 U.S. 113, 152{EN}\n53 (1973).", f"Roe v. Wade, 410 U.S. 113, 152{EN}53 (1973)."),
    (f"376 U.S. 254, 279{EN} \n  80 (1964).", f"376 U.S. 254, 279{EN}80 (1964)."),
    (f"under 12(a){EN}\n(c) of the Act", f"under 12(a){EN}(c) of the Act"),
    (f"107 Geo. L.J. 1613, 1621{EN}\n23 (2019)", f"107 Geo. L.J. 1613, 1621{EN}23 (2019)"),
    ("410 U.S. 113, 152-\n53 (1973).", "410 U.S. 113, 152-53 (1973)."),             # after a hyphen it always was
]

RANGE_NOT_JOINED = [
    (f"in the years 2019{EN}\n12", f"in the years 2019{EN}\n12"),                   # a line that is only a number is a page number
    (f"in the years 2019{EN}\n12 \nSmith v. Jones", f"in the years 2019{EN}\n12 \nSmith v. Jones"),
    (f"at 152{EN}\n\n53 (1973)", f"at 152{EN}\n\n53 (1973)"),                       # never across a blank line
    (f"the rule{EN}\nand its exceptions", f"the rule{EN}\nand its exceptions"),     # a dash in a sentence
    (f"at 152{EN}\n[^7] Id.", f"at 152{EN}\n[^7] Id."),                             # the next footnote
]


@pytest.mark.parametrize("text,expected", RANGE_JOINED, ids=[t.replace("\n", "|") for t, _ in RANGE_JOINED])
def test_a_range_broken_after_its_dash_is_joined(text, expected):
    assert r(text) == expected


@pytest.mark.parametrize("text,expected", RANGE_NOT_JOINED, ids=[t.replace("\n", "|") for t, _ in RANGE_NOT_JOINED])
def test_a_dash_at_a_line_end_that_is_not_a_range_is_left_alone(text, expected):
    assert r(text) == expected


# --- wrapped URLs: joined only when the next line continues the URL ------------------------------


URL_JOINED = [
    ("https://www.fr.gov/documents/2020/07/23\n/2020-15432/rules, the", "https://www.fr.gov/documents/2020/07/23/2020-15432/rules, the"),
    ("see https://www.gao.gov/products/\ngao-24-106481 for", "see https://www.gao.gov/products/gao-24-106481 for"),
    ("explained in https://www.gao.gov/products/gao-24-\n106481, the inquiry", "explained in https://www.gao.gov/products/gao-24-106481, the inquiry"),
    ("https://example.org/q?id=\n20220412", "https://example.org/q?id=20220412"),
]

URL_NOT_JOINED = [
    # the footer's page number, the next footnote's number, a bullet, another URL: all real cases
    ("https://www.cdc.gov/nchs/\n3", "https://www.cdc.gov/nchs/\n3"),
    ("https://www.cdc.gov/nchs/\n  12  ", "https://www.cdc.gov/nchs/\n  12  "),
    ("1 See https://www.supremecourt.gov/\n2 Smith v. Jones, 5 U.S. 137 (1803)", "1 See https://www.supremecourt.gov/\n2 Smith v. Jones, 5 U.S. 137 (1803)"),
    ("see https://example.org/q?id=\n123 Smith v. Jones, 5 U.S. 137 (1803)", "see https://example.org/q?id=\n123 Smith v. Jones, 5 U.S. 137 (1803)"),
    ("https://www.example.gov/a/\n- https://www.example.gov/b/", "https://www.example.gov/a/\n- https://www.example.gov/b/"),
    ("https://www.example.gov/a/\n• Smith v. Jones", "https://www.example.gov/a/\n• Smith v. Jones"),
    ("https://www.example.gov/a/\n2. Smith v. Jones", "https://www.example.gov/a/\n2. Smith v. Jones"),
    ("https://www.example.gov/a/\n(3) Smith v. Jones", "https://www.example.gov/a/\n(3) Smith v. Jones"),
    ("https://www.example.gov/a/\n[^3] Smith v. Jones", "https://www.example.gov/a/\n[^3] Smith v. Jones"),
    ("https://www.example.gov/a/\nhttps://www.example.gov/b/", "https://www.example.gov/a/\nhttps://www.example.gov/b/"),
    ("https://www.example.gov/a/\n/", "https://www.example.gov/a/\n/"),
    ("see https://orionpolicy.org/\nId. at 4", "see https://orionpolicy.org/\nId. at 4"),
]


@pytest.mark.parametrize("text,expected", URL_JOINED)
def test_a_wrapped_url_is_joined(text, expected):
    assert r(text) == expected


@pytest.mark.parametrize("text,expected", URL_NOT_JOINED)
def test_a_url_is_never_joined_to_what_only_follows_it(text, expected):
    assert r(text) == expected


def test_the_footnote_url_above_a_page_number_stays_a_url_the_extractor_reads_whole():
    from app.services.extractor import CitationExtractor

    page = "4 Centers for Disease Control, https://www.cdc.gov/nchs/\n3"
    cited = [c.raw_text for c in CitationExtractor().extract_all(r(page))]
    assert not any(c.endswith("/3") for c in cited), cited


# --- every expression is linear: a long run costs milliseconds, not minutes --------------------
#
# The expressions run over a whole page from an untrusted file and hold the interpreter lock, so
# a quadratic one freezes the server (64,000 letters took 49 seconds). An in-process time check
# cannot see that (the check never runs while the expression holds the lock), so this runs in a
# child with a hard stop: a regression fails the test after the stop, it does not hang the run.

RUNS = {
    "letters": "a", "capitals": "A", "mixed case": "aA", "digits": "7", "alphanumeric": "a7",
    "dots": ".", "hyphens": "-", "hyphen then newline": "a-\n", "hyphen space newline space": "a- \n ",
    "capital hyphen newline": "Ab-\n", "spaces": " ", "tabs": "\t", "newlines": "\n", "blank lines": "a\n\n",
    "url": "http://aaaaaaaa", "url lines": "http://a/\n", "url continued": "http://a/\n/b", "url numbered": "http://a/\n2 B\n",
    "marker newline": "\x02\n", "marker space newline": "\x02 \n ", "soft hyphen": "\u00ad", "soft hyphen newline": "ab\u00ad\n",
    "ligature": "ﬁ", "control": "\x01", "mixed whitespace": " \n\t", "brackets": "(", "bullets": "- ", "particles": "A-\nde ",
    # shapes that leave a hyphen for the document pass, or walk back through a token to look for a URL
    "undecided": "ab-\ncd ", "undecided with evidence": "regu-\nlation gun-\ncontrol regulation gun-control ",
    "marker word": "ab\x02cd ", "marker newline word": "ab\x02\ncd ", "marker chain": "ab\x02",
    "url marker": "http://a/b\x02\nc-", "capitals broken": "AB-\nCD ", "compound tail": "a-or-\nbc or ",
    "breaks without spaces": "ab-\ncd-\n", "hyphenated pairs": "ab-cd ", "delete characters": "a\x7fb ",
    "ranges": "12" + chr(0x2013) + "\n34 ", "dashes and line breaks": chr(0x2013) + "\n", "digits and dashes": "1" + chr(0x2013),
}


def test_every_repair_expression_is_linear_on_every_kind_of_run():
    code = (
        "import json, time\n"
        "from app.services import pdf_text as P\n"
        f"RUNS = {RUNS!r}\n"
        "out = {}\n"
        "for name, unit in RUNS.items():\n"
        "    for n in (100_000, 400_000):\n"
        "        text = (unit * (n // len(unit) + 1))[:n]\n"
        "        t = time.perf_counter(); P.repair_text(text); out[f'{name}|{n}'] = time.perf_counter() - t\n"
        "print(json.dumps(out))\n"
    )
    done = run_python(code, timeout=120)
    assert done.returncode == 0, done.stderr
    times = json.loads(done.stdout)
    for name in RUNS:
        small, large = times[f"{name}|100000"], times[f"{name}|400000"]
        assert large < 2.0, f"{name}: 400,000 characters took {large:.1f} s"
        assert large < 12 * max(small, 0.02), f"{name}: 4x the text took {large / max(small, 1e-6):.0f}x the time ({small:.3f} s -> {large:.3f} s)"


def test_a_664_byte_pdf_of_letters_is_read_in_a_blink():
    """The reviewer's case: one TJ array of 2 x 32,000 letters. Read directly (no child)."""
    code = (
        "import sys, time\n"
        "from app.services.pdf_text import read_pdf\n"
        "from tests.hostile import run_pdf\n"
        "t = time.perf_counter(); res = read_pdf(run_pdf('letters')); dt = time.perf_counter() - t\n"
        "print(dt, len(res.text))\n"
    )
    assert len(run_pdf("letters")) < 1000
    done = run_python(code, timeout=60)
    assert done.returncode == 0, done.stderr
    seconds, chars = done.stdout.split()
    assert float(seconds) < 3 and int(chars) == 64_000


# --- the regular expressions against a naive reference ------------------------------------------
#
# The line-end hyphen rule is written as one linear regular expression per stage and the URL joining
# as one pass over the lines. This is the same rule written the obvious, slow way, character by
# character, with the document's words and hyphenated pairs listed in full, and the two are compared
# on thousands of random strings built from the pieces that matter (fragments, hyphens of every
# kind, pdfium's markers, line breaks, URLs, page numbers, particles, words that vouch for each other).

PIECES = [
    "re", "regu", "lation", "GAO", "16", "552", "Smith", "Jones", "de", "la", "Cruz", "and", "of", "the", "non", "e", "FDA",
    "approved", "van", "state", "art", "A", "b", "10", "K", "x", "http://x.org/a", "https://www.gao.gov/p/", "/b-1", "3",
    "(a)", "“q”", "-", "-", "-", "‐", "\u00ad", "\n", "\n", "\n", " ", " ", "\t", "\n\n", "\x02", "￾",
    "ﬁ", "- ", "2 ", "[^2] ",
    # the document rule: words that are evidence for each other, capitals, a bracket before a URL, and
    # the delete character the reader uses for its own marks
    "regulation", "gun", "control", "gun-control", "ex", "plained", "explained", "or", "wp", "https://x.org/a-", "(",
    "MERCHANTABILI", "TY", "concealed", "carry", "concealed-carry", "Mary", "land", "\x7f", "\x7f-",
    EN, EN, "152", "53 (1973)", ")",
]


PENDING, KEPT_MARK = "\x7f", "\x7f-"       # the reader's two private marks (see pdf_text._PENDING)
ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def naive_decide(text: str) -> str:
    """Rules 1, 2 and 3a of the line-end hyphen rule, one character at a time. Whether a break is
    inside a URL is read off everything written so far (`view`: the output, except that a line
    break left in a URL for the URL joiner does not end the token)."""

    def in_url(view, frag):
        token = re.split(r"[ \t\n]", view + frag)[-1]
        return re.search(r"https?://|www\.", token, re.I) is not None

    def decide(frag, marked, hyphen, gap, nxt, after, url):
        """-> (what replaces fragment + hyphen + gap, what the URL test sees in its place)"""
        first = nxt[0]
        if first.isdigit() or "A" <= first <= "Z":
            if url:
                return frag + "-", None
            capitals = len(frag) >= 2 and frag.isalpha() and frag.isupper() and nxt[:2].isascii() and nxt[:2].isalpha() and nxt[:2].isupper()
            return frag + (PENDING if capitals else KEPT_MARK), None
        if url:
            return (frag + "-", None) if marked else (frag + hyphen + gap, frag + hyphen)
        if marked:
            if not "a" <= first <= "z":
                return frag + "-" + gap, None
        elif not (len(nxt) >= 2 and nxt[:2].isascii() and nxt[:2].isalpha() and nxt[:2].islower()):
            return frag + hyphen + gap, None
        if hyphen == "\xad":
            return frag, None
        if nxt.lower() in ("and", "or"):
            return frag + "- ", None
        hard = (
            len(frag) == 1
            or any(c.isdigit() for c in frag)
            or (len(frag) >= 2 and frag.isupper())
            or (nxt.lower() in P._PARTICLES and frag[0].isupper() and after is not None
                and (after[0].isupper() or after.lower() in P._PARTICLES))
        )
        return frag + (KEPT_MARK if hard else PENDING), None

    out, view, pos, i, n = [], [], 0, 0, len(text)
    while i < n:
        marked = text[i] == "\x02"
        if not marked and text[i] not in P._HYPHENS:
            i += 1
            continue
        s = i
        while s > pos and text[s - 1] in ALNUM:
            s -= 1
        if s == i or (s > 0 and text[s - 1] in ALNUM):
            i += 1
            continue
        # the gap: optional spaces, ONE line break, optional spaces, then something that is not a space
        j = i + 1
        while j < n and text[j] in " \t":
            j += 1
        if j < n and text[j] == "\n":
            j += 1
            while j < n and text[j] in " \t":
                j += 1
            if j >= n or text[j].isspace():
                j = None
        else:
            j = None
        if j is None:
            if not marked or i + 1 >= n or text[i + 1].isspace():
                i += 1
                continue
            j = i + 1                      # a marker with the next half right behind it
        k = j
        while k < n and not text[k].isspace() and k - j < 40:
            k += 1
        nxt, after, m = text[j:k], None, k
        if m < n and text[m] in " \t":
            while m < n and text[m] in " \t":
                m += 1
            if m < n and not text[m].isspace():
                e = m
                while e < n and not text[e].isspace() and e - m < 40:
                    e += 1
                after = text[m:e]
        before = text[pos:s]
        out.append(before)
        view.append(before)
        written, seen_as = decide(text[s:i], marked, text[i], text[i + 1:j], nxt, after, in_url("".join(view), text[s:i]))
        out.append(written)
        view.append(written if seen_as is None else seen_as)
        pos = i = j
    out.append(text[pos:])
    return "".join(out)


def naive_join_urls(text: str) -> str:
    """The URL rule, re-splitting the whole joined line at every step (quadratic, and obviously right).
    The evidence is read with the marks out of the way; once a line is joined, a marked hyphen in its
    first token is a hyphen of the address."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        cur = lines[i]
        while i + 1 < len(lines):
            parts = cur.split()
            nxt = lines[i + 1]
            seen = nxt.replace(KEPT_MARK, "-").replace(PENDING, "")
            if not parts or not seen.split() or not P._URL_START.match(parts[-1]) or len(parts[-1]) >= P._MAX_URL_CHARS:
                break
            if not P._is_url_continuation(parts[-1], seen, seen.split()):
                break
            first = nxt.split()[0]
            cur = cur.rstrip() + first.replace(KEPT_MARK, "-").replace(PENDING, "-") + nxt.lstrip()[len(first):]
            i += 1
        out.append(cur)
        i += 1
    return "\n".join(out)


def naive_page(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = text.replace(chr(0xFFFE), "\x02")
    text = re.sub(r"[\x00\x01\x03-\x08\x0b\x0e-\x1f\x7f]", "", text)
    text = text.translate(P._LIG_TABLE)
    text = naive_decide(text)
    text = re.sub(r"\x02[ \t]*\n[ \t]*(?=[a-z])", "", text)
    text = re.sub(r"\x02[ \t]*\n[ \t]*(?=[0-9A-Z])", "-", text)
    text = re.sub(r"\x02(?=[a-z])", "", text)
    text = text.replace("\x02", "-")
    text = text.replace("\xad", "").replace(chr(0x2010), "-").replace(chr(0x2011), "-")
    text = re.sub(r"(?<=[0-9)])" + EN + r"[ \t]*\n[ \t]*(?=[0-9(])(?![0-9]{1,4}[ \t]*(?:\n|\Z))", EN, text)
    return naive_join_urls(text)


def naive_settle(pages: list[str]) -> list[str]:
    """Rules 3b-3g with the whole document as evidence, the slow and obvious way: list every word
    and every hyphenated pair of the document, then walk the marks."""
    words, pairs = set(), set()
    for page in pages:
        prose = re.sub(r"(https?://|www\.)\S+", " ", page, flags=re.I).lower()
        runs = [(m.start(), m.end()) for m in re.finditer(r"[a-z0-9]+", prose)]
        for a, b in runs:
            if prose[a - 1:a] != PENDING and prose[b:b + 1] != PENDING:
                words.add(prose[a:b])
        for (a, b), (c, d) in zip(runs, runs[1:], strict=False):
            if prose[b:c] == "-" and prose[a - 1:a] != PENDING and prose[d:d + 1] != PENDING:
                pairs.add(prose[a:d])

    def breaks(page):
        """(index of the mark, fragment, next word, rest of its token) for every undecided break"""
        for i, ch in enumerate(page):
            if ch != PENDING or page[i + 1:i + 2] == "-":
                continue
            s = i
            while s > 0 and page[s - 1] in ALNUM:
                s -= 1
            e = i + 1
            while e < len(page) and page[e] in ALNUM:
                e += 1
            if s == i or e == i + 1 or not page[i + 1].isalpha():
                continue
            r = e
            while r < len(page) and not page[r].isspace() and r - e < 40:
                r += 1
            yield i, page[s:i], page[i + 1:e], page[e:r]

    real = typeset = 0
    for page in pages:
        for _, frag, word, _ in breaks(page):
            if f"{frag}-{word}".lower() in pairs:
                real += 1
            elif (frag + word).lower() in words:
                typeset += 1
    hyphenated, unhyphenated = typeset > real, typeset == 0 and real >= 2

    def keep(page, i, frag, word, rest):
        low, w = frag.lower(), word.lower()
        if f"{low}-{w}" in pairs:
            return True
        if low + w in words:
            return False
        if unhyphenated or word[0].isupper():
            return True
        both = low in words and w in words
        if low in P._STRONG_PREFIXES and not (hyphenated and low == "ex" and w not in words):
            return True
        if len(frag) >= 2 and low[-1] in "aeiou" and w[0] == low[-1]:
            return True
        if "-" in rest and (both or not hyphenated):
            return True
        if rest == "" and w in ("of", "the"):
            return True
        if page[i - len(frag) - 1:i - len(frag)] == "-":
            return low in words and len(low) >= 2
        return both and frag.islower() and len(low) >= 3 and len(w) >= 3

    out = []
    for page in pages:
        decided = {i: keep(page, i, frag, word, rest) for i, frag, word, rest in breaks(page)}
        chars = [("-" if decided.get(i) else "") if ch == PENDING and page[i + 1:i + 2] != "-" else ch for i, ch in enumerate(page)]
        out.append("".join(chars).replace(PENDING, ""))
    return out


def naive_repair(text: str) -> str:
    return naive_settle([naive_page(text)])[0]


def test_repair_text_agrees_with_the_naive_reference_on_random_text():
    rng = random.Random(20260301)
    for _ in range(4000):
        text = "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 18)))
        assert r(text) == naive_repair(text), repr(text)


def test_the_reference_itself_gets_the_tables_right():
    marked = [(row.values[0], row.values[1]) for row in MARKED]
    tables = JOINED + KEPT + UNTOUCHED + URL_JOINED + URL_NOT_JOINED + KEPT_BY_THE_DOCUMENT + JOINED_BY_THE_DOCUMENT + URL_HYPHENS + RANGE_JOINED + RANGE_NOT_JOINED
    for text, expected in tables + marked:
        assert naive_repair(text) == expected, repr(text)


def test_repair_text_is_idempotent_on_random_text():
    """Repairing repaired text changes nothing. (Soft hyphens and pdfium's markers are left out of
    the pieces: removing one at the start of a line can leave a line-end hyphen that was not
    there before, and the text is repaired once, so that corner is not worth a different rule.)"""
    rng = random.Random(7)
    pieces = [p for p in PIECES if p not in ("\u00ad", "\x02", "￾")]
    for _ in range(1500):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 18)))
        once = r(text)
        assert r(once) == once, repr(text)


# --- properties: whatever the line breaks, the text comes back -----------------------------------
#
# Seeded random documents, laid out the way a producer lays them out, then read back. A web
# address broken at any of its hyphens comes back whole. A paragraph that a word processor wrapped
# (it breaks a line only at a space or after a hyphen the author wrote) comes back as it was
# written. A paragraph a typesetter hyphenated comes back with its words whole.

SLUG_WORDS = (
    "amicus brief gun law safety court state federal press release statement victory reasonable campaign "
    "policy action demand support center report justice public v 2nd 3 2024 US Amicus FILED wp"
).split()
BREAK_FORMS = ["-\n", "\x02", FFFE, "\x02\n", FFFE + "\n", "\x02 \n  "]


def random_url(rng: random.Random) -> str:
    host = rng.choice(["https://www.example.org", "http://example.com", "www.example.gov", "https://files.example.org"])
    path = "/".join("-".join(rng.choice(SLUG_WORDS) for _ in range(rng.randint(1, 6))) for _ in range(rng.randint(1, 4)))
    return f"{host}/{path}{rng.choice(['', '.pdf', '.html', '/'])}"


def hyphens_of(url: str) -> list[int]:
    """Where a line can break in the address: a hyphen between two letters or digits."""
    return [i for i, c in enumerate(url) if c == "-" and url[i - 1].isalnum() and url[i + 1:i + 2].isalnum()]


def test_a_web_address_broken_at_any_hyphen_pdfium_marked_comes_back_whole():
    rng = random.Random(20260819)
    tried = 0
    for _ in range(300):
        url = random_url(rng)
        whole = f"Source: {url} (last visited)."
        for at in hyphens_of(url):
            for form in BREAK_FORMS[1:]:
                tried += 1
                broken = f"Source: {url[:at]}{form}{url[at + 1:]} (last visited)."
                assert r(broken) == whole, repr(broken)
    assert tried > 2000


def test_a_web_address_broken_at_several_hyphens_at_once_comes_back_whole():
    rng = random.Random(7)
    tried = 0
    for _ in range(600):
        url = random_url(rng)
        places = hyphens_of(url)
        if len(places) < 2:
            continue
        chosen = set(rng.sample(places, rng.randint(2, min(4, len(places)))))
        broken = "".join(rng.choice(BREAK_FORMS[1:]) if i in chosen else c for i, c in enumerate(url))
        tried += 1
        assert r(f"See {broken}, at 4.") == f"See {url}, at 4.", repr(broken)
    assert tried > 300


def test_a_web_address_broken_at_a_literal_hyphen_never_loses_a_character():
    """A hyphen and a line break (no marker) are joined only on the URL joiner's own evidence, so
    the line break may stay. Nothing else may change: no hyphen is ever dropped from an address."""
    rng = random.Random(3)
    for _ in range(300):
        url = random_url(rng)
        for at in hyphens_of(url):
            broken = f"Source: {url[:at]}-\n{url[at + 1:]} (last visited)."
            assert r(broken).replace("\n", "") == f"Source: {url} (last visited).", repr(broken)


COMPOUNDS = (
    "concealed-carry red-flag safe-storage common-sense gun-trafficking lost-or-stolen frame-or-receiver "
    "evidence-backed state-of-the-art Brady-led 5-year notice-and-comment self-defense non-profit so-called"
).split()
PLAIN_WORDS = (
    "the court held that a permit law is a reasonable measure and upheld it in part because of its history "
    "although many states have since adopted rules for firearms which are now before courts again"
).split()


def wrapped(words: list[str], width: int, rng: random.Random) -> str:
    """Lines no wider than `width`, broken only at a space or after a hyphen that is in the word:
    what Word, Google Docs and LibreOffice do when hyphenation is off. A line-end hyphen is written
    as pdfium hands it over (its marker and the line break) or as a hyphen and a line break."""
    lines, cur = [], ""
    for word in words:
        while True:
            room = width - len(cur) - (1 if cur else 0)
            if len(word) <= room:
                cur = f"{cur} {word}" if cur else word
                break
            cuts = [i + 1 for i, c in enumerate(word) if c == "-" and i + 1 <= room and i + 1 < len(word)]
            if cuts and cur:
                head, word = word[:cuts[-1]], word[cuts[-1]:]
                lines.append(f"{cur} {head[:-1]}{rng.choice(['-', chr(2), FFFE])}")
                cur = ""
            else:
                lines.append(cur)
                cur = ""
    return "\n".join(lines + [cur])


def test_a_paragraph_wrapped_without_hyphenation_reads_back_as_written():
    rng = random.Random(58)
    broken_at_a_hyphen = 0
    for _ in range(400):
        words = [rng.choice(COMPOUNDS) if rng.random() < 0.3 else rng.choice(PLAIN_WORDS) for _ in range(rng.randint(30, 90))]
        used = sorted({w for w in words if "-" in w})
        # every compound also stands on one line somewhere in the document, as it does in a real one
        glossary = "Terms: " + ", ".join(used) + "."
        layout = wrapped(words, rng.randint(24, 60), rng)
        broken_at_a_hyphen += sum(1 for line in layout.split("\n") if line[-1:] in ("-", chr(2), FFFE))
        got = r(layout + "\n\n" + glossary)
        paragraph, _, rest = got.partition("\n\n")
        assert paragraph.replace("\n", " ") == " ".join(words), repr(layout)
        assert rest == glossary
    assert broken_at_a_hyphen > 500


def test_text_with_no_line_end_hyphen_is_not_touched():
    rng = random.Random(4)
    for _ in range(300):
        words = [rng.choice(COMPOUNDS + PLAIN_WORDS) for _ in range(rng.randint(5, 60))]
        lines = [" ".join(words[i:i + 7]) for i in range(0, len(words), 7)]
        text = "\n".join(lines)
        assert r(text) == text


TYPESET = [
    ("regu", "lation"), ("consti", "tutional"), ("Massa", "chusetts"), ("Sulli", "van"), ("Branden", "burg"),
    ("litiga", "tion"), ("juris", "diction"), ("pro", "vision"), ("sub", "stantial"), ("impor", "tant"),
    ("Enter", "prises"), ("amend", "ment"), ("govern", "ment"), ("in", "formation"), ("ex", "plained"),
    ("re", "quirement"), ("there", "fore"), ("with", "out"), ("how", "ever"), ("law", "suit"), ("State", "ment"),
    ("co", "herent"), ("semi", "nar"), ("see", "ing"), ("deci", "sion"),
]
TYPESET_FORMS = ["-\n", HYPHEN + "\n", SHY + "\n", "\x02", FFFE, "\x02\n", FFFE + " \n  "]


def test_words_a_typesetter_broke_are_rejoined_when_the_document_has_them_whole():
    rng = random.Random(1964)
    for _ in range(300):
        chosen = rng.sample(TYPESET, rng.randint(2, 8))
        whole = [a + b for a, b in chosen]
        body = [rng.choice(PLAIN_WORDS) for _ in range(40)] + whole          # each word once, unbroken
        rng.shuffle(body)
        broken = [f"{a}{rng.choice(TYPESET_FORMS)}{b}" for a, b in chosen]
        text = " ".join(body) + "\n" + " and ".join(broken) + " end"
        assert r(text) == " ".join(body) + "\n" + " and ".join(whole) + " end", repr(text)


def test_a_fragment_that_is_not_a_word_is_rejoined_with_no_evidence_at_all():
    """One page, nothing repeated: the rule falls back on what it always did for a literal hyphen
    (keep after a strong prefix or a doubled vowel, join otherwise), now for pdfium's marker too."""
    for a, b in TYPESET:
        guess = a.lower() in P._STRONG_PREFIXES or (a[-1] in "aeiou" and b[0] == a[-1])
        for form in TYPESET_FORMS:
            expected = a + b if not guess or form.startswith(SHY) else f"{a}-{b}"
            assert r(f"the {a}{form}{b} applies") == f"the {expected} applies", (a, b, form)
