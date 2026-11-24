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
