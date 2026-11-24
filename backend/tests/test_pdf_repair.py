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
# The rule is in pdf_text.py next to _dehyphenate. These are the cases that decide it: the ones a
# reviewer found corrupted (a name, a compound, a paragraph break) and the ones that must go on
# working. When a case is in doubt the hyphen stays.

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


def test_the_pdfium_hyphen_marker_does_not_join_across_a_blank_line_either():
    assert r("Enterpris\x02\n\nes v.") == "Enterpris-\n\nes v."


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
# The line-end hyphen rule and the URL joining are written as one linear regular expression and one
# pass over the lines. This is the same rule written the obvious, slow way, character by
# character, and the two are compared on thousands of random strings built from the pieces that
# matter (fragments, hyphens of every kind, line breaks, URLs, page numbers, particles).

PIECES = [
    "re", "regu", "lation", "GAO", "16", "552", "Smith", "Jones", "de", "la", "Cruz", "and", "of", "the", "non", "e", "FDA",
    "approved", "van", "state", "art", "A", "b", "10", "K", "x", "http://x.org/a", "https://www.gao.gov/p/", "/b-1", "3",
    "(a)", "“q”", "-", "-", "-", "‐", "\u00ad", "\n", "\n", "\n", " ", " ", "\t", "\n\n", "\x02", "￾",
    "ﬁ", "- ", "2 ", "[^2] ",
]


def naive_dehyphenate(text: str) -> str:
    """The line-end hyphen rule written character by character."""

    def decide(frag, hyphen, nxt, after, start):
        if nxt[0].isdigit() or "A" <= nxt[0] <= "Z":
            return frag + "-"
        before = text[max(0, start - 300): start]
        cut = max(before.rfind(" "), before.rfind("\t"), before.rfind("\n"))
        if re.match(r"(?:https?://|www\.)", before[cut + 1:], re.I):
            return None
        if not (len(nxt) >= 2 and nxt[:2].isascii() and nxt[:2].isalpha() and nxt[:2].islower()):
            return None
        if hyphen == "\u00ad":
            return frag
        low, word = frag.lower(), nxt.lower()
        if word in ("and", "or"):
            return frag + "- "
        keep = (
            len(frag) == 1
            or any(c.isdigit() for c in frag)
            or (len(frag) >= 2 and frag.isupper())
            or low in P._STRONG_PREFIXES
            or (len(frag) >= 2 and low[-1] in "aeiou" and nxt[0].lower() == low[-1])
            or "-" in nxt
            or word in ("of", "the")
            or (word in P._PARTICLES and frag[0].isupper() and after is not None
                and (after[0].isupper() or after.lower() in P._PARTICLES))
        )
        return frag + "-" if keep else frag

    out, pos, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] not in P._HYPHENS:
            i += 1
            continue
        s = i
        while s > 0 and text[s - 1].isascii() and text[s - 1].isalnum():
            s -= 1
        j = i + 1
        while j < n and text[j] in " \t":
            j += 1
        if s == i or s < pos or j >= n or text[j] != "\n":
            i += 1
            continue
        j += 1
        while j < n and text[j] in " \t":
            j += 1
        if j >= n or text[j].isspace():
            i += 1
            continue
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
        replacement = decide(text[s:i], text[i], nxt, after, s)
        out.append(text[pos:s])
        out.append(text[s:j] if replacement is None else replacement)
        pos = i = j
    out.append(text[pos:])
    return "".join(out)


def naive_join_urls(text: str) -> str:
    """The URL rule, re-splitting the whole joined line at every step (quadratic, and obviously right)."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        cur = lines[i]
        while i + 1 < len(lines):
            parts = cur.split()
            nxt_parts = lines[i + 1].split()
            if not parts or not nxt_parts or not P._URL_START.match(parts[-1]) or len(parts[-1]) >= P._MAX_URL_CHARS:
                break
            if not P._is_url_continuation(parts[-1], lines[i + 1], nxt_parts):
                break
            cur = cur.rstrip() + lines[i + 1].lstrip()
            i += 1
        out.append(cur)
        i += 1
    return "\n".join(out)


def naive_repair(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = re.sub(r"[\x02￾][ \t]*\n[ \t]*(?=[a-z])", "", text)
    text = re.sub(r"[\x02￾][ \t]*\n[ \t]*(?=[0-9A-Z])", "-", text)
    text = re.sub(r"[\x02￾](?=[a-z])", "", text)
    text = text.replace("\x02", "-").replace("￾", "-")
    text = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", "", text)
    text = text.translate(P._LIG_TABLE)
    text = naive_dehyphenate(text)
    text = text.replace("\u00ad", "").replace("‐", "-").replace("‑", "-")
    return naive_join_urls(text)


def test_repair_text_agrees_with_the_naive_reference_on_random_text():
    rng = random.Random(20260301)
    for _ in range(4000):
        text = "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 18)))
        assert r(text) == naive_repair(text), repr(text)


def test_the_reference_itself_gets_the_tables_right():
    for text, expected in JOINED + KEPT + UNTOUCHED + URL_JOINED + URL_NOT_JOINED:
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
