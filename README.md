# Bluebook Citation Generator

Automated legal citation formatting, completion, and verification using Bluebook 21st Edition rules.

**[Try it live](https://delschlangen.github.io/bluebook-cite/)**

## Features

- **Citation Extraction**: Automatically detects cases, statutes, regulations, articles, and books
- **Citation Completion**: Looks up incomplete citations using free legal databases (CourtListener, CrossRef, Open Library)
- **Bluebook Formatting**: Formats citations per Bluebook 21st Edition rules
- **Context-Aware Short Forms**: Suggests Id., supra, and short case forms based on document context
- **Unsourced Claim Detection**: Identifies statements that may need citations

## Tech Stack

- **Backend**: Python/FastAPI
- **Frontend**: React + Vite + TailwindCSS
- **APIs**: CourtListener, CrossRef, Open Library, eCFR (all free, no keys required)

## Local Development

### Backend
