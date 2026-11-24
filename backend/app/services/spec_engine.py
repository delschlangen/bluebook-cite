"""Data-driven citation engine.

A citation type is described by data: how to recognise it, which fields it has and
which Bluebook rule governs each, and a template that renders it. The engine is the
one piece of code that interprets that data. Adding a type means adding an entry to
the spec, not writing another regular expression and another formatter, and the
same spec drives the browser, so the two cannot disagree about what a type is.

Template syntax
---------------
    {name}              the field, or "[label]" when it is missing and gaps are shown
    {name|a|b}          the field passed through transforms a then b
    <<text {name}>>     optional block, emitted only if every field inside is present

Transforms are listed in TRANSFORMS and mirrored exactly in the browser engine.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

STYLES = ("law_review", "practitioner")

_PLACEHOLDER = re.compile(r"\{(\w+)((?:\|\w+)*)\}")
_OPTIONAL = re.compile(r"<<(.*?)>>", re.S)


# --- transforms --------------------------------------------------------------
#
# Each takes (value, style) and returns a string. Keep this list short and keep the
# browser's copy identical. The shared conformance corpus fails if they diverge.


def _t_upper(value: str, style: str) -> str:
    return value.upper()


def _t_smallcaps(value: str, style: str) -> str:
    # Plain text has no small capitals. Law review style sets authors and titles of
    # books in large and small caps, which this tool renders as capitals; a
    # practitioner document uses ordinary type.
    return value.upper() if style == "law_review" else value


def _t_italic(value: str, style: str) -> str:
    # Italics in both styles. Practitioners may underline instead; that is a
    # display choice, so the marker is the same.
    return f"*{value}*" if value else value


def _t_roman_upper(value: str, style: str) -> str:
    return value.upper()


TRANSFORMS: dict[str, Callable[[str, str], str]] = {
    "upper": _t_upper,
    "smallcaps": _t_smallcaps,
    "italic": _t_italic,
    "roman": _t_roman_upper,
}


def register_transform(name: str, fn: Callable[[str, str], str]) -> None:
    """Add a transform. Used by modules that own a rule (title capitalisation)."""
    TRANSFORMS[name] = fn


# --- matching ----------------------------------------------------------------


@dataclass
class Match:
    type_id: str
    start: int
    end: int
    fields: dict[str, str]
    pattern_index: int = 0
    coverage: float = 0.0
    priority: int = 0

    @property
    def length(self) -> int:
        return self.end - self.start


def choose_non_overlapping(candidates: list[Match]) -> list[Match]:
    """Keep the best candidate for each stretch of text, in document order.

    Longest first, then higher priority, then the earlier (more specific) pattern, then the
    earlier position. A candidate is dropped if it overlaps one already chosen. Chosen spans are
    disjoint, so they are kept sorted and a candidate only has to be compared with its one
    possible neighbour; testing it against every chosen span was quadratic in the number of
    citations.
    """
    ordered = sorted(candidates, key=lambda m: (-m.length, -m.priority, m.pattern_index, m.start))
    chosen: list[Match] = []
    starts: list[int] = []
    ends: list[int] = []
    for cand in ordered:
        i = bisect_left(starts, cand.end)
        if i > 0 and ends[i - 1] > cand.start:
            continue
        j = bisect_left(starts, cand.start)
        starts.insert(j, cand.start)
        ends.insert(j, cand.end)
        chosen.append(cand)
    chosen.sort(key=lambda m: m.start)
    return chosen


@dataclass
class CompiledType:
    spec: dict[str, Any]
    patterns: list[re.Pattern]
    # Parallel to `patterns`. A paste-only pattern is anchored to the start of the
    # input or is loose enough to be a false positive inside running prose, so it is
    # used for a single pasted citation and never when scanning a whole document.
    paste_only: list[bool] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.spec["id"]


class Engine:
    """Interprets a citation spec."""

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.types: dict[str, CompiledType] = {}
        for entry in spec["types"]:
            patterns = []
            paste_only = []
            for p in entry.get("patterns", []):
                f = re.IGNORECASE if "i" in p.get("flags", "") else 0
                patterns.append(re.compile(p["regex"], f))
                paste_only.append(bool(p.get("paste_only")))
            self.types[entry["id"]] = CompiledType(entry, patterns, paste_only)

    # -- lookup helpers

    def type_spec(self, type_id: str) -> dict[str, Any]:
        return self.types[type_id].spec

    def field_specs(self, type_id: str) -> list[dict[str, Any]]:
        return self.type_spec(type_id)["fields"]

    def required_fields(self, type_id: str) -> list[str]:
        return [f["name"] for f in self.field_specs(type_id) if f.get("required")]

    # -- matching

    def _scan(self, compiled: CompiledType, text: str, document: bool = False):
        # Italics are written with asterisks, in this tool's own output and in many
        # pasted drafts. They are not part of a title, and left in they get read back
        # into it and doubled: correcting a corrected citation would corrupt it. One
        # space for one asterisk keeps every offset valid.
        text = text.replace("*", " ")
        for index, pattern in enumerate(compiled.patterns):
            if document and compiled.paste_only[index]:
                continue
            for m in pattern.finditer(text):
                fields = {
                    name: _clean(value)
                    for name, value in m.groupdict().items()
                    if value is not None and _clean(value)
                }
                yield Match(
                    type_id=compiled.id,
                    start=m.start(),
                    end=m.end(),
                    fields=fields,
                    pattern_index=index,
                    priority=compiled.spec.get("priority", 0),
                )

    def find_all(self, text: str) -> list[Match]:
        """Every non-overlapping citation in a document, best match winning each span."""
        candidates: list[Match] = []
        for compiled in self.types.values():
            candidates.extend(self._scan(compiled, text, document=True))

        return choose_non_overlapping(candidates)

    def best_match(self, text: str) -> Match | None:
        """The single best reading of one pasted citation.

        A match is judged by how much of the input it accounts for. A pattern that
        recognises two words inside a long string is a coincidence, not an answer.
        """
        stripped = text.strip()
        if not stripped:
            return None
        best: Match | None = None
        for compiled in self.types.values():
            for cand in self._scan(compiled, stripped):
                cand.coverage = cand.length / max(len(stripped), 1)
                if best is None or _rank(cand) > _rank(best):
                    best = cand
        if best is None or best.coverage < MIN_COVERAGE:
            return None
        return best

    # -- rules and examples

    def display_rule(self, number: str | None) -> dict[str, str] | None:
        """The nearest VERIFIED rule at or above `number`, using the spec's own table.

        "10.3.2" is shown as "10.3" unless 10.3.2 itself is in the table. Nothing is
        returned when no ancestor is verified, so an unverified number is never shown.
        """
        rules = self.spec.get("rules") or {}
        if not number:
            return None
        base = number.split("(")[0].strip()
        parts = base.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in rules:
                return {"number": candidate, "title": rules[candidate]}
        return None

    def render_example(self, type_id: str, style: str = "law_review") -> str | None:
        """The type's worked example, rendered through its own template."""
        example = self.type_spec(type_id).get("example")
        if not example:
            return None
        return self.render(type_id, {k: v for k, v in example.items() if v}, style)

    # -- completeness and rendering

    def missing(self, type_id: str, fields: dict[str, str]) -> list[str]:
        return [n for n in self.required_fields(type_id) if not fields.get(n)]

    def render(
        self,
        type_id: str,
        fields: dict[str, str],
        style: str = "law_review",
        gaps: bool = False,
    ) -> str | None:
        """Render a citation.

        With gaps=False the result is only produced when nothing required is
        missing, so a formatted citation is never returned with a hole in it. With
        gaps=True, each missing required field appears as [label].
        """
        spec = self.type_spec(type_id)
        template = spec["templates"].get(style) or spec["templates"]["law_review"]
        labels = {f["name"]: f["label"] for f in spec["fields"]}
        required = set(self.required_fields(type_id))

        if not gaps and any(not fields.get(n) for n in required):
            return None

        def fill(segment: str, in_optional: bool) -> str | None:
            """Fill one segment; None means an optional block lost a field."""
            def sub(m: re.Match) -> str:
                name, chain = m.group(1), m.group(2)
                value = fields.get(name, "")
                if not value:
                    if in_optional:
                        raise _Drop
                    return f"[{labels.get(name, name)}]" if name in required or gaps else ""
                for t in [t for t in chain.split("|") if t]:
                    value = TRANSFORMS[t](value, style)
                return value

            try:
                return _PLACEHOLDER.sub(sub, segment)
            except _Drop:
                return None

        def optional(m: re.Match) -> str:
            return fill(m.group(1), True) or ""

        body = _OPTIONAL.sub(optional, template)
        out = fill(body, False)
        return _tidy(out or "")


class _Drop(Exception):
    pass


MIN_COVERAGE = 0.55


def _rank(m: Match) -> tuple:
    # Match length, not the coverage ratio: every candidate is measured against the
    # same input, so length orders them identically, and an integer cannot round
    # differently in the browser (Python rounds half to even, JavaScript half up).
    return (m.length, len(m.fields), m.priority, -m.pattern_index)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\n,;")


def _tidy(text: str) -> str:
    """Remove the seams left where optional blocks were dropped."""
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r",\s*,", ",", text)
    return text.strip()


@dataclass
class Diagnosis:
    """What the engine concluded about one pasted citation."""

    type_id: str
    label: str
    fields: dict[str, str]
    missing: list[str]
    formatted: str | None
    template: str
    details: list[dict[str, Any]] = field(default_factory=list)
    citation_type: str = "other"
    confidence: str = "medium"
    notes: list[str] = field(default_factory=list)
    family: str = ""


def diagnose(engine: Engine, text: str, style: str = "law_review") -> Diagnosis | None:
    match = engine.best_match(text)
    if match is None:
        return None
    spec = engine.type_spec(match.type_id)
    missing = engine.missing(match.type_id, match.fields)
    by_name = {f["name"]: f for f in spec["fields"]}
    return Diagnosis(
        type_id=match.type_id,
        label=spec["label"],
        fields=match.fields,
        missing=missing,
        formatted=engine.render(match.type_id, match.fields, style),
        template=engine.render(match.type_id, match.fields, style, gaps=True) or "",
        details=[
            {
                "field": n,
                "label": by_name[n]["label"],
                "rule": by_name[n].get("rule", ""),
                "display_rule": engine.display_rule(by_name[n].get("rule")),
                "why": by_name[n].get("why", ""),
            }
            for n in missing
        ],
        citation_type=spec.get("citation_type", "other"),
        confidence=spec.get("confidence", "medium"),
        notes=list(spec.get("notes", [])),
        family=spec.get("family", ""),
    )
