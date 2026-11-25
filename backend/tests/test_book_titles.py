"""A book's title is a title, not a paragraph.

The book pattern is "Author, Title (Year)". In a catalog of statements (two names, a description,
a quotation, a line labelled "Context:", a report's name and a year) it matched a whole entry,
which was reported as a complete book and suggested back in a book's capitals: a paragraph of
shouting on a phone. A title never holds a labelled line; its length is not the test.
"""

from app.services.extractor import CitationExtractor

extractor = CitationExtractor()


def _books(text):
    return [c for c in extractor.extract_all(text) if c.type.value == "book"]


def test_a_catalog_entry_with_a_labelled_line_is_not_a_book():
    text = (
        'Jane A. Roe & John Q. Public, ABC, statement to the Senate Subcommittee on the Constitution\n'
        '"no serious student of the subject believes that the provision prevents sensible rules"\n'
        'Context: From the ABC statement in the committee report, "The Right in Question" (1982)'
    )

    assert _books(text) == []


def test_a_label_on_the_first_line_of_a_subtitle_is_part_of_the_title():
    """Only a label at the START OF A LINE marks a catalog entry: "Title: Subtitle" is a title."""
    books = _books("Akhil Reed Amar, America's Constitution: A Biography (2005).")

    assert len(books) == 1 and books[0].title.startswith("America's Constitution: A Biography")


def test_a_long_title_is_still_a_book():
    """Length is not the test: a bound on length once dropped real titles."""
    text = (
        "Jane A. Roe, A Long Account of the Many Things That Were Said and Done at the Meeting "
        "of the Committee on a Day When Nothing Else of Any Note Took Place at All in the Town "
        "or in the Country Around It (1799)."
    )

    books = _books(text)
    assert len(books) == 1 and books[0].title.startswith("A Long Account")


def test_real_books_are_still_found():
    for text, title_start in [
        ("Richard A. Posner, Economic Analysis of Law (9th ed. 2014).", "Economic Analysis"),
        ("Adam Smith, An Inquiry into the Nature and Causes of the Wealth of Nations (1776).", "An Inquiry"),
        ("Roy M. Mersky & Donald J. Dunn, Fundamentals of Legal Research (8th ed. 2002).", "Fundamentals"),
        ("Akhil Reed Amar, The Bill of Rights: Creation and Reconstruction (1998).", "The Bill of Rights"),
    ]:
        books = _books(text)
        assert len(books) == 1, text
        assert books[0].title.startswith(title_start)
