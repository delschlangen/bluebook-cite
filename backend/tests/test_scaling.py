"""Speed and correctness as documents get long or odd.

Three things were wrong, each found by measuring rather than reading:

* Several algorithms were quadratic in the number of citations or characters (claim detection,
  footnote assignment, overlap tests), so 3,000 pages took 71 s.
* Unbounded regex quantifiers made a failed match retry from every possible starting point, so
  well under 100 KB of odd but plausible text (capitals with no punctuation, one very long token)
  froze the whole server for tens of seconds.
* The same unbounded quantifiers let a book or article "author" swallow whole paragraphs of
  prose: citations of 686 characters, with the author field holding the sentences before it.

The faster versions are tested against deliberately naive references on random inputs, so that
being faster cannot quietly mean being different.
"""

import json
import random
import re
import time
from pathlib import Path

import pytest

from app.services.extractor import CitationExtractor, SpanIndex
from app.services.source_finder import ClaimDetector
from app.services.spec_engine import Match, choose_non_overlapping
from app.utils.bluebook_patterns import PATTERNS

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "spec_golden.json").read_text()
)
GOLDEN_INPUTS = [c["input"] for c in GOLDEN["cases"]]


# --- span index vs brute force ---------------------------------------------------------------


def _brute_overlaps(spans, start, end):
    return any(not (end <= s or start >= e) for s, e in spans)


class TestSpanIndex:
    @pytest.mark.parametrize("seed", range(12))
    def test_it_agrees_with_checking_every_span(self, seed):
        rng = random.Random(seed)
        index, accepted = SpanIndex(), []
        for _ in range(400):
            start = rng.randint(0, 2000)
            end = start + rng.randint(1, 60)
            expected = _brute_overlaps(accepted, start, end)
            assert index.overlaps(start, end) == expected, (start, end, accepted)
            if not expected:  # the extractor only ever appends a span that did not overlap
                index.append((start, end))
                accepted.append((start, end))
        assert len(index) == len(accepted)

    def test_touching_spans_do_not_overlap(self):
        index = SpanIndex()
        index.append((10, 20))
        assert not index.overlaps(20, 30)
        assert not index.overlaps(0, 10)
        assert index.overlaps(19, 21)
        assert index.overlaps(0, 11)
        assert index.overlaps(12, 14)

    def test_an_empty_index_overlaps_nothing(self):
        assert not SpanIndex().overlaps(0, 100)


# --- claim detection: "is there a citation near this sentence" ---------------------------------


def _original_near(start, end, starts):
    """The original definition, verbatim in meaning."""
    for cite_start in starts:
        if start <= cite_start <= end:
            return True
        if 0 <= cite_start - end <= 30:
            return True
    return False


class TestNearACitation:
    @pytest.mark.parametrize("seed", range(10))
    def test_it_agrees_with_the_original_definition(self, seed):
        rng = random.Random(seed)
        for _ in range(300):
            starts = sorted(rng.randint(0, 1000) for _ in range(rng.randint(0, 25)))
            start = rng.randint(0, 1000)
            end = start + rng.randint(0, 120)
            assert ClaimDetector._near_a_citation(starts, start, end) == _original_near(
                start, end, starts
            ), (starts, start, end)

    def test_a_citation_just_after_the_sentence_counts_but_31_characters_after_does_not(self):
        assert ClaimDetector._near_a_citation([130], 0, 100) is True
        assert ClaimDetector._near_a_citation([131], 0, 100) is False

    def test_a_citation_before_the_sentence_does_not_count(self):
        assert ClaimDetector._near_a_citation([5], 10, 50) is False

    def test_no_citations_means_no_citation_nearby(self):
        assert ClaimDetector._near_a_citation([], 0, 10) is False


# --- the engine's choice among overlapping candidates -----------------------------------------


class TestEngineSelectionMatchesTheNaiveGreedyChoice:
    def _reference(self, engine, text):
        candidates = []
        for compiled in engine.types.values():
            candidates.extend(engine._scan(compiled, text, document=True))
        candidates.sort(key=lambda m: (-m.length, -m.priority, m.pattern_index, m.start))
        chosen = []
        for cand in candidates:
            if any(not (cand.end <= c.start or cand.start >= c.end) for c in chosen):
                continue
            chosen.append(cand)
        chosen.sort(key=lambda m: m.start)
        return [(m.start, m.end, m.type_id) for m in chosen]

    @pytest.mark.parametrize("seed", range(8))
    def test_on_random_documents_built_from_known_citations(self, seed):
        from app.services.citation_engine import ENGINE

        rng = random.Random(seed)
        for _ in range(25):
            text = " ".join(
                rng.choice(GOLDEN_INPUTS + ["Filler text between citations.", "See", "Id."])
                + rng.choice([".", ";", ",", ""])
                for _ in range(rng.randint(3, 25))
            )
            got = [(m.start, m.end, m.type_id) for m in ENGINE.find_all(text)]
            assert got == self._reference(ENGINE, text), text[:200]

    def test_the_chosen_matches_never_overlap(self):
        from app.services.citation_engine import ENGINE

        text = " ".join(GOLDEN_INPUTS)
        spans = [(m.start, m.end) for m in ENGINE.find_all(text)]
        assert spans == sorted(spans)
        assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:], strict=False))


class TestChoosingAmongOverlappingCandidates:
    """The selection step on its own, against a naive reference, on random overlapping
    intervals. Random documents almost never produce candidates that overlap by a single
    character, so this is where an off-by-one would otherwise hide."""

    @staticmethod
    def _naive(candidates):
        ordered = sorted(candidates, key=lambda m: (-m.length, -m.priority, m.pattern_index, m.start))
        chosen = []
        for cand in ordered:
            if any(not (cand.end <= c.start or cand.start >= c.end) for c in chosen):
                continue
            chosen.append(cand)
        return sorted(chosen, key=lambda m: m.start)

    @staticmethod
    def _random_candidates(rng, n):
        out = []
        for _ in range(n):
            start = rng.randint(0, 200)
            out.append(
                Match(
                    type_id=rng.choice("abcde"),
                    start=start,
                    end=start + rng.randint(1, 25),
                    fields={},
                    pattern_index=rng.randint(0, 3),
                    priority=rng.choice([0, 0, 0, 5]),
                )
            )
        return out

    @pytest.mark.parametrize("seed", range(25))
    def test_it_matches_the_naive_greedy_choice(self, seed):
        rng = random.Random(seed)
        candidates = self._random_candidates(rng, rng.randint(1, 80))
        got = choose_non_overlapping(candidates)
        want = self._naive(candidates)
        assert [(m.start, m.end, m.type_id) for m in got] == [(m.start, m.end, m.type_id) for m in want]

    def test_spans_that_touch_are_both_kept_and_spans_that_overlap_by_one_are_not(self):
        touching = [Match("a", 0, 10, {}), Match("b", 10, 20, {})]
        assert [m.type_id for m in choose_non_overlapping(touching)] == ["a", "b"]
        overlapping = [Match("a", 0, 11, {}), Match("b", 10, 20, {})]
        assert [m.type_id for m in choose_non_overlapping(overlapping)] == ["a"]

    def test_the_longer_candidate_wins_then_priority_then_the_earlier_pattern(self):
        short, long = Match("short", 0, 5, {}), Match("long", 2, 12, {})
        assert [m.type_id for m in choose_non_overlapping([short, long])] == ["long"]
        low, high = Match("low", 0, 10, {}), Match("high", 5, 15, {}, priority=5)
        assert [m.type_id for m in choose_non_overlapping([low, high])] == ["high"]
        late, early = Match("late", 0, 10, {}, pattern_index=2), Match("early", 5, 15, {}, pattern_index=1)
        assert [m.type_id for m in choose_non_overlapping([late, early])] == ["early"]

    def test_nothing_in_nothing_out(self):
        assert choose_non_overlapping([]) == []


# --- footnote assignment ----------------------------------------------------------------------


class TestFootnoteAssignmentMatchesTheNaiveScan:
    def _expected(self, text, citations):
        markers = sorted(
            (m.start(), int(m.group(2)))
            for m in PATTERNS["footnote_marker_explicit"].finditer(text)
            if not m.group(1)
        )
        out = []
        for c in citations:
            current = 0
            for pos, n in markers:
                if pos <= c.position_start:
                    current = n
                else:
                    break
            out.append(current or None)
        return out

    @pytest.mark.parametrize("seed", range(6))
    def test_explicit_markers(self, seed):
        rng = random.Random(seed)
        lines = []
        for n in range(1, 60):
            cites = " ".join(
                rng.choice(GOLDEN_INPUTS[:30]) + "." for _ in range(rng.randint(0, 3))
            )
            lines.append(f"[^{n}] {cites}")
            if rng.random() < 0.3:
                lines.append("Some body text between the notes.")
        text = "\n".join(lines)
        citations = CitationExtractor().extract_all(text)
        assert len(citations) > 10
        assert [c.footnote_number for c in citations] == self._expected(text, citations)

    def test_a_citation_before_any_marker_has_no_footnote_number(self):
        citations = CitationExtractor().extract_all(
            "Brown v. Board of Education, 347 U.S. 483 (1954).\n[^1] 42 U.S.C. § 1983."
        )
        assert citations[0].footnote_number is None
        assert citations[1].footnote_number == 1


# --- hostile and unlucky input ----------------------------------------------------------------

KB = 100_000
PATHOLOGICAL = {
    "capitals with spaces": ("ALPHA BRAVO CHARLIE " * 6000)[:KB],
    "one long token of capitals": "A" * KB,
    "one long token of lower case": "a" * KB,
    "See repeated": ("See " * 30000)[:KB],
    "U.S.C. repeated": ("U.S.C. " * 20000)[:KB],
    "title case, no punctuation": ("The Quick Brown Fox Jumps Over " * 4000)[:KB],
    "v. repeated": ("A v. " * 30000)[:KB],
    "sentences with no commas": ("The court held the rule was invalid today. " * 4000)[:KB],
    "Id. repeated": ("Id. " * 30000)[:KB],
    "open parenthesis after a case": ("Smith v. Jones, 1 U.S. 1 (" * 4000)[:KB],
}


class TestHostileInputStaysFast:
    """Before the quantifiers were bounded, each of these took 14 to 30+ seconds (four never
    finished), and the server handles one request at a time. The ceiling is several times the
    slowest current result (about 2 s) so a slow machine does not fail it, and far below what
    the unbounded patterns took."""

    @pytest.mark.parametrize("label", PATHOLOGICAL)
    def test_extraction_and_claims_finish_quickly(self, label):
        text = PATHOLOGICAL[label]
        started = time.perf_counter()
        citations = CitationExtractor().extract_all(text)
        ClaimDetector().detect_unsourced_claims(
            text, [(c.position_start, c.position_end) for c in citations]
        )
        elapsed = time.perf_counter() - started
        assert elapsed < 8, f"{label}: {elapsed:.1f}s for {len(text):,} characters"


# --- bounded patterns do not swallow prose ----------------------------------------------------


class TestAuthorsDoNotSwallowProse:
    PROSE = (
        "The district court was not persuaded by what relief is appropriate. "
        "The Fifth Circuit maintained throughout the litigation which standard of review "
        "governs the challenge. The majority declined to decide the relationship between "
        "text and legislative purpose. Reviewing courts offered a specific account of the "
        "burden of proof on remand. "
    )

    def test_a_book_after_a_long_paragraph_is_not_captured_with_the_paragraph(self):
        text = self.PROSE * 3 + "As the Court explained in H.L.A. Hart, The Concept of Law 94 (3d ed. 2012)."
        books = [c for c in CitationExtractor().extract_all(text) if c.type.value == "book"]
        assert len(books) == 1
        assert len(books[0].raw_text) < 200, books[0].raw_text[:300]
        assert "The Concept of Law" in books[0].raw_text

    def test_a_law_review_article_after_a_long_paragraph_is_not_captured_with_it(self):
        text = (
            self.PROSE * 3
            + "The Court so held in Richard A. Posner, The Economic Structure of Tort Law, "
            "87 Harv. L. Rev. 1052, 1060 (1974)."
        )
        articles = [c for c in CitationExtractor().extract_all(text) if c.type.value == "law_review"]
        assert len(articles) == 1
        assert len(articles[0].raw_text) < 250, articles[0].raw_text[:300]

    def test_a_long_but_real_book_title_is_still_recognised_whole(self):
        title = (
            "The Federal Courts and the Federal System: A Comprehensive Examination of "
            "Jurisdiction, Procedure, Federalism and the Allocation of Judicial Power Among Courts"
        )
        assert 120 < len(title) < 250
        text = f"See Richard H. Fallon Jr., {title} 45 (7th ed. 2015)."
        books = [c for c in CitationExtractor().extract_all(text) if c.type.value == "book"]
        assert books and title in books[0].raw_text

    def test_a_long_but_real_article_title_is_still_recognised_whole(self):
        title = (
            "Constitutional Avoidance and the Problem of Judicial Restraint in the Administrative "
            "State: A Reexamination of the Canon in Light of Recent Doctrinal Developments"
        )
        assert 120 < len(title) < 250
        text = f"Jane Q. Author, {title}, 99 Harv. L. Rev. 100, 105 (1985)."
        articles = [c for c in CitationExtractor().extract_all(text) if c.type.value == "law_review"]
        assert articles and title in articles[0].raw_text

    def test_ordinary_citations_are_unchanged_by_the_bounds(self):
        text = (
            "Brown v. Board of Education, 347 U.S. 483, 495 (1954). "
            "Cass R. Sunstein, Interpreting Statutes in the Regulatory State, "
            "103 Harv. L. Rev. 405, 410 (1989). "
            "Richard A. Posner, How Judges Think 45 (2008)."
        )
        found = {c.type.value: c.raw_text for c in CitationExtractor().extract_all(text)}
        assert found["case"] == "Brown v. Board of Education, 347 U.S. 483, 495 (1954)"
        assert found["law_review"].startswith("Cass R. Sunstein, Interpreting Statutes")
        assert found["book"].startswith("Richard A. Posner, How Judges Think 45 (2008)")

    def test_a_regex_for_every_unbounded_run_is_bounded(self):
        """A guard on the patterns themselves: none may contain an unbounded repetition of a
        class that includes whitespace, which is what makes a failed match quadratic."""
        offenders = []
        for name, pattern in PATTERNS.items():
            source = pattern.pattern
            for m in re.finditer(r"\[[^\]]*\\s[^\]]*\](\*|\+)(?!\?)", source):
                offenders.append((name, m.group(0)))
        assert not offenders, offenders
