"""Every limit on what a document may be, in one place.

The server enforces these, the PDF reader reads them, `/health` publishes them, and the page
shows them to the person before they upload, so the number in the message is always the number
that is actually enforced. Each can be changed per environment without a code change.

Why these numbers (measured on synthetic documents of dense text, so real documents are lighter):

* TEXT: after the quadratic algorithms were fixed the analysis costs about 2 s per million
  characters, and the page has to send the text up and receive the analysis back inside its
  timeout on a phone connection. 1.5 million characters is roughly 250,000 words, 350 dense
  pages or about 500 ordinary ones.
* PDF PAGES: the reader keeps one page in memory at a time, so memory is flat (about 25 MB)
  and 400 pages take a few seconds. The text limit binds first for dense pages.
* UPLOAD BYTES: a file under this size can still expand to far more text, so the byte limit
  alone does not bound the work; the text limit does.
"""

import os


def _number(name: str, default: str, cast=int):
    return cast(os.getenv(name, default))


MAX_UPLOAD_MB = _number("MAX_UPLOAD_MB", "10")
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Extra bytes allowed on top of the file for the multipart envelope when the declared
# Content-Length is checked before the body is read.
UPLOAD_ENVELOPE_BYTES = 64 * 1024

# What /api/analyze accepts as a request body: the document text plus a little JSON.
# Characters are at most 4 bytes in UTF-8 but ordinary text is 1 to 2, so this is generous.
MAX_ANALYZE_BODY_BYTES = _number("MAX_ANALYZE_BODY_MB", "6") * 1024 * 1024

MAX_TEXT_CHARS = _number("MAX_TEXT_CHARS", "1500000")
MAX_PDF_PAGES = _number("MAX_PDF_PAGES", "400")

# How long reading one PDF may take. The page's own timeout is far longer; this keeps one
# hostile or enormous file from holding the single PDF reader indefinitely.
PDF_TIME_BUDGET_S = _number("PDF_TIME_BUDGET_S", "25", float)

# Pages re-read with the second PDF reader after the first one's text looked garbled.
MAX_PDF_FALLBACK_PAGES = 25

# How many claims and citations one response may carry. Further ones are counted, not sent:
# the page cannot usefully show thousands and a phone cannot render them.
MAX_CITATIONS_RETURNED = _number("MAX_CITATIONS_RETURNED", "2000")
MAX_CLAIMS_RETURNED = _number("MAX_CLAIMS_RETURNED", "500")

# Used only to turn a character count into "about N pages" in a message.
CHARS_PER_PAGE = 4300
CHARS_PER_WORD = 6


def approx_words(chars: int) -> int:
    return chars // CHARS_PER_WORD


def approx_pages(chars: int) -> int:
    return max(1, chars // CHARS_PER_PAGE)


def too_long_message(chars: int, limit: int) -> str:
    """The sentence shown when a document's text is over the limit.

    The limit is passed in, not read from here, so the number in the message is always the one
    the caller actually enforced."""
    return (
        f"This document has about {approx_words(chars):,} words ({chars:,} characters). "
        f"The limit is {limit:,} characters, roughly {approx_words(limit):,} "
        f"words or {approx_pages(limit):,} pages. Split it at a chapter or section "
        "boundary and check the parts one at a time."
    )


def as_dict() -> dict:
    """The limits as the page needs them (published by /health)."""
    return {
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_text_chars": MAX_TEXT_CHARS,
        "max_pdf_pages": MAX_PDF_PAGES,
        "approx_max_words": approx_words(MAX_TEXT_CHARS),
        "approx_max_pages": approx_pages(MAX_TEXT_CHARS),
    }
