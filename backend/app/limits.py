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

# Every other endpoint takes one small JSON object (a citation, a few lines of pasted text).
MAX_SMALL_BODY_BYTES = _number("MAX_SMALL_BODY_KB", "1024") * 1024

MAX_TEXT_CHARS = _number("MAX_TEXT_CHARS", "1500000")
MAX_PDF_PAGES = _number("MAX_PDF_PAGES", "400")

# How long reading one PDF may take. The page's own timeout is far longer; this keeps one
# hostile or enormous file from holding the single PDF reader indefinitely.
PDF_TIME_BUDGET_S = _number("PDF_TIME_BUDGET_S", "25", float)

# Pages re-read with the second PDF reader after the first one's text looked garbled.
MAX_PDF_FALLBACK_PAGES = 25

# How many citations one analysis will build. Each costs about 2 KB, and the text limit alone
# would allow 375,000 of them (a text of bare "Id."): 800 MB before anything is capped for the
# response. A real 500-page document has a few thousand.
MAX_CITATIONS_ANALYZED = _number("MAX_CITATIONS_ANALYZED", "50000")

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


def too_long_message(chars: int, limit: int, exact: bool = True) -> str:
    """The sentence shown when a document's text is over the limit.

    The limit is passed in, not read from here, so the number in the message is always the one
    the caller actually enforced. `exact=False` is for a reader that stopped as soon as the
    limit was passed and so does not know the true size."""
    if exact:
        size = f"about {approx_words(chars):,} words ({chars:,} characters)"
    else:
        size = f"more than {limit:,} characters"
    return (
        f"This document has {size}. "
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


# =====================================================================================
# Reading documents in a child process, and the bounds inside the readers
# (services/sandbox.py, services/parse_worker.py, services/pdf_text.py, services/parser.py)
#
# Every upload is parsed in a short-lived child process, because the two things that took the
# server down cannot be stopped from inside it: native code (pdfium aborts on an allocation
# failure instead of raising) and a regular expression that holds the interpreter lock (no
# deadline, thread or timeout can interrupt it). A child can be killed. Each of these can be
# changed per environment without a code change.
#
# What the memory limit is: RLIMIT_AS bounds the child's ADDRESS SPACE (virtual memory,
# including mapped libraries and reserved-but-unused ranges), not its resident memory, and it
# is set by the child on itself. It is a ceiling on one upload, not a guarantee about the
# container: the host's own memory limit still applies to the sum of the server and its
# children, so PARSE_MAX_CONCURRENT x PARSE_CHILD_MEM_MB should stay well under it.
# =====================================================================================

# Address-space ceiling, CPU-seconds ceiling and wall-clock ceiling for one parse. The wall
# clock is the one the parent enforces (it kills and reaps the child); the CPU ceiling is a
# second, independent stop, and the child also arms an alarm so it ends itself if the parent
# is gone. PDF_TIME_BUDGET_S (above) is the polite stop inside the reader and is shorter than
# all three, so an ordinary slow PDF gets a readable message before any kill.
PARSE_CHILD_MEM_MB = _number("PARSE_CHILD_MEM_MB", "1024")
PARSE_CHILD_CPU_S = _number("PARSE_CHILD_CPU_S", "40")
PARSE_WALL_S = _number("PARSE_WALL_S", "35", float)

# Children running at once, and uploads allowed to wait for one. Beyond that the server says
# it is busy (503 with Retry-After) instead of stacking up work. Waiting is bounded in time as
# well, and it is not part of the child's own budget.
PARSE_MAX_CONCURRENT = _number("PARSE_MAX_CONCURRENT", "2")
PARSE_MAX_QUEUE = _number("PARSE_MAX_QUEUE", "3")
PARSE_QUEUE_WAIT_S = _number("PARSE_QUEUE_WAIT_S", "20", float)
PARSE_RETRY_AFTER_S = _number("PARSE_RETRY_AFTER_S", "5")

# PDF: a page with more characters than this is read without layout analysis (its text is
# kept; footnote markers and pleading-number removal are skipped for that page). Layout costs
# about 800 bytes per character, and no real page holds anything like this much text.
PDF_MAX_PAGE_CHARS = _number("PDF_MAX_PAGE_CHARS", "60000")
# The second PDF reader (pdfminer) is quadratic or worse in the number of text boxes. It is
# tried only on a page whose text shows real garbling, only if the page is not larger than
# this, and for no longer than this in total.
PDF_SECOND_OPINION_MAX_CHARS = _number("PDF_SECOND_OPINION_MAX_CHARS", "30000")
PDF_SECOND_OPINION_BUDGET_S = _number("PDF_SECOND_OPINION_BUDGET_S", "10", float)

# Word: an XML part is read as a stream, so memory does not grow with its size, but its
# element count and nesting depth are bounded. A 250,000-word document written by Word has
# well under a million elements and nests about 30 levels deep; 4 million and 200 leave room
# and still stop a 40 MB part of "<w:p/>" or an unclosed "<w:b>" repeated ten million times.
DOCX_MAX_ELEMENTS = _number("DOCX_MAX_ELEMENTS", "4000000")
DOCX_MAX_DEPTH = _number("DOCX_MAX_DEPTH", "200")


def complex_message(reason: str) -> str:
    """The sentence shown when a document needs more than one upload is allowed to use."""
    return (
        f"This document is too complex to read within this server's limits ({reason}). "
        "Export it again or split it."
    )
