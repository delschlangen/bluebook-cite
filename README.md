# Bluebook Citation Generator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Deploy](https://img.shields.io/badge/demo-live-brightgreen)](https://delschlangen.github.io/bluebook-cite/)

**Automated legal citation formatting, completion, and verification using Bluebook 21st Edition rules.**

A free, open-source tool for law students, legal professionals, and law review editors to automatically format, complete, and verify legal citations. Upload a document and get instant Bluebook-compliant citation suggestions.

**[Try it live](https://delschlangen.github.io/bluebook-cite/)**

## Fix one citation

Paste what you have. You get back the Bluebook form, or a precise list of what
is missing.

```
Moody v. NetChoice
   -> Moody v. NetChoice, 603 U.S. 707 (2024).
      verify: courtlistener.com/opinion/9/moody-v-netchoice-llc/

Brandenburg v Ohio
   -> still needs: volume number, reporter, first page, year
```

**Nothing is reported as found unless it can be linked to a real record.** Every
LLM will happily invent a citation that looks right. This tool will tell you it
could not find one instead. A result is only marked resolved when it came from
your own complete input or from a matched record with a verification URL.

## Features

- **Single-citation repair** - Paste a partial or messy citation and get the corrected form, a list of the missing fields, or candidate matches to choose between
- **Citation Extraction** - Automatically detects cases, statutes, regulations, law review articles, and books from uploaded documents
- **Citation Completion** - Looks up incomplete citations using free legal databases (CourtListener, CrossRef, Open Library)
- **Bluebook Formatting** - Formats citations per Bluebook 21st Edition rules with proper abbreviations, italics, and punctuation
- **Context-Aware Short Forms** - Suggests *Id.*, *supra*, and short case forms based on document context and citation sequence
- **Unsourced Claim Detection** - Identifies factual, legal, and statistical statements that may need supporting citations

Copying a result puts real italics on the clipboard, so it pastes correctly into
Word or Google Docs instead of arriving full of asterisks.

## Tech Stack

- **Backend**: Python 3.11 / FastAPI
- **Frontend**: React + Vite + TailwindCSS
- **Deployment**: Railway (backend) + GitHub Pages (frontend)
- **APIs**: CourtListener, CrossRef, Open Library, eCFR (all free, no API keys required)

## Local Development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /api/repair` | Diagnose and complete a single pasted citation |
| `POST /api/upload` | Upload a document for analysis |
| `POST /api/analyze` | Extract and analyze citations from text |
| `POST /api/format` | Format a citation per Bluebook rules |
| `POST /api/lookup/case` | Look up case information |

`/api/repair` returns one of four statuses. `resolved` means complete and
verifiable. `ambiguous` means candidates were found but none was confident
enough to apply. `incomplete` means the gaps are known but no record matched.
`unparseable` means it is not recognizable as a citation.

```bash
curl -X POST https://<backend>/api/repair \
  -H 'Content-Type: application/json' \
  -d '{"text": "Moody v. NetChoice", "style": "law_review"}'
```

`style` is `law_review` (the default) or `practitioner`. The response also carries `kind`
and `kind_label` (what the citation was recognised as), `format_confidence`, a `template`
showing the finished shape with gaps marked, and `missing_details` giving the rule that
governs each missing part.

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests && pytest
```

CI runs exactly this on every pull request, and the deploy workflow is gated
behind it. See [DEPLOYMENT.md](DEPLOYMENT.md) for how the two Docker build
contexts differ.

## Supported citation types

Paste any of these, whole or partial. Each is read, corrected, and, if something is
missing, shown in its finished shape with the gaps marked and the rule that governs each.

| Family | Kinds |
|---|---|
| Cases | Federal and state decisions, with a lookup against CourtListener |
| Constitutions and court rules | U.S. and state constitutions, the Federal Rules of Civil, Criminal and Appellate Procedure and of Evidence |
| Statutes | U.S. Code, Public Laws and the Statutes at Large |
| Regulations and executive materials | C.F.R., Federal Register, executive orders |
| Legislative materials | Bills, committee reports, the Congressional Record (daily and bound) |
| Reports | GAO and CRS reports |
| Newspapers and periodicals | Newspaper articles, law review articles |
| Books | Books and treatises, including multiple authors |
| Restatements and model codes | Restatements, the Model Penal Code, the UCC |

A few more (hearings, state statutes, treaties, record citations) are **guidance only**:
the tool shows the finished shape and the rules, but will not rewrite a pasted citation
of those kinds, because their formats could only be sourced from search summaries.

## Document limits

"Check a document" takes Word (`.docx`), PDF and plain text. The upload box states the limits
before anyone chooses a file, using the values the server publishes. A document over a limit is
refused with a message that says which limit and what to do, never with a bare connection error,
and a file over the size limit is refused in the browser before anything is sent.

| What | Limit | Notes |
|---|---|---|
| File size | 10 MB | Checked from the declared size, before the file is read |
| Text | 1,500,000 characters | About 250,000 words, 350 dense or 500 ordinary pages. Applies to every format |
| PDF pages | 400 | Read from the file before any page is processed |
| Citations returned | 2,000 | The true total is still reported |
| Unsourced claims returned | 500 | The most likely ones; the true total is still reported |
| Time for one analysis | 90 seconds | Then a readable 504; one analysis runs at a time and two may wait |
| Time and memory to read one document | 35 seconds, 1 GB | The reader is stopped and the page is told the document is too complex to read within the server's limits (413) |
| Documents read at once | 2, with 3 waiting | Beyond that a 503 "busy" with `Retry-After`, never a file-type error |

Each can be changed per environment without a code change (`MAX_UPLOAD_MB`, `MAX_TEXT_CHARS`,
`MAX_PDF_PAGES`, `MAX_CITATIONS_RETURNED`, `MAX_CLAIMS_RETURNED`, `ANALYSIS_DEADLINE_SECONDS`,
`MAX_QUEUED_ANALYSES`, and the document-reading and request limits below; see
[`backend/app/limits.py`](backend/app/limits.py)), and `/health` publishes the values in force so
a client can show the number that is actually enforced.

**Reading documents in a child process.** Every upload (PDF, Word and text) is read by a
short-lived child process, not by the server itself. A PDF can make the native library behind
the reader abort or allocate gigabytes (an 862-byte file did), and a long unbroken run of
letters or digits can hold a regular expression for minutes; neither a thread, a deadline nor a
timeout inside the server can stop either, but a child can be killed. The child starts with a
reduced environment (no API keys), sets its own limits before it imports anything or sees the
file, and answers with one JSON object. The server waits for it without using a worker thread,
kills it (and its process group) at the wall-clock limit, caps what it may write back, and turns
how it ended into a message: too many pages or too much text is a 413 with the limit stated;
a document that needed more memory, processor time or wall-clock time than allowed is a 413
"too complex to read within this server's limits ... export it again or split it"; a damaged,
encrypted or unsupported file keeps its 415 or 400; and a full queue is a 503 with `Retry-After`.
Measured cost over reading in the server itself (medians, 4 CPUs): 46 ms for a short text or
Word document, 170 to 200 ms for a PDF (it imports pdfium, and the citation extractor when the PDF
has running headers), 56 ms for a 300-page Word document, and 0.29 s (at most 0.47 s) for the
273-page PDF, 3.65 s to 3.94 s. The server's own memory stays flat across uploads (62.6 MB before
50 mixed uploads to a live server, 60.7 MB after); the child peaks at 41 MB on the 273-page PDF.

| Variable | Default | Meaning |
|---|---|---|
| `PARSE_CHILD_MEM_MB` | `1024` | address-space ceiling for one child (RLIMIT_AS: virtual memory, not resident) |
| `PARSE_CHILD_CPU_S` | `40` | processor-time ceiling for one child (RLIMIT_CPU) |
| `PARSE_WALL_S` | `35` | wall-clock limit; the server kills the child at this point |
| `PARSE_MAX_CONCURRENT` | `2` | children running at once; with the memory ceiling this is the most the server can be asked to hold for uploads |
| `PARSE_MAX_QUEUE` | `3` | uploads allowed to wait for a child, then a 503 |
| `PARSE_QUEUE_WAIT_S` | `20` | longest an upload waits for a child; waiting does not count against the reading limits |
| `PARSE_RETRY_AFTER_S` | `5` | the `Retry-After` value on a 503 |
| `PDF_MAX_PAGE_CHARS` | `60000` | a PDF page with more characters is read without layout analysis |
| `PDF_SECOND_OPINION_MAX_CHARS` | `30000` | largest page the second PDF reader will be tried on |
| `PDF_SECOND_OPINION_BUDGET_S` | `10` | total time the second PDF reader may take |
| `DOCX_MAX_ELEMENTS` | `4000000` | XML elements in one Word part |
| `DOCX_MAX_DEPTH` | `200` | nesting depth of one Word part |

The memory ceiling is on each child's address space, and the host's own limit applies to the
server and its children together, so `PARSE_MAX_CONCURRENT` times `PARSE_CHILD_MEM_MB` should stay
well under it. The child is a guard against crashes and exhaustion, not a security boundary: it
runs as the same user, outside any container of its own.

**Reading PDFs.** PDFs are read with pypdfium2 one page at a time, so memory stays flat (about
25 MB) however long the file is, and 273 dense pages take about 4 seconds. This replaced
pdfplumber, which kept every page in memory (about 9 MB per page, 2.5 GB for 273 pages) and
crashed the server on a long document. The reader also rejoins superscript footnote markers,
drops pleading-paper line numbers, repairs ligatures and hyphenation, removes running headers,
footers and page numbers that repeat on most pages, and marks footnotes the same way the Word
reader does. On 17 PDFs **generated for testing** this raised citation recall from 97.3% to 99.96%
and footnote numbers from 92.6% to 98.7%. Those figures say how the reader does on documents built
to contain the citation forms it handles; see "How far to trust it" for what happened on a real
paper.

Inside the child the reader is bounded before the child's own limits have to stop it: a page's
character count is read before any layout is built (a page that cannot fit in the text limit is
refused at once, an enormous one is read as plain text and the person is told), the time limit is
checked inside the page as well as between pages, and the slow second reader (pdfminer) is tried
only on a page with real garble evidence (control characters, or "(cid:N)" codes making up 2% of
the page; the text "(cid:12)" in a sentence is not evidence), never while the first reader's lock
is held, and for at most `PDF_SECOND_OPINION_BUDGET_S` in all. The page count in a PDF is treated
as a claim and checked against the file: a count that is too large no longer refuses a small file
with "this PDF has 450 pages", a count that is too small no longer drops the rest of the document
without a word, and either mismatch is reported in the warnings. Running lines are removed only if
they really run: a URL is compared exactly (a different regulations.gov docket on every page is
five citations, not a footer), digits that differ between pages must count pages, and nothing the
citation extractor reads as a citation is removed. A line-end hyphen is decided with the whole
document as evidence, whether or not pdfium had already marked it: inside a web address it is
always kept, elsewhere it is kept when the document writes the compound with its hyphen on one
line (concealed-/carry) or shows no typesetter's hyphenation at all (a paper exported from Word),
dropped when the document has the word whole (regu-/lation), and never joined across a blank
line; the rule is written in `pdf_text.py` next to the code and pinned by tables of right and
wrong cases.

What it cannot do: a scanned PDF has no text to read (run OCR first), and a PDF whose fonts carry
no text map comes out as codes, which is reported rather than passed on as text. The test
fixtures are real PDFs written by Chromium, reportlab and LibreOffice; PDFs from other producers
(LaTeX, InDesign, Word's own export) are not covered.

**When something does fail.** The browser reports a crash, a dropped connection and an outage
identically. After a request that got no answer, the page asks `/health` which it was: a changed
`boot_id` means the server restarted while working on the document (usually out of memory), the
same one means the request itself did not finish, and no answer means it is down. Analysis has
its own two-minute timeout and uploads are allowed time in proportion to the file, so a slow
phone connection is not mistaken for a broken server. After a failed analysis, "Try again" re-runs
it without uploading the file again. Long results are shown a hundred at a time, and the
document preview shows one window of text, because thousands of cards made a phone unusable
(4,000 citations took 3.9 s to first paint on a throttled phone).

**Staying responsive.** The analysis is CPU work, so it runs in a worker thread, one document at
a time. Every error the server can produce, including an unexpected one, is a JSON response that
carries CORS headers (a browser hides a response without them and can only say "could not reach
the server"), and every response carries `X-Boot-Id`. Request bodies are counted as they arrive
and never trusted from their headers: a body sent in chunks with no declared length is cut off at
the limit with a 413 that states it (`/api/upload` allows the file limit, `/api/analyze` the text
limit, every other endpoint `MAX_SMALL_BODY_KB`). When a person closes the tab their place in
the analysis queue and their outside lookups are released at once; a job already running on the
processor finishes first, because a thread cannot be stopped. A text with more than `MAX_CITATIONS_ANALYZED` citations (a text of bare "Id.", for
example) is refused with the limit stated instead of being built in memory. Lookup results are
counted where the request is made, so the response says how many were found and how many failed
(`lookup.matched`, `lookup.failed`) and "the sources refused us" is no longer reported as
"nothing found".

The small endpoints (one citation, a case name, a search phrase) refuse any text field longer than
`MAX_FIELD_CHARS`: a 3 KB string of spaces once held the event loop for 45 seconds in a pattern
written inline in a handler. Two tests now guard every pattern in the code:
`tests/test_regex_floods.py` (about eighty floods of one repeated shape over every import-time
pattern and every stage) and `tests/test_regex_inline.py`, which reads the source of every module,
collects every `re.` call wherever it is written, and attacks each with text built from the
pattern's own structure, reporting any that is slow and growing faster than its input.

When a container runs out of memory the kernel ends one process without asking. The child that
reads an upload marks itself as the first to go, so a hostile file costs that one upload and not
the server (measured in a 512 MB container: the server was ended 4 times in 4 before, and not
once in about 350 hostile uploads after).

Two last-resort checks exist because a regular expression holds the interpreter lock for the
whole of one match, and nothing inside Python can interrupt it: not a deadline, not a timer, not
another thread. `EVENT_LOOP_STALL_EXIT_S` (45 s) ends the process if the event loop has not run
for that long, and `CPU_JOB_MAX_S` (180 s) ends it if an analysis thread outlives its request by
that long, since a thread cannot be killed and would hold the single analysis slot. Both print
every thread's stack first, which names the pattern, and the host restarts the process; the page
sees a new `boot_id` and says the server restarted. Set either to `0` to turn it off (a laptop
that sleeps for a minute would otherwise end a local server). They are a net under the fixes, not
a substitute: `tests/test_regex_floods.py` runs every regular expression in the app over about
fifty floods of one repeated shape in a killable subprocess and fails on any that takes over a
second on 30,000 characters. That is a sample of shapes, not a proof, and the net remains because
of it.

| Variable | Default | Meaning |
|---|---|---|
| `MAX_SMALL_BODY_KB` | `64` | request body for every endpoint except upload and analyze |
| `MAX_FIELD_CHARS` | `2000` | longest text field those endpoints accept (one citation, a case name, a search phrase); longer is a 413 that names the field |
| `MAX_CITATIONS_ANALYZED` | `50000` | citations one analysis will build; more is a 413 |
| `MAX_CLAIMS_FOR_SOURCES` | `25` | claims the legacy source-finding endpoints search outside sources for |
| `EVENT_LOOP_STALL_EXIT_S` | `45` | end the process if the event loop stalls this long (`0` = off) |
| `CPU_JOB_MAX_S` | `180` | end the process if one analysis thread runs this long (`0` = off) |

`python-multipart` is pinned to 0.0.34 on purpose: version 0.0.6 spends minutes parsing a hostile
`Content-Type` header on the event loop, and `tests/test_http_layer.py` fails against it.

## Two styles

A footnote in a law review and a citation in a court document use different typefaces.
The toggle above the input chooses between them.

| | Law review footnote | Court document |
|---|---|---|
| Report or book author and title | CAPITALS (the tool's stand-in for small caps) | ordinary type, italic title |
| Title capitalization | n/a, all capitals | Rule 8: `with` and `the` lower case |
| Newspaper name | CAPITALS | ordinary type |

## How far to trust it

The Bluebook is copyrighted, and this tool was built without being able to read it. Formats
and rule numbers come from library guides and cited examples, so:

- **Rule numbers are only shown if they were verified.** A sub-rule the sources disagreed
  about is shown as its nearest verified parent, so a claimed 10.3.2 appears as Rule 10.3.
  The list is in [`backend/app/utils/rules.py`](backend/app/utils/rules.py).
- **Every type carries a confidence level.** "Format well established" means the form is
  the same in every source consulted. Anything else says to check it against your Bluebook.
- **Rule numbers follow the 21st edition.** The 22nd edition is current; most numbers are
  unchanged but a few are known to differ, so the interface says to confirm in yours.
- **Nothing is reported as found unless it links to a real record.** For most kinds there
  is no free source to look a record up in, so the tool says what is missing instead.
- **The accuracy figures in this README come from test documents, not from real ones.** The
  first real paper it was checked against (58 pages, about 345 citations, written in Word) came
  out almost entirely wrong: case names swallowed the words around them, web addresses lost
  hyphens and gained the sentence's full stop, most state statutes were missed, and every
  citation was labelled as being in footnote 2. Those causes were fixed and the same paper was
  checked again (every case name read whole, all 171 web addresses intact, all eleven statutes of
  its first footnote found), but it has not been re-scored citation by citation, and one paper
  is not a benchmark. Treat every result as a draft to check against the source.
- Text typed entirely in capitals is brought back to ordinary case for court documents, with
  a short list of known agency acronyms kept. An acronym not on that list needs its capitals
  restored by hand.

## Adding a citation type

A type is data, not code. Add an entry to
[`backend/app/utils/citation_spec.py`](backend/app/utils/citation_spec.py): how to recognise it,
its fields and the rule claimed for each, and a template per style. Then:

```bash
cd backend && python scripts/generate_frontend_tables.py   # exports the spec to the browser
pytest                                                     # includes the shared golden corpus
```

`shared/spec_golden.json` is run against both the Python and the JavaScript engine, so
add a real citation and its expected output there. A test fails if a template uses an
optional field outside an optional block, if a worked example does not read back as its
own type, or if a field would end up with no verified rule to show.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Citation

If you use this software in your research, please cite it:

```bibtex
@software{schlangen_bluebook_cite,
  author = {Schlangen, Del},
  title = {Bluebook Citation Generator},
  url = {https://github.com/delschlangen/bluebook-cite},
  license = {MIT}
}
```

---

Made with care for the legal community.
