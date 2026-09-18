"""Guards against the browser and the server disagreeing.

The frontend formats complete citations locally so the tool works when the
backend is unreachable. That means two implementations of the same rules, which
is exactly the kind of duplication that drifts silently and produces two
different "correct" answers.

Two things keep them honest. The abbreviation tables are generated from the
Python source, so they cannot diverge at all. And the golden corpus is asserted
to be identical in both suites.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
GENERATOR = BACKEND / "scripts" / "generate_frontend_tables.py"
GENERATED = REPO / "frontend" / "src" / "utils" / "bluebookTables.js"
JS_TESTS = REPO / "frontend" / "src" / "utils" / "__tests__" / "localCitation.test.js"


def test_generated_tables_are_current():
    """Fails when bluebook_patterns.py changed but the JS tables were not
    regenerated. Fix: cd backend && python scripts/generate_frontend_tables.py
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=BACKEND,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_file_is_marked_as_generated():
    assert GENERATED.exists()
    head = GENERATED.read_text()[:200]
    assert "DO NOT EDIT" in head


def _python_golden() -> set[tuple[str, str]]:
    from tests.test_extraction import GOLDEN

    return set(GOLDEN)


def _js_golden() -> set[tuple[str, str]]:
    """Pull the GOLDEN array out of the JS test file."""
    source = JS_TESTS.read_text()
    block = re.search(r"const GOLDEN = \[(.*?)\n\];", source, re.S)
    assert block, "GOLDEN array not found in the JS test file"

    pairs = set()
    # Each entry is [ 'input', 'expected' ] across one or more lines.
    for entry in re.finditer(
        r"\[\s*(['\"])(.*?)\1\s*,\s*(['\"])(.*?)\3\s*,?\s*\]", block.group(1), re.S
    ):
        pairs.add((entry.group(2), entry.group(4)))
    return pairs


def test_both_suites_agree_on_the_shared_corpus():
    """Every citation tested in both places must expect the same output."""
    python_pairs = dict(_python_golden())
    js_pairs = dict(_js_golden())

    shared = set(python_pairs) & set(js_pairs)
    assert shared, "the two corpora share no inputs, so neither constrains the other"

    mismatched = {
        source: (python_pairs[source], js_pairs[source])
        for source in shared
        if python_pairs[source] != js_pairs[source]
    }
    assert not mismatched, (
        "the browser and the server format these differently: " f"{mismatched}"
    )


@pytest.mark.parametrize(
    "source",
    [
        "Brandenburg v. Ohio, 395 U.S. 444 (1969)",
        "NetChoice, LLC v. Paxton, 49 F.4th 439 (5th Cir. 2022)",
        "47 C.F.R. § 54",
    ],
)
def test_key_citations_are_covered_by_both(source):
    """The regressions that shipped must be pinned on both sides, not one."""
    assert source in dict(_python_golden())
    assert source in dict(_js_golden())
