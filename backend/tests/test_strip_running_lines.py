"""Removing running headers, footers and page numbers from a PDF without touching content.

The case that prompted this: a 4-page PDF with the page's URL printed in the footer of every
page produced 4 "Website" citations. In a 300-page document it would have produced 300. The
function must remove what repeats on every page and never remove real text, however much it
repeats: "Id." recurring as the last footnote of every page, or the same statute cited on every
page, is content.
"""

import pytest

from app.services.pdf_text import strip_running_lines

URL ="https://orionpolicy.org/how-congress-should-regulate-autonomous-agentic-ai-cyber-risk/"
TITLE = "How Congress Should Regulate Autonomous Agentic AI Cyber Risk - Orion Policy"


_W = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
      "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu"]


def body(i, n=6):
    """n distinct body lines for page i (distinct in their words, not just in their digits)."""
    return "\n".join(
        f"The {_W[(i * 7 + k) % 26]} panel held that the {_W[(i * 3 + k * 5 + 1) % 26]} rule governs the {_W[(i + k * 11 + 2) % 26]} claim."
        for k in range(n)
    )


def chrome_page(i, total, url=URL):
    """Chrome 'Print to PDF': date + title on top, URL and n/N at the bottom."""
    return f"11/24/2026, 10:15 AM\n{TITLE}\n{body(i)}\n{url}\n{i}/{total}"


def pages_of(fn, n):
    return [fn(i, n) for i in range(1, n + 1)]


def test_chrome_header_footer_removed_and_body_untouched():
    pages = pages_of(chrome_page, 8)
    out = strip_running_lines(pages)
    for i, p in enumerate(out, 1):
        assert URL not in p and TITLE not in p and "11/24/2026" not in p
        assert f"{i}/8" not in p.split("\n")
        assert body(i) in p


def test_url_footer_becomes_zero_bogus_website_lines_for_the_users_four_page_pdf():
    # the real case: a 4-page PDF with the page URL repeated once per page
    pages = [f"{body(i)}\n{URL}" for i in range(1, 5)]
    assert sum(p.count(URL) for p in pages) == 4
    out = strip_running_lines(pages)
    assert sum(p.count(URL) for p in out) == 0


def test_digits_are_normalised_page_x_of_y():
    pages = [f"{body(i)}\nPage {i} of 90" for i in range(1, 8)]
    out = strip_running_lines(pages)
    assert all("Page" not in p for p in out)


def test_nothing_is_removed_from_very_short_documents():
    one = [f"{body(1)}\n{URL}"]
    two = [f"{body(i)}\n{URL}" for i in (1, 2)]
    assert strip_running_lines(one) == one
    assert strip_running_lines(two) == two


def test_three_pages_remove_boilerplate_but_not_ordinary_text():
    boiler = [f"{body(i)}\n{URL}" for i in (1, 2, 3)]
    assert all(URL not in p for p in strip_running_lines(boiler))
    ordinary = [f"{body(i)}\nThe Committee on Rules and Procedure" for i in (1, 2, 3)]   # ordinary text, 3 pages
    assert strip_running_lines(ordinary) == ordinary


def test_ordinary_header_needs_five_pages():
    four = [f"Smith Report\n{body(i)}" for i in range(1, 5)]
    assert strip_running_lines(four) == four
    five = [f"Smith Report\n{body(i)}" for i in range(1, 6)]
    assert all("Smith Report" not in p for p in strip_running_lines(five))


def test_recurring_Id_is_never_deleted():
    # "Id." is the last line of the footnote block on every page
    pages = [f"{body(i)}\n1 Compare the dissent below.\n2 Id." for i in range(1, 9)]
    out = strip_running_lines(pages)
    assert all(p.endswith("2 Id.") for p in out)       # the "# Id." key repeats on every page and must survive
    pages = [f"{body(i)}\nId." for i in range(1, 9)]
    assert strip_running_lines(pages) == pages
    pages = [f"{body(i)}\nId. at {10 + i}" for i in range(1, 9)]   # varying pincite normalises to one key
    assert strip_running_lines(pages) == pages


def test_repeated_legitimate_citation_is_never_deleted():
    cites = ["47 U.S.C. § 230(c)(1).", "Brandenburg v. Ohio, 395 U.S. 444, 447 (1969).", "See 60 Fed. Reg. 50,379 (Sept. 29, 1995).",
             "Pub. L. No. 111-148, 124 Stat. 119 (2010).", "H.R. Rep. No. 116-123 (2019).", "Smith, supra note 12, at 4."]
    for c in cites:
        pages = [f"{body(i)}\n{c}" for i in range(1, 9)]
        assert strip_running_lines(pages) == pages, c


def test_vetoed_lines_survive():
    pages = [f"{body(i)}\nSee also the agency guidance" for i in range(1, 9)]
    assert strip_running_lines(pages) != pages
    assert strip_running_lines(pages, veto=lambda line: line.startswith("See also")) == pages


def test_only_edge_lines_are_touched():
    # the same sentence in the middle of every page is body text, not a header
    mid = "The agency repeated this sentence on every page."
    pages = [f"{body(i, 3)}\n{mid}\n{body(i + 100, 5)}" for i in range(1, 9)]
    assert strip_running_lines(pages) == pages


def test_alternating_odd_even_headers():
    pages = [("Jane Q. Author\n" if i % 2 else "Rules and Standards in Administrative Law\n") + body(i) for i in range(1, 11)]
    out = strip_running_lines(pages)
    assert all("Jane Q. Author" not in p and "Rules and Standards" not in p for p in out)


def test_header_missing_on_first_page():
    pages = [body(1)] + [f"Running Title Here\n{body(i)}" for i in range(2, 9)]
    out = strip_running_lines(pages)
    assert all("Running Title Here" not in p for p in out) and out[0] == pages[0]


def test_page_numbers_that_climb_are_removed_numbers_that_do_not_are_kept():
    climbing = [f"{body(i)}\n{i}" for i in range(1, 9)]
    assert all(p.split("\n")[-1] != str(i) for i, p in enumerate(strip_running_lines(climbing), 1))
    offset = [f"{body(i)}\n{i + 40}" for i in range(1, 9)]          # article starting at page 41
    assert all(not p.split("\n")[-1].isdigit() for p in strip_running_lines(offset))
    constant = [f"{body(i)}\n7" for i in range(1, 9)]                 # a "7" that never changes is not a page number
    assert strip_running_lines(constant) == constant


def test_short_lines_that_repeat_are_kept():
    for short in ["Id.", "Ex. 4", "Tr.", "Ibid.", "No.", "A."]:
        pages = [f"{body(i)}\n{short}" for i in range(1, 9)]
        assert strip_running_lines(pages) == pages, short


def test_header_on_top_or_bottom_of_stream_order():
    # pdfium writes Chromium's header/footer last and reportlab's first; both must work
    first = [f"Footer text here\n{body(i)}" for i in range(1, 8)]
    last = [f"{body(i)}\nFooter text here" for i in range(1, 8)]
    assert all("Footer text here" not in p for p in strip_running_lines(first))
    assert all("Footer text here" not in p for p in strip_running_lines(last))


def test_repetition_below_fraction_is_kept():
    pages = [(f"Maybe Header\n{body(i)}" if i in (1, 4) else body(i)) for i in range(1, 11)]
    assert strip_running_lines(pages) == pages


def test_report_and_length_preserved_and_idempotent():
    pages = pages_of(chrome_page, 6)
    out, report = strip_running_lines(pages, return_report=True)
    assert len(out) == len(pages) and sum(report.values()) >= 6 * 3
    assert strip_running_lines(out) == out


def test_empty_and_blank_pages():
    assert strip_running_lines([]) == []
    assert strip_running_lines(["", "  ", "\n"]) == ["", "  ", "\n"]
    pages = ["", f"{body(1)}\n{URL}", "", f"{body(2)}\n{URL}", f"{body(3)}\n{URL}", f"{body(4)}\n{URL}"]
    out = strip_running_lines(pages)
    assert all(URL not in p for p in out) and len(out) == 6


def test_page_footer_zone_overlap_on_tiny_pages():
    # pages with fewer lines than 2*edge_lines: zones overlap, nothing should crash or double-remove
    pages = [f"Header\nthe {_W[i]} line\nFooter" for i in range(1, 8)]
    out = strip_running_lines(pages)
    assert out == [f"the {_W[i]} line" for i in range(1, 8)]


def test_page_numbers_survive_other_numeric_lines_near_the_edge():
    # superscript footnote markers extracted on their own line must not hide the page numbers,
    # and must not be removed with them
    first = [9, 41, 2, 38, 15, 27, 5, 19]
    second = [17, 4, 33, 8, 21, 26, 29, 12]
    pages = [f"{first[i - 1]}\n{body(i)}\n{second[i - 1]}\n{i}" for i in range(1, 9)]
    out = strip_running_lines(pages)
    assert all(p.split("\n")[-1] != str(i) for i, p in enumerate(out, 1))                 # page numbers gone
    assert all(p.split("\n")[0] == str(first[i - 1]) for i, p in enumerate(out, 1))       # other number lines kept
    assert all(p.split("\n")[-1] == str(second[i - 1]) for i, p in enumerate(out, 1))


def test_three_letter_running_head_like_vol_is_removed_but_Id_is_not():
    pages = [f"[Vol. 97:1\n{body(i)}\nId." for i in range(1, 9)]
    out = strip_running_lines(pages)
    assert all(not p.startswith("[Vol.") and p.endswith("Id.") for p in out)


def test_pleading_line_numbers_are_not_mistaken_for_page_numbers():
    page = "\n".join(str(n) for n in range(1, 29))
    pages = [page for _ in range(8)]
    out = strip_running_lines(pages)
    assert sum(len(p.split()) for p in out) >= 8 * 26       # at most a page-number-like line per page is touched, never the column


# --- lines that differ from page to page are not one running line ------------------------------
#
# Lines are grouped with their digits blanked out so that "Page 3 of 90" and "Page 4 of 90" are
# one line. Before the digits of a group were checked, any lines of one shape were taken for a
# running footer and ALL removed: one footnote per page citing congress.gov/bill/.../house-bill/N, or
# a different regulations.gov docket id on each page, vanished without a trace.


def _footnote_pages(make_line, n=8):
    return [f"{body(i)}\n{make_line(i)}" for i in range(1, n + 1)]


@pytest.mark.parametrize(
    "make_line",
    [
        lambda i: f"https://www.congress.gov/bill/117th-congress/house-bill/{i}",
        lambda i: f"https://www.congress.gov/bill/117th-congress/house-bill/{[4021, 17, 988, 2503, 61, 3340, 725, 1198][i - 1]}",
        lambda i: f"{i} See https://www.congress.gov/bill/117th-congress/house-bill/{i}",
        lambda i: f"https://www.regulations.gov/document/EPA-HQ-OAR-2021-0317-{i:04d}",
        lambda i: f"https://www.regulations.gov/docket/EPA-HQ-OAR-2021-{[317, 52, 4410, 9, 871, 23, 640, 112][i - 1]:04d}",
        lambda i: f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={3000000 + i * 7}",
        lambda i: f"www.example.gov/report/{i}/summary",
    ],
    ids=["bill climbing", "bill unrelated", "numbered footnote", "docket document", "docket random", "ssrn", "www"],
)
def test_footnote_urls_that_differ_only_in_a_number_are_all_kept(make_line):
    pages = _footnote_pages(make_line)
    assert strip_running_lines(pages) == pages


def test_the_same_url_on_every_page_is_still_a_footer_but_a_different_one_beside_it_is_kept():
    pages = [f"{body(i)}\n{i} See https://www.congress.gov/bill/117th-congress/house-bill/{i}\n{URL} {i}/8" for i in range(1, 9)]
    out = strip_running_lines(pages)
    assert all(URL not in p for p in out)
    assert all(f"house-bill/{i}" in p for i, p in enumerate(out, 1))


def test_a_boilerplate_line_must_be_on_four_fifths_of_the_pages_to_go():
    """boilerplate_fraction: 8 of 10 pages is a footer, 7 of 10 or 4 of 10 is a footnote that recurs."""
    for count, removed in [(10, True), (8, True), (7, False), (4, False), (3, False)]:
        pages = [(f"{body(i)}\n{URL}" if i <= count else body(i)) for i in range(1, 11)]
        out = strip_running_lines(pages)
        assert (sum(URL in p for p in out) == 0) is removed, count


def test_digits_that_do_not_count_pages_keep_a_line():
    """Same shape, numbers that are not a page counter: a recurring heading with other numbers."""
    figures = [37, 12, 58, 91, 5, 63, 29, 84]
    pages = [f"Annual figures {figures[i - 1]}\n{body(i)}" for i in range(1, 9)]
    assert strip_running_lines(pages) == pages


def test_a_court_header_with_a_page_counter_and_constant_numbers_is_removed():
    header = "Case 1:20-cv-01234-ABC Document 56 Filed 01/02/21 Page {i} of 25"
    pages = [f"{header.format(i=i)}\n{body(i)}" for i in range(1, 9)]
    out = strip_running_lines(pages)
    assert all("Case 1:20" not in p for p in out)
    # the same header, but the document number is not constant: those are different docket entries
    pages = [f"Case 1:20-cv-01234-ABC Document {[56, 3, 71, 8, 12, 40, 99, 21][i - 1]} Filed 01/02/21 Page {i} of 25\n{body(i)}" for i in range(1, 9)]
    assert strip_running_lines(pages) == pages


def test_bates_numbers_that_climb_are_removed():
    pages = [f"{body(i)}\nDEF-{i + 4100:06d}" for i in range(1, 9)]
    assert all("DEF-" not in p for p in strip_running_lines(pages))


def test_a_running_head_with_the_page_number_in_it_is_removed():
    pages = [f"{body(i)}\nTHE LAW OF THINGS {i + 120}" for i in range(1, 11)]
    assert all("THE LAW OF THINGS" not in p for p in strip_running_lines(pages))


# --- lines that are too long, and numbers that are too long, are never candidates ----------------


def test_a_long_line_is_never_a_running_line():
    long_line = "This sentence is repeated at the foot of every page, word for word. " * 6
    assert len(long_line) > 300
    pages = [f"{body(i)}\n{long_line.strip()}" for i in range(1, 9)]
    assert strip_running_lines(pages) == pages


@pytest.mark.parametrize("digits", [5000, 30_000])
def test_a_line_of_digits_beyond_python_integer_limit_is_not_a_page_number_and_not_an_error(digits):
    """int() refuses more than 4,300 digits: this used to raise ValueError (a 415 'could not be read')."""
    pages = [f"{body(i)}\n{'7' * digits}" for i in range(1, 9)]
    assert strip_running_lines(pages) == pages
    short = [f"{body(i)}\n{'7' * 9}{i}" for i in range(1, 9)]       # ten digits: also too long to be a page number
    assert strip_running_lines(short) == short


def test_long_numbers_that_climb_with_the_page_are_not_page_numbers_either():
    pages = [f"{body(i)}\n{10**11 + i}" for i in range(1, 9)]
    assert strip_running_lines(pages) == pages


# --- nothing that holds a citation is removed -------------------------------------------------


def _golden_citation_lines():
    import json
    from pathlib import Path

    gold = json.loads((Path(__file__).resolve().parents[2] / "shared" / "spec_golden.json").read_text())
    lines = [c["input"] for c in gold["cases"] if c["type_id"] is not None]
    lines += [d["input"] for d in gold["document_cases"]]
    from app.services.extractor import CitationExtractor

    extractor = CitationExtractor()
    return [
        ln for ln in dict.fromkeys(lines)
        if len(ln) <= 300 and "\n" not in ln and any(c.type.value != "website" for c in extractor.extract_all(ln))
    ]


GOLDEN_LINES = _golden_citation_lines()


def test_there_are_real_citations_to_check_against():
    assert len(GOLDEN_LINES) >= 40


@pytest.mark.parametrize("line", GOLDEN_LINES, ids=[ln[:50] for ln in GOLDEN_LINES])
def test_a_citation_repeated_on_every_page_is_never_removed_when_the_extractor_is_the_veto(line):
    from app.services.pdf_text import _citation_veto

    pages = [f"{body(i)}\n{line}" for i in range(1, 9)]
    assert strip_running_lines(pages, veto=_citation_veto) == pages


def test_the_extractor_veto_does_not_protect_a_footer_that_is_only_a_web_address():
    from app.services.pdf_text import _citation_veto

    assert _citation_veto(URL) is False
    assert _citation_veto("Orion Policy | Page 3") is False
    assert _citation_veto("47 CFR 54.101") is True


def test_read_pdf_protects_unusual_citations_that_repeat_at_the_foot_of_every_page():
    """The wiring: read_pdf asks the extractor, which knows forms (47 CFR 54.101) the quick patterns do not."""
    from app.services.pdf_text import read_pdf
    from tests.docfactory import make_pdf_pages

    pages = [
        [(720 - 14 * k, f"Para {i} line {k}: the {_W[(i * 5 + k) % 26]} panel held that the {_W[(i + k * 3) % 26]} rule applies to the {_W[(i * 2 + k) % 26]} claim.")
         for k in range(12)] + [(40, "47 CFR 54.101")]
        for i in range(8)
    ]
    text = read_pdf(make_pdf_pages(pages)).text
    assert text.count("47 CFR 54.101") == 8


def _random_document(rng):
    """Random pages: unique body lines, with lines drawn from a pool at the top and bottom of each
    page. Pool lines are boilerplate, citations (some with numbers that vary) and short words."""
    n = rng.randint(3, 12)
    cites = rng.sample(GOLDEN_LINES, 6)
    pool = [URL, TITLE, "Confidential", "Id.", "Smith Report", *cites,
            "See {n} U.S.C. § 1983.", "Brandenburg v. Ohio, 395 U.S. {n}, 447 (1969).", "Page {n} of 40", "Doc. {n}", "{n}"]
    chosen = rng.sample(pool, rng.randint(1, 5))
    pages = []
    for i in range(1, n + 1):
        top, bottom = [], []
        for line in chosen:
            if rng.random() < 0.9:
                num = i if rng.random() < 0.6 else rng.randint(1, 900)
                (top if rng.random() < 0.4 else bottom).append(line.replace("{n}", str(num)))
        pages.append("\n".join([*top, body(i, rng.randint(2, 6)), *bottom]))
    return pages


def test_no_line_with_a_citation_is_ever_removed_from_a_random_document():
    """The property that matters most: whatever repeats, whatever the numbers do, a line the
    extractor reads as a citation (a web address aside) survives."""
    import random

    from app.services.pdf_text import _citation_veto

    rng = random.Random(20260301)
    removed_any = 0
    for _ in range(300):
        pages = _random_document(rng)
        out = strip_running_lines(pages, veto=_citation_veto)
        for before, after in zip(pages, out, strict=True):
            remaining = after.split("\n")
            for line in before.split("\n"):
                if line in remaining:
                    remaining.remove(line)
                elif line.strip():
                    removed_any += 1
                    assert not _citation_veto(line), f"removed a citation: {line!r}"
    assert removed_any > 50, "the generator never made anything removable, so the property proved nothing"
