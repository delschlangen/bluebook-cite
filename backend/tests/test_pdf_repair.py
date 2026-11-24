"""Repairing what PDF producers do to text: ligature code points, line-end hyphens, soft
hyphens, the marker pdfium writes where it removed a hyphen, and wrapped URLs."""

from app.services.pdf_text import repair_text as r


def test_ligature_code_points_are_expanded():
    assert r("oﬃce ﬁnal ﬂoor eﬀect") == "office final floor effect"


def test_line_end_hyphen_inside_a_word_is_dropped_and_joined():
    assert r("the regu-\nlation applies") == "the regulation applies"
    assert r("the regu‐\n  lation") == "the regulation"
    assert r("the regu­\nlation") == "the regulation"


def test_real_hyphens_in_numbers_and_identifiers_are_kept():
    assert r("GAO-\n16-552") == "GAO-16-552"
    assert r("Pub. L. No. 111-\n148") == "Pub. L. No. 111-148"
    assert r("Ohio-\nBased") == "Ohio-Based"


def test_soft_hyphen_inside_a_word_is_removed():
    assert r("sta­ndard") == "standard"


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
