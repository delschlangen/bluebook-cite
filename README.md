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
  -d '{"text": "Moody v. NetChoice"}'
```

## Testing

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests && pytest
```

CI runs exactly this on every pull request, and the deploy workflow is gated
behind it. See [DEPLOYMENT.md](DEPLOYMENT.md) for how the two Docker build
contexts differ.

## Supported Citation Types

- **Cases** - Federal and state court decisions
- **Statutes** - U.S.C. and state code citations
- **Regulations** - C.F.R. citations
- **Law Review Articles** - Journal articles with volume/page citations
- **Books** - Treatises and legal texts with edition support
- **Websites** - Online sources with access dates

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
