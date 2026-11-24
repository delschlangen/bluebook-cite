"""Run every compiled regular expression, and the stages built on them, against floods of one
repeated shape. Prints `<label> <seconds>` after each item and `START <label>` before it, so a
parent process that has to kill a hung run can say which item hung.

Run by tests/test_regex_floods.py in a subprocess with a hard timeout. It is a script and not a
test function because a regular expression holds the interpreter lock for the whole of one match:
a timer, a signal handler and an `assert elapsed < n` in the same process cannot interrupt it,
so the only way to turn a freeze into a failure is to be able to kill the process doing it.

The floods are the shapes that make unbounded repetitions retry from every starting point: one
character repeated, a short unit repeated, and the units the patterns themselves are made of. They
find the quadratic cases that were found by hand (a run of digits froze the server for over a
minute; a run of letters did the same inside the PDF reader). They are a net, not a proof: a
shape nobody thought of can still get through.
"""

import importlib
import pkgutil
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 30_000


def repeated(unit: str, n: int = SIZE) -> str:
    return (unit * (n // len(unit) + 1))[:n]


FLOODS = {
    "digits": "1" * SIZE,
    "digits-and-spaces": repeated("1 "),
    "digits-and-commas": repeated("1,000"),
    "digits-and-dots": repeated("1."),
    "digits-and-hyphens": repeated("1-"),
    "lowercase": "a" * SIZE,
    "uppercase": "A" * SIZE,
    "mixed-case": repeated("aA"),
    "letters-and-hyphens": repeated("ab-"),
    "letters-and-spaces": repeated("ab "),
    "capitalised-words": repeated("Alpha "),
    "initials": repeated("A. "),
    "dotted-initials": repeated("A.B."),
    "all-caps-words": repeated("ALPHA BETA "),
    "spaces": " " * SIZE,
    "newlines": "\n" * SIZE,
    "tabs-and-newlines": repeated("\t\n"),
    "dots": "." * SIZE,
    "spaced-dots": repeated(". "),
    "commas": "," * SIZE,
    "hyphens": "-" * SIZE,
    "underscores": "_" * SIZE,
    "slashes": "/" * SIZE,
    "open-brackets": "(" * SIZE,
    "close-brackets": ")" * SIZE,
    "square-brackets": "[" * SIZE,
    "quotes": '"' * SIZE,
    "apostrophes": "'" * SIZE,
    "stars": "*" * SIZE,
    "section-signs": repeated("§ "),
    "ampersands": repeated("A & B & "),
    "versus": repeated("A v. "),
    "case-names": repeated("Alpha Beta v. Gamma Delta, 1 U.S. "),
    "id": repeated("Id. "),
    "supra": repeated("supra note 1, at 1; "),
    "statute": repeated("42 U.S.C. § 1983 "),
    "reporter": repeated("1 F.2d 1 "),
    "court-year": repeated("(2d Cir. 1999) "),
    "law-review": repeated("A. B., 1 Harv. L. Rev. 1 "),
    "federal-register": repeated("86 Fed. Reg. 1 "),
    "url": repeated("https://a.b/c "),
    "long-url": "https://example.org/" + "a" * SIZE,
    "ellipsis": repeated(". . . "),
    "footnote-markers": repeated("[^1] "),
    "numbered-lines": repeated("1 Alpha\n"),
    "non-breaking-spaces": repeated(" "),
    "em-dashes": repeated("a—b "),
    "percent": repeated("5% "),
    "claims": repeated("The Court held that about 5 people "),
    "emoji": repeated("\U0001f600"),
    "cjk": repeated("法"),
}


# Patterns the app only ever applies with .match (anchored at the start of one line), never with
# search or finditer. They begin with a possessive run of whitespace, which is linear when
# anchored and quadratic when searched, so searching them would report a cost the app cannot
# incur. If the app starts searching with one of these, remove it from this set.
MATCH_ONLY = {"app.services.pdf_text._NEW_ITEM"}


def discover_patterns() -> dict[str, "re.Pattern"]:
    """Every compiled pattern reachable from the app: module level, class level, inside dicts,
    lists and tuples, and on the objects the app builds once at import (the citation engine's
    per-type patterns, the claim detector's)."""
    import app  # noqa: PLC0415

    found: dict[str, re.Pattern] = {}
    seen_ids: set[int] = set()

    def visit(label: str, value, depth: int = 0) -> None:
        if isinstance(value, re.Pattern):
            if id(value) not in seen_ids:
                seen_ids.add(id(value))
                found[label] = value
        elif depth < 3 and isinstance(value, dict):
            for k, v in value.items():
                visit(f"{label}[{k!r}]", v, depth + 1)
        elif depth < 3 and isinstance(value, list | tuple | set | frozenset):
            for i, v in enumerate(value):
                visit(f"{label}[{i}]", v, depth + 1)

    modules = [app]
    for info in pkgutil.walk_packages(app.__path__, "app."):
        try:
            modules.append(importlib.import_module(info.name))
        except Exception as exc:  # a module that cannot import here is reported, not hidden
            print(f"NOTE could not import {info.name}: {exc!r}", flush=True)

    for module in modules:
        for name, value in vars(module).items():
            if getattr(value, "__module__", module.__name__) != module.__name__ and not isinstance(
                value, dict | list | tuple | re.Pattern
            ):
                continue
            visit(f"{module.__name__}.{name}", value)
            if isinstance(value, type) and value.__module__ == module.__name__:
                for attr, attr_value in vars(value).items():
                    visit(f"{module.__name__}.{name}.{attr}", attr_value)

    # Objects built at import or construction time.
    from app.services import citation_engine  # noqa: PLC0415
    from app.services.source_finder import ClaimDetector  # noqa: PLC0415

    for type_id, citation_type in citation_engine.ENGINE.types.items():
        for i, pattern in enumerate(citation_type.patterns):
            visit(f"engine.{type_id}[{i}]", pattern)
    visit("ClaimDetector()", vars(ClaimDetector()))
    return found


def stages():
    """The functions a request can reach with text it controls."""
    from app.services.context_analyzer import DocumentContextAnalyzer  # noqa: PLC0415
    from app.services.extractor import CitationExtractor  # noqa: PLC0415
    from app.services.source_finder import ClaimDetector  # noqa: PLC0415

    extractor = CitationExtractor()
    analyzer = DocumentContextAnalyzer()
    detector = ClaimDetector()

    def sequence(text):
        return analyzer.analyze_citation_sequence(extractor.extract_all(text))

    yield "extract_all", extractor.extract_all
    yield "detect_unsourced_claims", lambda text: detector.detect_unsourced_claims(text, [])
    yield "analyze_document_structure", analyzer.analyze_document_structure
    yield "extract_then_sequence", sequence

    try:
        from app.services.repair import CitationRepairer  # noqa: PLC0415

        repairer = CitationRepairer()
        for method in ("diagnose", "repair"):
            if hasattr(repairer, method):
                yield f"CitationRepairer.{method}", getattr(repairer, method)
    except Exception as exc:
        print(f"NOTE no repairer stage: {exc!r}", flush=True)

    try:
        from app.services.pdf_text import repair_text  # noqa: PLC0415

        yield "pdf_text.repair_text", repair_text
    except Exception as exc:
        print(f"NOTE no repair_text stage: {exc!r}", flush=True)


def main() -> None:
    patterns = discover_patterns()
    print(f"PATTERNS {len(patterns)}", flush=True)
    print(f"FLOODS {len(FLOODS)}", flush=True)

    for flood_name, flood in FLOODS.items():
        for pattern_name, pattern in patterns.items():
            label = f"pattern {pattern_name} /{pattern.pattern[:60]!r}/ on {flood_name}"
            print(f"START {label}", flush=True)
            began = time.perf_counter()
            count = 0
            # A few patterns read raw file bytes (the PDF page-count check), not text.
            subject = flood.encode("utf-8") if isinstance(pattern.pattern, bytes) else flood
            if pattern_name in MATCH_ONLY:
                pattern.match(subject)
            else:
                for _ in pattern.finditer(subject):
                    count += 1
                    if count > 2_000_000:
                        break
            print(f"DONE {time.perf_counter() - began:.3f} {label}", flush=True)

    # The stages are slower per character (they do real work), so use fewer floods.
    stage_floods = [
        "digits", "lowercase", "uppercase", "mixed-case", "spaces", "dots", "hyphens",
        "digits-and-spaces", "digits-and-commas", "capitalised-words", "initials", "all-caps-words",
        "case-names", "statute", "law-review", "url", "long-url", "numbered-lines", "claims",
        "section-signs", "open-brackets", "quotes", "newlines", "footnote-markers",
    ]
    for stage_name, stage in stages():
        for flood_name in stage_floods:
            label = f"stage {stage_name} on {flood_name}"
            print(f"START {label}", flush=True)
            began = time.perf_counter()
            try:
                stage(FLOODS[flood_name])
            except Exception as exc:
                # An error is allowed here (callers turn it into a clean message); a hang is not.
                print(f"NOTE {label}: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
            print(f"DONE {time.perf_counter() - began:.3f} {label}", flush=True)

    print("FINISHED", flush=True)


if __name__ == "__main__":
    main()
