"""Removing running headers, footers and page numbers from a PDF without touching content.

The case that prompted this: a 4-page PDF with the page's URL printed in the footer of every
page produced 4 "Website" citations. In a 300-page document it would have produced 300. The
function must remove what repeats on every page and never remove real text, however much it
repeats: "Id." recurring as the last footnote of every page, or the same statute cited on every
page, is content.
"""

from app.services.pdf_text import strip_running_lines

URL = "https://orionpolicy.org/how-congress-should-regulate-autonomous-agentic-ai-cyber-risk/"
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
