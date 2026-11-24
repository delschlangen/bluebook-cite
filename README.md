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
`MAX_QUEUED_ANALYSES`, and the document-reading limits below; see
[`backend/app/limits.py`](backend/app/limits.py)), and `/health` publishes the values in force so
a client can show the number that is actually enforced.

**Reading documents in a child process.** Every upload (PDF, Word and text) is read by a
short-lived child process, never by the server itself. A PDF can make the native library behind
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
Measured cost: about 50 ms for a short document and 0.3 to 0.5 s more than reading in the server
for a 273-page PDF. The server's own memory stays flat across uploads.

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
reader does. On 17 realistic PDFs this raised citation recall from 97.3% to 99.96% and footnote
numbers from 92.6% to 98.7%.

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
a time, and every error the server can produce, including an unexpected one, is a JSON response
that carries CORS headers (a browser hides a response without them and can only say "could not
reach the server"). `/health` includes a `boot_id` that changes when the process restarts, so a
client can tell a crash from a dropped connection.

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
