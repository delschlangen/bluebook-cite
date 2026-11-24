#!/usr/bin/env python3
"""Generate the frontend's Bluebook tables from the Python source of truth.

The frontend formats complete citations locally so the tool works even when the
backend is unreachable. That means the abbreviation tables exist in two
languages, which is exactly the kind of duplication that drifts silently.

Generating one from the other removes the drift. `test_generated_tables.py`
fails if the checked-in file is stale, so CI catches it.

Usage:
    python scripts/generate_frontend_tables.py          # write the file
    python scripts/generate_frontend_tables.py --check  # verify it is current
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.bluebook_patterns import (  # noqa: E402
    COURT_ABBREVIATIONS,
    PARTY_ABBREVIATIONS,
    REPORTER_ABBREVIATIONS,
    STATE_ABBREVIATIONS,
)
from app.utils.text_normalize import NORMALIZATION  # noqa: E402
from app.utils.citation_spec import SPEC  # noqa: E402
from app.utils.field_guidance import (  # noqa: E402
    CITATION_TEMPLATES,
    FIELD_GUIDANCE,
)

OUTPUT = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend" / "src" / "utils" / "bluebookTables.js"
)
SPEC_OUTPUT = OUTPUT.with_name("citationSpec.json")

HEADER = """// GENERATED FILE - DO NOT EDIT BY HAND.
//
// Produced by backend/scripts/generate_frontend_tables.py from the Python
// tables in backend/app/utils/bluebook_patterns.py, which are the source of
// truth. Regenerate with:
//
//     cd backend && python scripts/generate_frontend_tables.py
//
// A backend test fails if this file is out of date.
"""


def render() -> str:
    parts = [HEADER]
    for name, table, ascii_only in (
        ("PARTY_ABBREVIATIONS", PARTY_ABBREVIATIONS, False),
        ("STATE_ABBREVIATIONS", STATE_ABBREVIATIONS, False),
        ("REPORTER_ABBREVIATIONS", REPORTER_ABBREVIATIONS, False),
        ("COURT_ABBREVIATIONS", COURT_ABBREVIATIONS, False),
        ("FIELD_GUIDANCE", FIELD_GUIDANCE, False),
        ("CITATION_TEMPLATES", CITATION_TEMPLATES, False),
        # Keys are invisible or look identical to ASCII (non-breaking space, curly
        # quotes), so they are written as \uXXXX escapes to stay readable and diffable.
        ("UNICODE_NORMALIZATION", NORMALIZATION, True),
    ):
        body = json.dumps(table, indent=2, ensure_ascii=ascii_only, sort_keys=True)
        parts.append(f"\nexport const {name} = {body};\n")
    return "".join(parts)


def render_spec() -> str:
    return json.dumps(SPEC, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    outputs = {OUTPUT: render(), SPEC_OUTPUT: render_spec()}

    if args.check:
        stale = [
            path.name for path, text in outputs.items()
            if not path.exists() or path.read_text() != text
        ]
        if stale:
            print(
                f"Out of date: {', '.join(stale)}.\n"
                "Run: cd backend && python scripts/generate_frontend_tables.py"
            )
            return 1
        print("Generated frontend files are current.")
        return 0

    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
