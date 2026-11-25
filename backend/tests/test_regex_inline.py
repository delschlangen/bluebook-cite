"""Every regular expression in the app, wherever it is written, survives an attack built from
its own structure. See tests/regex_inline_scan.py for what is attacked and why.

Six freezes reached production-bound code after tests/test_regex_floods.py was in place, because
they were written inline in a function body (nothing at import time holds them) or needed a
particular beginning before the repeated part. One of them let a 3 KB request hold the event loop
for 45 seconds, after which the watchdog ended the process.
"""

import selectors
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services.lookup_service import (
    _CFR_IN_TEXT,
    _USC_IN_TEXT,
    _VERSUS,
    parse_volume_reporter_page,
)
from app.services.source_finder import ClaimDetector

BACKEND = Path(__file__).resolve().parent.parent
SCANNER = Path(__file__).resolve().parent / "regex_inline_scan.py"

# No output for this long means one pattern never returned (an exponential one, for example).
STALL_SECONDS = 60.0
WHOLE_RUN_SECONDS = 900.0


def _scan():
    """Run the scanner; returns (slow lines, unresolved lines, what hung or None, finished)."""
    proc = subprocess.Popen(
        [sys.executable, str(SCANNER)],
        cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    slow, unresolved, other = [], [], []
    current, finished = None, False
    started = last_output = time.monotonic()
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while True:
            if time.monotonic() - started > WHOLE_RUN_SECONDS:
                return slow, unresolved, f"the whole scan took over {WHOLE_RUN_SECONDS:.0f} s (last: {current})", False, other
            if not selector.select(timeout=1.0):
                if time.monotonic() - last_output > STALL_SECONDS:
                    return slow, unresolved, current or "(before the first pattern)", False, other
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            last_output = time.monotonic()
            if line.startswith("START "):
                current = line[6:].strip()
            elif line.startswith("DONE "):
                current = None
            elif line.startswith("SLOW "):
                slow.append(line.strip())
            elif line.startswith("UNRESOLVED "):
                unresolved.append(line.strip())
            elif line.startswith("FINISHED"):
                finished = True
            elif line.startswith(("NOTE", "Traceback")) or "Error" in line:
                other.append(line.strip())
        return slow, unresolved, None, finished, other
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_no_pattern_in_the_app_is_superlinear_under_an_attack_built_from_it():
    slow, unresolved, hung, finished, other = _scan()

    assert hung is None, f"one pattern never returned: {hung}"
    assert finished, "the scanner did not finish:\n" + "\n".join(other[-20:])
    assert not unresolved, (
        "these patterns are built at run time, so nothing can attack them. Write the pattern as a "
        "constant (module level is best), or list the function in UNRESOLVED_ALLOWED with the "
        "reason it is safe:\n" + "\n".join(unresolved)
    )
    patterns = sorted({line.split(": ", 1)[1].split(" attack ")[0] for line in slow})
    assert not slow, (
        f"{len(patterns)} pattern(s) take more than linear time on text built from them "
        "(bound every repetition, and do not let two neighbouring parts match the same "
        "character):\n" + "\n".join(patterns) + "\n\nfirst attacks:\n" + "\n".join(slow[:12])
    )


class TestTheScannerSeesWhatItShould:
    """The scanner is only worth something if it would have caught the freezes that got through."""

    @pytest.fixture(scope="class")
    def scan(self):
        sys.path.insert(0, str(SCANNER.parent))
        import regex_inline_scan as scanner

        return scanner

    @pytest.mark.parametrize(
        ("pattern", "anchored"),
        [
            (r"(\d+)\s+([A-Za-z.\s]+)\s+(\d+)", True),            # main.py lookup_case, cubic
            (r"(\d+)\s*U\.?S\.?C\.?\s*§?\s*(\d+[a-z]?)", False),   # lookup_service, quadratic
            (r"([A-Z][a-zA-Z]+)\s+v\.\s+([A-Z][a-zA-Z]+)", False),  # source_finder, needs capitals
            (r"\B(?=(\d{3})+(?!\d))", False),                       # transforms.thousands
            (r"\s+v\.?\s+", False),                                 # re.split, mild quadratic
            (r"(a+)+$", True),                                      # exponential
        ],
    )
    def test_each_freeze_that_got_through_is_caught(self, scan, pattern, anchored):
        import re

        compiled = re.compile(pattern)
        previous = {}
        for tier in scan.TIERS:
            for key, text in scan.attacks(pattern, 0, tier):
                seconds = scan._run(compiled, text, anchored)
                if scan._is_superlinear(tier, seconds, previous.get(key)):
                    return
                previous[key] = (tier, seconds)
        pytest.fail(f"the scanner found nothing superlinear in {pattern!r}")

    @pytest.mark.parametrize(
        "pattern",
        [
            r"(?<![0-9])(\d{1,3})\s{0,3}U\.?\s?S\.?\s?C\.?\s{0,3}§{0,2}\s{0,3}(\d{1,6}[a-z]{0,2})",
            r"(?<![A-Za-z])([A-Z][a-zA-Z]{0,60})\s{1,5}v\.\s{1,5}([A-Z][a-zA-Z]{0,60})",
            r"[a-z0-9]+",
        ],
    )
    def test_a_bounded_pattern_is_not_reported(self, scan, pattern):
        import re

        compiled = re.compile(pattern)
        previous = {}
        for tier in scan.TIERS:
            for key, text in scan.attacks(pattern, 0, tier):
                seconds = scan._run(compiled, text, False)
                assert not scan._is_superlinear(tier, seconds, previous.get(key)), (tier, key, seconds)
                previous[key] = (tier, seconds)

    def test_slow_but_linear_is_not_reported_and_quadratic_is(self, scan):
        # four times the text, four times the time: linear, however slow
        assert not scan._is_superlinear(25600, 0.08, (6400, 0.02))
        # four times the text, sixteen times the time: quadratic
        assert scan._is_superlinear(25600, 0.32, (6400, 0.02))
        # over a second is reported whatever came before
        assert scan._is_superlinear(25600, 1.2, (6400, 0.3))
        # fast is never reported
        assert not scan._is_superlinear(25600, 0.01, (6400, 0.0001))

    def test_an_inline_pattern_built_from_arguments_is_reported_not_skipped(self, scan, tmp_path, monkeypatch):
        """A pattern nobody can work out from the source must be named, never passed over."""
        import ast

        source = "import re\ndef f(word, text):\n    return re.search(word + r'\\s+x', text)\n"
        tree = ast.parse(source)
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        with pytest.raises(NameError):
            scan._pattern_values(call.args[0], function, {})

    def test_a_local_constant_and_a_loop_over_constants_are_resolved(self, scan):
        import ast

        source = (
            "import re\n"
            "def f(text):\n"
            "    one = r'a+b'\n"
            "    many = [r'c+d', r'e+f']\n"
            "    re.search(one, text)\n"
            "    for p in many:\n"
            "        re.findall(p, text)\n"
        )
        tree = ast.parse(source)
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        values = [scan._pattern_values(c.args[0], function, {}) for c in calls]
        assert sorted(sum(values, [])) == ["a+b", "c+d", "e+f"]


class TestTheReplacementPatternsStillRead:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("410 U.S. 113", ("410", "U.S.", "113")),
            ("123 F.3d 456", ("123", "F.3d", "456")),
            ("5 Cal. App. 4th 100", ("5", "Cal. App. 4th", "100")),
            ("12 F. Supp. 2d 99", ("12", "F. Supp. 2d", "99")),
            ("1  U.S.   2", ("1", "U.S.", "2")),
            ("2020 WL 1234567", ("2020", "WL", "1234567")),
            ("598 U.S. 1, 5 (2023)", ("598", "U.S.", "1")),
            ("113", None),
            ("U.S. 113", None),
            ("1 2 3", None),          # a reporter word must contain a letter
            ("", None),
            (None, None),
        ],
    )
    def test_volume_reporter_page(self, text, expected):
        assert parse_volume_reporter_page(text) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("42 U.S.C. § 1983", ("42", "1983")),
            ("42 USC 1983", ("42", "1983")),
            ("see 42 U.S.C.\n§ 1396a(a)", ("42", "1396a")),
            ("42 U.S.C.A. § 300gg-11", ("42", "300gg-11")),
            ("title 42 of the code", None),
        ],
    )
    def test_usc(self, text, expected):
        match = _USC_IN_TEXT.search(text)
        assert (match.groups() if match else None) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("47 C.F.R. § 54.101", ("47", "54.101")),
            ("47 CFR 54.101", ("47", "54.101")),
            ("47 C.F.R. pt. 54", ("47", "54")),
            ("the CFR says", None),
        ],
    )
    def test_cfr(self, text, expected):
        match = _CFR_IN_TEXT.search(text)
        assert (match.groups() if match else None) == expected

    def test_versus_splits_two_parties(self):
        assert _VERSUS.split("Brown v. Board of Education", maxsplit=1) == ["Brown", "Board of Education"]
        assert _VERSUS.split("Brown v Board", maxsplit=1) == ["Brown", "Board"]
        assert _VERSUS.split("Brown  v.\nBoard", maxsplit=1) == ["Brown", "Board"]

    def test_case_names_in_a_sentence_are_still_found(self):
        terms = ClaimDetector()._extract_legal_terms(
            "In Smith v. Jones the Court held that due process applies; see Roe v. Wade."
        )
        assert terms[:2] == ["Smith v. Jones", "Roe v. Wade"]
