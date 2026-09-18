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

OUTPUT = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend" / "src" / "utils" / "bluebookTables.js"
)

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
    for name, table in (
        ("PARTY_ABBREVIATIONS", PARTY_ABBREVIATIONS),
        ("STATE_ABBREVIATIONS", STATE_ABBREVIATIONS),
        ("REPORTER_ABBREVIATIONS", REPORTER_ABBREVIATIONS),
        ("COURT_ABBREVIATIONS", COURT_ABBREVIATIONS),
    ):
        body = json.dumps(table, indent=2, ensure_ascii=False, sort_keys=True)
        parts.append(f"\nexport const {name} = {body};\n")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    generated = render()

    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT} is missing. Run this script without --check.")
            return 1
        if OUTPUT.read_text() != generated:
            print(
                f"{OUTPUT} is out of date.\n"
                "Run: cd backend && python scripts/generate_frontend_tables.py"
            )
            return 1
        print(f"{OUTPUT.name} is current.")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated)
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
