"""Shared fixtures for the Bluebook citation test suite."""

import pytest

from app.services.bluebook_rules import BluebookFormatter
from app.services.extractor import CitationExtractor


@pytest.fixture(scope="session")
def extractor() -> CitationExtractor:
    return CitationExtractor()


@pytest.fixture(scope="session")
def formatter() -> BluebookFormatter:
    return BluebookFormatter()


@pytest.fixture(scope="session")
def roundtrip(extractor, formatter):
    """Extract the first citation from a string and format it.

    This is the path a user actually exercises, so it is the path the golden
    corpus asserts on.
    """

    def _roundtrip(text: str) -> str:
        citations = extractor.extract_all(text)
        assert citations, f"no citation extracted from {text!r}"
        return formatter.format_citation(citations[0])

    return _roundtrip
