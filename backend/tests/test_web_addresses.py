"""A web address is the address, without the sentence punctuation after it.

"Source: https://example.org/a.html." was reported with the sentence's full stop as the last
character of the address, and the suggestion then added another ("...html.."). About 170
addresses in one real paper were wrong that way.
"""

import time

import pytest

from app.services.bluebook_rules import BluebookFormatter
from app.services.extractor import CitationExtractor, trim_url

extractor = CitationExtractor()
formatter = BluebookFormatter()


def sites(text):
    return [c for c in extractor.extract_all(text) if c.type.value == "website"]


# (text, the addresses in it)
ADDRESSES = [
    ("Source: https://example.org/reports/annual.html.", ["https://example.org/reports/annual.html"]),
    (
        "See https://example.org/a, https://example.org/b; and https://example.org/c: three.",
        ["https://example.org/a", "https://example.org/b", "https://example.org/c"],
    ),
    ("Is it at https://example.org/q?a=1&b=2? Yes! At https://example.org/x!",
     ["https://example.org/q?a=1&b=2", "https://example.org/x"]),
    # an unbalanced closing bracket or quote is not part of the address ...
    ("(see https://example.org/page) and [a link](https://example.org/md).",
     ["https://example.org/page", "https://example.org/md"]),
    ("\"https://example.org/quoted\" and 'https://example.org/single' and <https://example.org/angle>.",
     ["https://example.org/quoted", "https://example.org/single", "https://example.org/angle"]),
    # ... and what is inside the address stays: full stops, balanced brackets, another address
    ("Also https://en.wikipedia.org/wiki/Roe_(disambiguation).", ["https://en.wikipedia.org/wiki/Roe_(disambiguation)"]),
    ("https://example.org/v1.2/file.tar.gz, and https://example.org/path/.",
     ["https://example.org/v1.2/file.tar.gz", "https://example.org/path/"]),
    ("https://web.archive.org/web/20240224044940/https://example.org/brief.pdf.",
     ["https://web.archive.org/web/20240224044940/https://example.org/brief.pdf"]),
    ("Source:https://example.org/no-space.pdf.", ["https://example.org/no-space.pdf"]),
    ("https://example.org/a%20b,%20c-d.PDF\nNext line", ["https://example.org/a%20b,%20c-d.PDF"]),
    ("It is at https://example.org/end", ["https://example.org/end"]),
]


@pytest.mark.parametrize(("text", "expected"), ADDRESSES, ids=[t[0][:45] for t in ADDRESSES])
def test_the_address_ends_where_the_address_ends(text, expected):
    found = sites(text)

    assert [c.url for c in found] == expected
    # the span is exactly the address: positions are what the page highlights
    assert [text[c.position_start:c.position_end] for c in found] == expected
    for c in found:
        suggestion = formatter.format_citation(c)
        assert ".." not in suggestion
        assert suggestion.count(c.url) == 1


@pytest.mark.parametrize(
    ("candidate", "address"),
    [
        ("https://a.example/b.", "https://a.example/b"),
        ("https://a.example/b.,;:!?", "https://a.example/b"),
        ("https://a.example/b).", "https://a.example/b"),
        ("https://a.example/b_(c)).", "https://a.example/b_(c)"),
        ("https://a.example/b_(c)", "https://a.example/b_(c)"),
        ("https://a.example/b]'\"", "https://a.example/b"),
        ("https://a.example/b[1]", "https://a.example/b[1]"),
        ("https://a.example/b...", "https://a.example/b"),
    ],
)
def test_trim_url(candidate, address):
    assert trim_url(candidate) == address


class TestAnAddressBrokenBeforeItsExtension:
    """A PDF's layout can break an address at any character. The one break that can be
    rejoined without guessing is the one before a file extension that stands alone at the
    start of the next line."""

    def test_the_extension_on_the_next_line_is_rejoined(self):
        text = "Source: https://www.example.gov/docket/24-1046/Brief%20FINAL%2012.23.25.\npdf.\nNext entry."
        (site,) = sites(text)

        assert site.url == "https://www.example.gov/docket/24-1046/Brief%20FINAL%2012.23.25.pdf"
        assert text[site.position_start:site.position_end].endswith("12.23.25.\npdf")

    def test_a_word_that_merely_follows_a_full_stop_is_not_an_extension(self):
        text = "See https://example.org/report.\npdf versions are available on request."
        (site,) = sites(text)

        assert site.url == "https://example.org/report"


class TestTheDayTheAuthorLooked:
    def test_last_visited_is_read_from_the_document(self):
        text = "See Jane Roe, A Title, https://example.org/a (last visited Mar. 3, 2024)."
        (site,) = sites(text)

        assert site.url == "https://example.org/a"
        assert site.access_date == "Mar. 3, 2024"
        assert text[site.position_start:site.position_end] == "https://example.org/a (last visited Mar. 3, 2024)"

    def test_no_date_is_reported_when_the_document_gives_none(self):
        (site,) = sites("Source: https://example.org/a.")

        assert site.access_date is None


def test_nothing_else_is_read_out_of_the_inside_of_an_address():
    text = "Source: https://files.example.org/2019/Smith-v.-Jones-9th-Cir.-18-55717-Amicus-Brief.pdf."
    found = extractor.extract_all(text)

    assert [c.type.value for c in found] == ["website"]


@pytest.mark.parametrize(
    "flood",
    [
        "https://a.example/" + "a" * 30_000,
        "https://a.example/" + ")" * 30_000,
        "https://a.example/" + "." * 30_000,
        ("https://a.example/" + "a)" * 900 + " ") * 16,
        "https://a.example/b. " * 1500,
        "https://a.example/b.\npdf.\n" * 1200,
        "https://a.example/b (last visited Mar. 3, 2024) " * 600,
    ],
    ids=["long", "brackets", "dots", "bracket-pairs", "many", "wrapped", "visited"],
)
def test_addresses_are_read_in_linear_time(flood):
    started = time.perf_counter()
    extractor.extract_all(flood)
    assert time.perf_counter() - started < 2.0
