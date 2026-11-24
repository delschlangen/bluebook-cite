"""Reading text out of a PDF: fast, one page in memory at a time, and faithful on legal layouts.

    result = read_pdf(content)          # PdfResult(text, pages, warnings, engine)

Primary reader: pypdfium2 (pdfium), page by page, with a thin layout layer (superscripts rejoin
their line, pleading line numbers are dropped, footnotes are marked "[^N]" in the same syntax
the Word reader writes). Fallback: pdfminer.six, per page, only when the pdfium text looks
garbled, or for the whole file when pdfium cannot open it. Then text repair (ligatures, soft
hyphens, line-end hyphens, wrapped URLs) and removal of running headers, footers and page
numbers.

This replaced pdfplumber, which keeps every page's layout in memory: about 9 MB per page, so a
273-page PDF needed 2.5 GB and 40 s, and a long upload killed the server. This reader holds
about 25 MB however long the file is and reads 273 dense pages in about 4 s. On 17 realistic
PDFs (Chromium, reportlab and LibreOffice output: law review articles with footnotes, two
columns, pleading paper, hyphenation, ligatures, running footers) citation recall went from
97.3% to 99.96%, spurious citations from 60 to 1, and footnote numbers from 92.6% to 98.7%.

Requires pypdfium2 and pdfminer.six (see requirements.txt).
"""
from __future__ import annotations

import io
import math
import re
import signal
import statistics
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import NamedTuple

from ..limits import (
    MAX_PDF_FALLBACK_PAGES,
    MAX_PDF_PAGES,
    MAX_TEXT_CHARS,
    PDF_MAX_PAGE_CHARS,
    PDF_SECOND_OPINION_BUDGET_S,
    PDF_SECOND_OPINION_MAX_CHARS,
    PDF_TIME_BUDGET_S,
)

# =========================== text repair ===========================
#
# Every regular expression in this section runs over a whole page of text from an untrusted file,
# and a regular expression that is slow holds the interpreter lock until it finishes (nothing in
# the same process can interrupt it). So each is written to cost time linear in the page: a run
# that can repeat without limit is anchored by a look-behind, so that a match can only begin at the
# start of the run, and is possessive, so that the engine never backs into it. Without the anchor
# the engine tries every start inside a run of n letters and scans to the end of the run from each
# one: 64,000 letters (a 664-byte PDF) took 49 seconds. tests/test_pdf_repair.py times every
# expression here on long runs of letters, digits, punctuation, spaces and line breaks.
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
}
_LIG_TABLE = str.maketrans(_LIGATURES)
# characters some producers use for the hyphen drawn at a line end
_HYPHENS = "-\u2010\u2011\u00ad"

# A hyphen that ends a line: the word fragment before it, the hyphen, ONE line break, then the first
# token of the next line and the token after it on that line (at most 40 characters of each: all the
# decision needs). One line break only: a blank line is a paragraph break, and a word is never broken
# across paragraphs ("five-\n\nyear" must not become "fiveyear").
_LINE_END_HYPHEN = re.compile(
    rf"(?<![A-Za-z0-9])([A-Za-z0-9]++)([{_HYPHENS}])[ \t]*+\n[ \t]*+(?=(\S{{1,40}})(?:[ \t]++(\S{{1,40}}))?)"
)

# Line-end dehyphenation: is the hyphen one the typesetter added to break a word (drop it and join:
# "regu-\nlation" -> "regulation") or part of the spelling (keep it: "state-\nof-the-art")? It
# cannot be known from the text, so the rule keeps the hyphen whenever the compound reading is
# plausible, because a wrongly kept hyphen ("regu-lation") costs a reader nothing while a wrongly
# joined compound ("stateof-the-art", "Lopezde la Cruz") corrupts a name or a citation. It keeps it when
#   1. the next line starts with a digit or a capital: GAO-\n16-552, 10-\nK, Smith-\nJones, 1981-\n1983
#   2. the fragment is one character, holds a digit, or is an all-capitals acronym: e-\nmail, 5-\nyear,
#      FDA-\napproved
#   3. the fragment is a prefix that is nearly always hyphenated (non, anti, self, ...), or ends in the
#      vowel the next line starts with (re-\nenacted, co-\noperate)
#   4. the next line's first token is already hyphenated (state-\nof-the-art), or is "of" or "the" on its
#      own, or is a name particle after a capitalised fragment and before a capitalised word or another
#      particle (Lopez-\nde la Cruz, Garcia-\nde Leon)
# and otherwise drops it, as it always did, except that "and" or "or" on its own is a suspended hyphen
# ("pre-\nand post-trial" is "pre- and post-trial": the hyphen stays and so does the space). Particles are not accepted on their own because the last
# syllable of an ordinary word is often one ("Sulli-\nvan", "gar-\nden", "or-\nder", "mo-\ndel"). A soft
# hyphen (U+00AD) is the exception to 2-4: the typesetter chose that break and it is never part of a
# spelling. Inside a URL a hyphen before a lower-case word is left alone: it is part of the address
# wherever the line broke (_join_wrapped_urls joins a wrapped URL on its own evidence). If the next line
# does not start with two lower-case letters (a quotation mark, a bracket, a single letter) the text is
# left as it is.
_STRONG_PREFIXES = frozenset(
    "non anti self ex quasi semi vice half well ill cross e co post multi counter all".split()
)
_SUSPENDED_WORDS = frozenset("and or".split())     # "pre-\nand post-trial": a suspended hyphen, then a space
_JOINING_WORDS = frozenset("of the".split())
_PARTICLES = frozenset("de la le el del della di da du des van von der den dos das do".split())


def _dehyphenate(m: re.Match) -> str:
    frag, hyphen, nxt, after = m.group(1), m.group(2), m.group(3), m.group(4)
    first = nxt[0]
    if first.isdigit() or ("A" <= first <= "Z"):
        return frag + "-"
    # Inside a URL (judged by the 300 characters before the fragment) the hyphen is part of the address.
    before = m.string[max(0, m.start(1) - 300): m.start(1)]
    token = before[max(before.rfind(" "), before.rfind("\t"), before.rfind("\n")) + 1:]
    if _URL_START.match(token):
        return m.group(0)
    if not (len(nxt) >= 2 and nxt[:2].isascii() and nxt[:2].isalpha() and nxt[:2].islower()):
        return m.group(0)
    if hyphen == "\u00ad":
        return frag
    low, word = frag.lower(), nxt.lower()
    if word in _SUSPENDED_WORDS:
        return frag + "- "           # the line break stood where the space was
    if (
        len(frag) == 1
        or any(c.isdigit() for c in frag)
        or (len(frag) >= 2 and frag.isupper())
        or low in _STRONG_PREFIXES
        or (len(frag) >= 2 and low[-1] in "aeiou" and nxt[0].lower() == low[-1])
        or "-" in nxt
        or word in _JOINING_WORDS
        or (
            word in _PARTICLES
            and frag[0].isupper()
            and after is not None
            and (after[0].isupper() or after.lower() in _PARTICLES)
        )
    ):
        return frag + "-"
    return frag


# pdfium writes U+0002 (get_text_bounded) or U+FFFE (get_text_range) where it removed a line-end hyphen
# and joined the two halves of the word
_PDFIUM_HYPHEN_LOWER = re.compile(r"[\x02\ufffe](?=[a-z])")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")


# the same marker followed by the line break that pdfium_layout keeps between rectangles
_PDFIUM_HYPHEN_NL_LOWER = re.compile(r"[\x02\ufffe][ \t]*+\n[ \t]*+(?=[a-z])")
_PDFIUM_HYPHEN_NL_KEEP = re.compile(r"[\x02\ufffe][ \t]*+\n[ \t]*+(?=[0-9A-Z])")


_URL_START = re.compile(r"(?:https?://|www\.)", re.I)
_CONT_CHARS = "/-_=&?#%"
_CONT_TOKEN = re.compile(r"[A-Za-z0-9/_\-.%~#?=&:@+,;()]++")
# The start of a new numbered, bulleted or footnote line: never a continuation of the URL above it.
_NEW_ITEM = re.compile(
    r"\s*+(?:\[\^?e?\d{1,4}\]|\(?\d{1,3}[.)][ \t]|\d{1,3}[ \t]++\S|[\u2022\u2013\u2014*\-][ \t]++\S|[A-Za-z][.)][ \t])"
)
# A wrapped URL is at most this long; beyond it nothing is joined (a real URL is under about 2,000).
_MAX_URL_CHARS = 2000


def _is_url_continuation(tok: str, nxt_line: str, nxt_parts: list[str]) -> bool:
    """Does `nxt_line` carry on the URL `tok` that ends the line above it?

    Only on strong evidence: the URL ends in / - _ = & ? # % and the next line's first token looks
    like a path fragment (it has a digit, or one of / - _ = . &), or the next line's first token
    starts with one of those characters. Never when the next line begins a numbered or bulleted
    item or a footnote, and never when its first token is only a number of up to three digits (a
    page number or the next footnote's number: "https://www.cdc.gov/nchs/" above a footer "3" must
    stay as it is). A URL broken in the middle of a segment with no punctuation cannot be
    recognised and is left alone."""
    first = nxt_parts[0]
    if _NEW_ITEM.match(nxt_line):
        return False
    if _URL_START.match(first) and not tok.endswith("//"):
        return False                                  # another URL: two references, not one (but "https://" + "www.x.gov" is one)
    body = first.rstrip(".,;)")
    if not (body or first) or not _CONT_TOKEN.fullmatch(body or first):
        return False
    if body.isdigit():
        # a long number ("...gao-24-\n106481", "?id=\n20220412") is a continuation; a short one is a
        # page number or the next footnote's number
        return tok[-1] in _CONT_CHARS and len(body) >= 4
    if len(first) == 1 and first in _CONT_CHARS + "\u2013\u2014\u2022*":
        return False                                  # a lone "-" or "/" is a bullet or a dash, not a path
    starts_cont = first[0] in _CONT_CHARS
    ends_open = tok[-1] in _CONT_CHARS and any(c.isdigit() or c in "/-_=.&" for c in body)
    return starts_cont or ends_open


def _join_wrapped_urls(text: str) -> str:
    """Re-join a URL that the producer wrapped (see _is_url_continuation for the evidence).
    Linear in the text: each line is split once, and only the last token is carried forward."""
    if "http" not in text and "www." not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        pieces = [lines[i]]
        parts = lines[i].split()
        tok = parts[-1] if parts else ""
        while i + 1 < n and tok and _URL_START.match(tok) and len(tok) < _MAX_URL_CHARS:
            nxt_parts = lines[i + 1].split()
            if not nxt_parts or not _is_url_continuation(tok, lines[i + 1], nxt_parts):
                break
            pieces[-1] = pieces[-1].rstrip()
            pieces.append(lines[i + 1].lstrip())
            tok = tok + nxt_parts[0] if len(nxt_parts) == 1 else nxt_parts[-1]
            i += 1
        out.append("".join(pieces))
        i += 1
    return "\n".join(out)


def repair_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = _PDFIUM_HYPHEN_NL_LOWER.sub("", text)
    text = _PDFIUM_HYPHEN_NL_KEEP.sub("-", text)
    text = _PDFIUM_HYPHEN_LOWER.sub("", text)      # Enterpris\x02es -> Enterprises
    text = text.replace("\x02", "-").replace("\ufffe", "-")   # GAO\x0216-552 -> GAO-16-552
    text = _CTRL.sub("", text)
    text = text.translate(_LIG_TABLE)
    text = _LINE_END_HYPHEN.sub(_dehyphenate, text)
    # a soft hyphen that survived inside a word was never printed
    text = text.replace("\u00ad", "")
    # U+2010/2011 inside words are plain hyphens for every regex downstream
    text = text.replace("\u2010", "-").replace("\u2011", "-")
    return _join_wrapped_urls(text)


# =========================== running header / footer / page-number removal ===========================
_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
# "Page # of #", "page #", "# of #", "#/#", "- # -", with optional surrounding punctuation
_PAGE_LIKE = re.compile(r"^[\W_]*(page\s*)?#\s*((of|/|\|)\s*#)?[\W_]*$", re.I)
_DATE_LIKE = re.compile(r"^#[/.-]#[/.-]#(,?\s*#:#(:#)?\s*(am|pm)?)?$", re.I)
_NUM_ONLY = re.compile(r"^[\W_]*#[\W_]*$")

# A running header or footer is a short line. A longer one is never grouped, never removed, and
# never costs the time to normalise it.
_MAX_RUNNING_LINE = 300
# A page number has at most this many digits. int() of a longer run would also raise past Python's
# 4,300-digit limit; such a line is no page number.
_MAX_PAGE_DIGITS = 9

_CITATION_LIKE = re.compile(
    r"\u00a7|\bId\.|\bIbid\b|\bsupra\b|\binfra\b"
    # volume + reporter / code + page
    r"|\b\d+\s+(?:U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.|F\.(?:\s?\d?d|\s?\dth|\s?Supp\.?|\s?App'x)?|B\.R\.|U\.S\.C\.(?:A\.)?|C\.F\.R\.|Fed\.\s?Reg\.|Stat\.|Cong\.\s?Rec\."
    r"|N\.\s?[EW]\.|S\.\s?[EW]\.|So\.|[A-Z][A-Za-z]*\.\s+L\.\s?(?:Rev\.|J\.)|L\.\s?(?:Rev\.|J\.))"
    # citation types that have no volume number
    r"|\bH\.R\.\s|\bS\.\s?Rep\.|\bPub\.\s?L\.|\bFed\.\s?R\.\s|\bU\.S\.\s?Const\.|\bRestatement\b|\bU\.C\.C\.|\bModel\s+Penal\s+Code\b"
    r"|\bExec\.\s?Order\b|\bGAO-\d|\bCong\.\s?Rsch\.",
    re.I,
)


def _key(line: str) -> str:
    """What lines are grouped by across pages.

    Each URL on the line is compared exactly: two footnotes that cite
    congress.gov/bill/117th-congress/house-bill/1 and .../house-bill/2 are two citations, not one
    running footer, while a Chrome footer that prints the same URL (and "3/8") on every page is
    one. Everything else on the line has its digit runs replaced, so "Page 3 of 90" and "Page 4 of
    90" are the same line; strip_running_lines then checks that the digits that differ really are
    a page counter (_digit_fields_are_page_counters)."""
    norm = _WS.sub(" ", line.strip())
    parts: list[str] = []
    at = 0
    for m in _URL.finditer(norm):
        parts.append(_DIGITS.sub("#", norm[at:m.start()]))
        parts.append(m.group())
        at = m.end()
    parts.append(_DIGITS.sub("#", norm[at:]))
    return "".join(parts)


def _letter_count(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


def _is_boilerplate(raw: str, key: str) -> bool:
    return bool(_URL.search(raw) or _PAGE_LIKE.match(key) and "#" in key and not _NUM_ONLY.match(key) or _DATE_LIKE.match(key))


def _edge_indices(lines: list[str], k: int) -> set[int]:
    nonblank = [i for i, line in enumerate(lines) if line.strip()]
    return set(nonblank[:k]) | set(nonblank[-k:]) if nonblank else set()


def _digit_fields_are_page_counters(raws: dict[int, str]) -> bool:
    """`raws` maps a page index to a line. True if the lines differ only in digit runs that count
    pages: a run is fine if it is the same on every page, or if on at least 80% of the pages it is
    the page index plus one constant (the page number, a Bates number, "Page 7 of 25").

    The lines are grouped with their digits blanked out, so without this check any lines of the
    same shape ("Case 1:20-cv-0123 ... Page 7 of 25" and "Smith v. Jones, 5 U.S. 137" below
    "Smith v. Jones, 6 U.S. 138") would be taken for one repeated line and all be removed."""
    fields = [_DIGITS.findall(raw) for raw in raws.values()]
    if len({len(f) for f in fields}) != 1:
        return False
    pages = list(raws)
    for k in range(len(fields[0])):
        values = [f[k] for f in fields]
        if len(set(values)) == 1:
            continue
        if any(len(v) > _MAX_PAGE_DIGITS for v in values):
            return False
        offsets = Counter(int(v) - pi for v, pi in zip(values, pages, strict=True))
        if offsets.most_common(1)[0][1] < 0.8 * len(values):
            return False
    return True


_extractor = None


def _citation_veto(line: str) -> bool:
    """True if the citation extractor reads `line` as a citation (other than a bare web address,
    which a repeated footer legitimately is). Used as strip_running_lines's `veto`, so that a
    footnote is never removed as a running footer because it repeats: _CITATION_LIKE knows the
    common forms, the extractor knows the rest ("47 CFR 54.101", "FRCP 12(b)(6)", "HR 1234").

    The extractor is imported on first use, which is the first time a line is about to be
    removed, so a file with no running lines never pays for it (about 0.2 s). A line the extractor
    cannot judge stays."""
    global _extractor
    try:
        if _extractor is None:
            from .extractor import CitationExtractor

            _extractor = CitationExtractor()
        return any(c.type.value != "website" for c in _extractor.extract_all(line))
    except Exception:
        return True


def strip_running_lines(
    pages: list[str],
    *,
    edge_lines: int = 3,
    min_pages: int = 5,
    min_fraction: float = 0.5,
    boilerplate_min_pages: int = 3,
    boilerplate_fraction: float = 0.8,
    min_count: int = 3,
    veto: Callable[[str], bool] | None = None,
    protect_short: bool = True,
    protect_citations: bool = True,
    return_report: bool = False,
):
    """Return `pages` with running header/footer/page-number lines removed (same length, same order).

    `veto(line) -> True` lets the caller protect additional lines (for example, anything the citation
    extractor recognises).  With `return_report=True` the result is `(pages, report)` where report maps
    each removed normalised line to the number of pages it was removed from.

    A line is removed only if it repeats on enough pages (see the parameters), is short, is not a
    citation, and, if its digits differ from page to page, they count pages (_key, _digit_fields_are_page_counters).
    """
    n_text_pages = sum(1 for p in pages if p and p.strip())
    if n_text_pages < boilerplate_min_pages:
        return (list(pages), {}) if return_report else list(pages)

    split = [p.split("\n") for p in pages]
    zones = [_edge_indices(lines, edge_lines) for lines in split]

    raws: dict[str, dict[int, str]] = defaultdict(dict)     # key -> page index -> the line as printed
    page_number_candidates: list[tuple[int, int, int]] = []     # (page index, line index, value)
    for pi, (lines, zone) in enumerate(zip(split, zones, strict=True)):
        for li in zone:
            raw = lines[li]
            if len(raw) > _MAX_RUNNING_LINE:
                continue
            key = _key(raw)
            if not key:
                continue
            if _NUM_ONLY.match(key):
                # a bare number is judged below, on its own rule (it must climb with the page index)
                m = _DIGITS.search(raw)
                if m and len(m.group()) <= _MAX_PAGE_DIGITS:
                    page_number_candidates.append((pi, li, int(m.group())))
                continue
            raws[key][pi] = raw

    running: set[str] = set()
    for key, by_page in raws.items():
        count = len(by_page)
        if count < min_count:
            continue
        samples = list(by_page.values())
        raw = samples[0]
        if protect_short and _letter_count(key) < 3 and not _is_boilerplate(raw, key):
            continue                                       # "Id.", "Ex. #", "Tr." and friends
        if _is_boilerplate(raw, key):
            repeats = n_text_pages >= boilerplate_min_pages and count >= max(min_count, math.ceil(boilerplate_fraction * n_text_pages))
        else:
            repeats = n_text_pages >= min_pages and count >= max(min_count, math.ceil(min_fraction * n_text_pages))
        if not repeats or not _digit_fields_are_page_counters(by_page):
            continue
        # Last, and only for a line that is about to be removed: nothing that holds a citation is
        # ever removed, however often it repeats. (`veto` may be slow, such as the citation
        # extractor, which is why it is asked only now.)
        if protect_citations and any(_CITATION_LIKE.search(line) for line in samples):
            continue
        # (the lines of one group have one shape, so three of them are enough to ask about)
        if veto is not None and any(veto(line) for line in (samples[0], samples[len(samples) // 2], samples[-1])):
            continue
        running.add(key)

    # page numbers: a first/last line whose value is (page index + a constant offset) on enough pages
    drop_numbers: set[tuple[int, int]] = set()
    by_offset: dict[int, set[int]] = defaultdict(set)
    for pi, _li, v in page_number_candidates:
        by_offset[v - pi].add(pi)
    need = max(min_count, math.ceil(min_fraction * n_text_pages))
    good_offsets = {off for off, pset in by_offset.items() if len(pset) >= need}
    drop_numbers = {(pi, li) for pi, li, v in page_number_candidates if v - pi in good_offsets}

    removed: Counter = Counter()
    out = []
    for pi, (lines, zone) in enumerate(zip(split, zones, strict=True)):
        keep = []
        for li, raw in enumerate(lines):
            if (pi, li) in drop_numbers:
                removed["#"] += 1
                continue
            if li in zone and len(raw) <= _MAX_RUNNING_LINE:
                key = _key(raw)
                if key in running:
                    removed[key] += 1
                    continue
            keep.append(raw)
        out.append("\n".join(keep).strip("\n") if len(keep) != len(lines) else "\n".join(keep))
    return (out, dict(removed)) if return_report else out


# =========================== pdfium layout layer ===========================
_LEAD_NUM = re.compile(r"^(\d{1,3})(?:\s+|(?=[A-Z\"\u201c\u2018(\[])|$)")
_BARE_NUMBER = re.compile(r"^\d{1,3}$")


def _squash(s: str) -> str:
    return re.sub(r"[\s\x02\ufffe\u00ad\-\u2010]", "", s)


def _plain(tp) -> str:
    return tp.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n")


def _build_lines(tp, whole: str, page_w: float, page_h: float, deadline: float | None = None):
    lines: list[dict] = []
    cur = None
    for i, ch in enumerate(whole):
        # the time limit is checked inside the page, not only between pages: one page can hold
        # a million characters, and this loop costs about 30 microseconds for each
        if deadline is not None and not i & 0x7FF and time.monotonic() > deadline:
            raise PdfReadError(_TOO_SLOW)
        if ch == "\r" or ch == "\n":
            continue
        left, b, r, t = tp.get_charbox(i, loose=True)
        h = t - b
        degenerate = h <= 0.01 or r - left <= 0.01
        if not degenerate and (r < 0 or left > page_w or t < 0 or b > page_h):
            continue                      # off-page (hidden) text
        if cur is None:
            cur = {"chars": [(ch, left, r)], "mb": b, "mt": t, "r": r, "l": left, "t": t, "b": b, "last": (left, b, r, t)}
            lines.append(cur)
            continue
        if degenerate:
            cur["chars"].append((ch, cur["r"], cur["r"]))
            continue
        if (left, b, r, t) == cur["last"]:
            # pdfium expands a ligature glyph into 2-3 characters that all carry the glyph's box (same x AND y)
            cur["chars"].append((ch, left, r))
            continue
        mh = cur["mt"] - cur["mb"]
        ov = min(t, cur["mt"]) - max(b, cur["mb"])
        same_size = min(h, mh) >= 0.8 * max(h, mh)
        same_line = (ov >= 0.5 * min(h, mh)) if same_size else (ov > 0)
        if same_line and left >= cur["r"] - 0.8 * mh:
            cur["chars"].append((ch, left, r))
            cur["last"] = (left, b, r, t)
            cur["r"] = max(cur["r"], r)
            cur["t"], cur["b"] = max(cur["t"], t), min(cur["b"], b)
            if h > mh:
                cur["mb"], cur["mt"] = b, t
        else:
            cur = {"chars": [(ch, left, r)], "mb": b, "mt": t, "r": r, "l": left, "t": t, "b": b, "last": (left, b, r, t)}
            lines.append(cur)
    for L in lines:
        L["h"] = L["mt"] - L["mb"]
        L["text"] = "".join(c for c, _, _ in L["chars"]).strip()
    return [L for L in lines if L["text"]]


def _lead_token(L, page_w):
    """(value, right_edge, n_chars) of a leading 1-2 digit token followed by a wide gap, else None."""
    ch = L["chars"]
    k = 0
    while k < len(ch) and ch[k][0].isspace():
        k += 1
    j = k
    while j < len(ch) and ch[j][0].isdigit() and j - k < 2:
        j += 1
    if j == k:
        return None
    r = ch[j - 1][2]
    nxt = ch[j][1] if j < len(ch) else None
    if j < len(ch) and ch[j][0].isdigit():
        return None
    if nxt is not None and ch[j][0] != " " and nxt - r < 0.6 * L["h"]:
        return None
    # the token must be followed by a gap in x (to the next non-space char)
    m = j
    while m < len(ch) and ch[m][0].isspace():
        m += 1
    if m < len(ch) and ch[m][1] - r < 1.2 * L["h"]:
        return None
    if r > 0.22 * page_w:
        return None
    return int("".join(c for c, _, _ in ch[k:j])), r, j


def _drop_pleading_numbers(lines, page_w):
    cands = []
    for idx, L in enumerate(lines):
        tk = _lead_token(L, page_w)
        if tk:
            cands.append((idx, tk[0], tk[1], tk[2], L["mb"]))
    if len(cands) < 8:
        return lines
    groups: dict[int, list] = {}
    for c in cands:
        groups.setdefault(round(c[2] / 3), []).append(c)
    drop_tok: dict[int, int] = {}
    for g in groups.values():
        g.sort(key=lambda c: -c[4])
        i = 0
        while i < len(g):
            j = i
            while j + 1 < len(g) and g[j + 1][1] == g[j][1] + 1:
                j += 1
            if j - i + 1 >= 8:
                ys = [g[k][4] for k in range(i, j + 1)]
                gaps = [ys[k] - ys[k + 1] for k in range(len(ys) - 1)]
                if statistics.pstdev(gaps) < 1.6:
                    for k in range(i, j + 1):
                        drop_tok[g[k][0]] = g[k][3]
            i = j + 1
    if not drop_tok:
        return lines
    out = []
    for idx, L in enumerate(lines):
        if idx in drop_tok:
            L["chars"] = L["chars"][drop_tok[idx]:]
            L["text"] = "".join(c for c, _, _ in L["chars"]).strip()
            if not L["text"]:
                continue
        out.append(L)
    return out


def _mark_footnotes(lines, page_h, state):
    weights = [(L["h"], len(L["text"])) for L in lines if len(L["text"]) > 25]
    if len(weights) < 4:
        return
    weights.sort()
    total = sum(w for _, w in weights)
    acc, body_h = 0, weights[-1][0]
    for h, w in weights:
        acc += w
        if acc >= total / 2:
            body_h = h
            break
    # geometry, not stream order: the block may be drawn before or after the body, and a running
    # footer may be drawn after it
    region = [i for i, L in enumerate(lines) if L["h"] <= 0.93 * body_h and L["mt"] < 0.62 * page_h]
    if not region:
        return
    left_edge = min(lines[i]["l"] for i in region)
    cands = []
    for i in region:
        m = _LEAD_NUM.match(lines[i]["text"])
        if not m or lines[i]["l"] > left_edge + 6:
            continue
        # a bare number in the page-footer zone is a page number, not a footnote
        if _BARE_NUMBER.match(lines[i]["text"]) and lines[i]["mt"] < 0.09 * page_h:
            continue
        cands.append((i, int(m.group(1))))
    exp = state.get("next")

    def chain_from(start_n, from_idx):
        want, trial = start_n, []
        for i, n in cands[from_idx:]:
            if n == want:
                trial.append((i, n))
                want += 1
        return trial

    chosen: list = chain_from(exp, 0) if exp is not None else []
    if not chosen:
        # no history, or the counter was lost / restarted: accept the longest consecutive run on this page
        for s in range(len(cands)):
            trial = chain_from(cands[s][1], s)
            if len(trial) > len(chosen):
                chosen = trial
        if len(chosen) == 1 and chosen[0][1] > 3:
            chosen = []                       # a lone number with no counter history is not evidence
    for i, n in chosen:
        lines[i]["text"] = _LEAD_NUM.sub(f"[^{n}] ", lines[i]["text"], count=1)
    if chosen:
        state["next"] = chosen[-1][1] + 1


def _page_text(page, tp, state, deadline: float | None = None, layout: bool = True):
    """The text of one page. With `layout` False (a page with more characters than
    PDF_MAX_PAGE_CHARS) the characters are returned as pdfium has them, without the per-character
    layout analysis that costs about 800 bytes of memory for each of them."""
    if not layout:
        return _plain(tp)
    whole_raw = tp.get_text_range()
    plain = _plain(tp)
    if len(whole_raw) != tp.count_chars() or not whole_raw.strip():
        return plain
    page_w, page_h = page.get_size()
    try:
        lines = _build_lines(tp, whole_raw, page_w, page_h, deadline)
        before = sum(len(_squash(L["text"])) for L in lines)
        lines = _drop_pleading_numbers(lines, page_w)
    except PdfReadError:
        raise
    except Exception:
        return plain
    n_plain = len(_squash(plain))
    if not lines or before < 0.97 * n_plain or before > 1.03 * n_plain:
        return plain
    _mark_footnotes(lines, page_h, state)
    return "\n".join(L["text"] for L in lines)


# ===========================================================================================
# Reader: page cap, pdfium (+ layout) as primary, pdfminer.six as fallback, repair, strip.
#
# This runs inside the child process of services/sandbox.py, which is the safety net: the limits
# below are the first line, so that an ordinary hostile file is refused with a precise message
# before the child's memory, CPU or wall-clock limit has to stop it.
# ===========================================================================================

MAX_FALLBACK_PAGES = MAX_PDF_FALLBACK_PAGES

_TOO_SLOW = "Reading this PDF took too long. Try a shorter file."

# A page is refused before layout if its character count is over what is left of the text budget
# by more than this (repair adds a few characters, expanding ligatures, so a page is allowed a little over).
_BUDGET_SLACK_CHARS = 1024

# pdfium is not thread-safe by contract.  Taking one lock around every use is both safe and, measured,
# 4.5x faster than letting 8 threads contend (14.6 s vs 67 s for 200 parses).  The lock is held only
# while pdfium is in use: never while the second reader (pdfminer) runs.
_PDFIUM_LOCK = threading.Lock()

# How long one upload will wait for another to finish being read. A read is capped at
# PDF_TIME_BUDGET_S, so a wait this long means either a queue of large files or a bug that left
# the lock held. Either way the person gets "busy, try again" instead of a request that never
# answers. (The server reads each upload in its own child process, so this wait only happens when
# the reader is used directly.)
_LOCK_WAIT_S = 60.0


@contextmanager
def _pdfium_session():
    if not _PDFIUM_LOCK.acquire(timeout=_LOCK_WAIT_S):
        raise PdfBusyError(
            "The server is busy reading other documents. Please try again in a minute."
        )
    try:
        yield
    finally:
        _PDFIUM_LOCK.release()


class PdfReadError(ValueError):
    """The message is written for the person who uploaded the file."""


class PdfBusyError(PdfReadError):
    """Another upload is being read and this one waited too long. Not a fault in the file."""


class PdfTooLongError(PdfReadError):
    """Over the page or text limit.  Map to HTTP 413 so the page can say what the limit is."""


class PdfResult(NamedTuple):
    text: str
    pages: int
    warnings: list
    engine: str            # "pdfium" or "pdfium+pdfminer" or "pdfminer"


class _TimeUp(BaseException):
    """Raised by an interval timer inside pdfminer's pure-Python code. A BaseException so that no
    `except Exception` in a library can swallow it."""


@contextmanager
def _time_limit(seconds: float):
    """Interrupt pure-Python work (pdfminer) after `seconds` of processor time by raising _TimeUp.

    The deadline checks between pages cannot stop one page that takes minutes; this can, because a
    signal handler runs between the interpreter's own steps. Its limits: it needs the main thread
    and POSIX (elsewhere it does nothing, and only the caller's wall-clock limit applies), and a
    single long call into C (a regular expression, zlib) is interrupted only when it returns.
    It uses ITIMER_PROF, leaving the real-time alarm that the child arms for itself alone."""
    usable = (
        hasattr(signal, "setitimer")
        and hasattr(signal, "SIGPROF")
        and threading.current_thread() is threading.main_thread()
    )
    if not usable:
        yield
        return
    if seconds <= 0:
        raise _TimeUp()

    def on_alarm(signum, frame):
        raise _TimeUp()

    previous = signal.signal(signal.SIGPROF, on_alarm)
    signal.setitimer(signal.ITIMER_PROF, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0)
        signal.signal(signal.SIGPROF, previous if previous is not None else signal.SIG_DFL)


def _open(content: bytes):
    import pypdfium2 as pdfium
    try:
        return pdfium.PdfDocument(content)
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        if "password" in msg:
            raise PdfReadError("This PDF is password protected. Remove the password and upload it again.") from exc
        raise PdfReadError("This PDF looks damaged or incomplete (the upload may have been cut off).") from exc


def page_count(content: bytes) -> int:
    """Number of pages, in 0.3-3 ms for any size (no page is parsed).  A regex over '/Type /Page' is NOT a
    substitute: it reports 0 pages for PDFs that keep their page objects in compressed object streams.
    This is the number the file DECLARES (pdfium trusts /Count); see _loadable_pages and _pages_in_file."""
    with _pdfium_session():
        pdf = _open(content)
        try:
            return len(pdf)
        finally:
            pdf.close()


def _loadable_pages(content: bytes, declared: int) -> int:
    """How many of the `declared` pages really load.

    A /Count that is too large (3 pages and /Count 450) must not refuse a small file with "this PDF
    has 450 pages", nor tell the person to run OCR on pages that do not exist. Page `declared - 1`
    is tried first and, if it loads, nothing is wrong; otherwise the first page that fails is found
    by bisection (a page tree holds pages up to some number and none after), a dozen loads even for
    a /Count of two billion."""
    with _pdfium_session():
        pdf = _open(content)
        try:
            def loads(i: int) -> bool:
                try:
                    pdf[i].close()
                    return True
                except Exception:
                    return False

            if loads(declared - 1):
                return declared
            lo, hi = 0, declared - 1              # every page before lo loads; page hi does not
            while lo < hi:
                mid = (lo + hi) // 2
                if loads(mid):
                    lo = mid + 1
                else:
                    hi = mid
            return lo
        finally:
            pdf.close()


_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![A-Za-z])")


def _count_page_objects(content: bytes, stop_above: int) -> int:
    """'/Type /Page' objects written out in the file (a quick suspicion only: objects inside
    compressed object streams are invisible to it, and an old revision of a page left by an
    incremental save counts again). Counting stops once it passes `stop_above`."""
    n = 0
    for _ in _PAGE_OBJECT.finditer(content):
        n += 1
        if n > stop_above:
            break
    return n


def _pdfminer_page_total(content: bytes, limit: int) -> int:
    """Pages in the page tree as pdfminer walks it (which ignores /Count), counted up to `limit`."""
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    document = PDFDocument(PDFParser(io.BytesIO(content)))
    n = 0
    for _ in PDFPage.create_pages(document):
        n += 1
        if n >= limit:
            break
    return n


def _pages_in_file(content: bytes, declared: int, max_pages: int) -> int:
    """The page count the file really has, when the declared one is too SMALL.

    pdfium trusts /Count, so a PDF that says 5 and holds 401 would be read as 5 pages and the other
    396 dropped without a word. Only if the file visibly holds more page objects than it declares is
    a second reader asked (it walks the page tree and ignores /Count); a file that does not is
    taken at its word. Counts up to max_pages + 1, which is enough to refuse an over-long file."""
    if _count_page_objects(content, declared) <= declared:
        return declared
    try:
        with _time_limit(PDF_SECOND_OPINION_BUDGET_S):
            return max(declared, _pdfminer_page_total(content, max_pages + 1))
    except (_TimeUp, Exception):
        return declared


def iter_pdf_pages(
    content: bytes,
    stats: dict | None = None,
    deadline: float | None = None,
    *,
    budget: float | None = None,
    max_chars: int | None = None,
    limit: int | None = None,
) -> Iterator[str]:
    """Generator over the RAW text of each page (pdfium + layout).  Memory is one page at a time.

    `budget` (seconds) starts the clock once the reader's lock is held, so that waiting for
    another upload is not charged to this one; `deadline` is an absolute time for callers that
    have one. `max_chars` is the text allowance: a page whose character count passes what is
    left of it is refused before any layout is built. `limit` stops after that many pages.

    A page that fails to load yields "" and is counted in stats["failed_pages"] (and its index in
    stats["load_failed"]); the document goes on. stats["deadline"] reports the deadline in force.
    """
    stats = stats if stats is not None else {}
    stats.setdefault("failed_pages", 0)
    stats.setdefault("load_failed", [])
    stats.setdefault("unlaid_pages", 0)
    with _pdfium_session():
        if budget is not None:
            deadline = time.monotonic() + budget
        stats["deadline"] = deadline
        pdf = _open(content)
        state: dict = {}
        used = 0
        try:
            count = len(pdf) if limit is None else min(len(pdf), limit)
            for i in range(count):
                if deadline is not None and time.monotonic() > deadline:
                    raise PdfReadError(_TOO_SLOW)
                try:
                    page = pdf[i]
                except Exception:
                    stats["load_failed"].append(i)
                    stats["failed_pages"] += 1
                    yield ""
                    continue
                try:
                    tp = page.get_textpage()
                    try:
                        n = tp.count_chars()
                        if max_chars is not None and n > max_chars - used + _BUDGET_SLACK_CHARS:
                            raise PdfTooLongError(_too_much_text(max_chars))
                        layout = n <= PDF_MAX_PAGE_CHARS
                        if not layout:
                            stats["unlaid_pages"] += 1
                        text = _page_text(page, tp, state, deadline, layout)
                    finally:
                        tp.close()
                except PdfReadError:
                    raise
                except Exception:
                    stats["failed_pages"] += 1
                    text = ""
                finally:
                    page.close()
                used += len(text)
                yield text
        finally:
            pdf.close()


# ---- garbled-text detection and the pdfminer fallback ------------------------------------------------
_STOP = frozenset("the of and to in a is that for it as was with be by on not this are or from at which but have an had they their were has been if more when will would who so no".split())
_WORD = re.compile(r"[A-Za-z']+")
_CID = re.compile(r"\(cid:\d+\)")


def _quality(text: str) -> tuple[float, float, bool]:
    """(share of ordinary words, share of control characters, whether "(cid:N)" codes make up a real
    part of the text). A page that merely mentions "(cid:12)" in a sentence is not leaking codes;
    a page that does has them for 2% or more of its characters."""
    words = _WORD.findall(text)
    stop = sum(1 for w in words if w.lower() in _STOP) / max(1, len(words))
    ctrl = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t") / max(1, len(text))
    codes = _CID.findall(text)
    leaking = len(codes) >= 2 and sum(map(len, codes)) >= 0.02 * len(text)
    return stop, ctrl, leaking


def _garble_evidence(text: str) -> str | None:
    """How sure we are that a page's text is corrupt: "strong", "weak" or None.

    Strong evidence is control characters or a real share of "(cid:N)" codes in the text: a font
    with no text map makes a reader emit codes instead of letters, and real text has neither in
    quantity (a single literal "(cid:12)" in a sentence is not evidence: it used to send pages that
    quote one to the slow second reader). Weak evidence is a very low share of ordinary words
    ("the", "of", "and"). Normal prose has 25-40%, but a table of authorities, a works-cited list or
    a page of footnotes that is all citations can sit below 5% and be perfectly good text. So a weak
    signal is reported but is never grounds to reject a file, and it no longer earns the slow
    second reader either: that reader is for pages with strong evidence only.
    """
    if len(text.strip()) < 150:
        return None
    stop, ctrl, cid = _quality(text)
    if ctrl > 0.01 or cid:
        return "strong"
    if sum(c.isalpha() for c in text) >= 150 and stop < 0.05:
        return "weak"
    return None


def _looks_garbled(text: str) -> bool:
    return _garble_evidence(text) == "strong"


def _pdfminer_pages(content: bytes, page_numbers=None) -> Iterator[str]:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextContainer
    for layout in extract_pages(io.BytesIO(content), laparams=LAParams(), page_numbers=page_numbers):
        yield "".join(el.get_text() for el in layout if isinstance(el, LTTextContainer))


def _second_opinion(content: bytes, index: int, first: str, deadline: float | None = None) -> str:
    """The page as the second reader (pdfminer) has it if that is clearly better, else `first`.

    Bounded: it does not run for a page of more than PDF_SECOND_OPINION_MAX_CHARS (pdfminer's layout
    analysis is worse than quadratic in the number of text boxes: 2,000 scattered words took two
    minutes), it is interrupted after what is left until `deadline`, and it never runs while the
    pdfium lock is held (read_pdf calls it afterwards)."""
    if len(first) > PDF_SECOND_OPINION_MAX_CHARS:
        return first
    remaining = PDF_SECOND_OPINION_BUDGET_S if deadline is None else deadline - time.monotonic()
    if remaining <= 0:
        return first
    try:
        with _time_limit(remaining):
            for alt in _pdfminer_pages(content, [index]):
                alt = repair_text(alt)
                s1, c1, id1 = _quality(first)
                s2, c2, id2 = _quality(alt)
                better = (s2 >= s1 + 0.10 and c2 <= c1) or (c1 > 0.01 and c2 < c1 / 2 and not id2)
                return alt if better else first
    except (_TimeUp, Exception):
        pass
    return first


def read_pdf(content: bytes, *, max_pages: int | None = None, max_chars: int | None = None,
             time_budget: float | None = None) -> PdfResult:
    """Read a PDF into one string.  Raises PdfReadError / PdfTooLongError with a message fit to show the user."""
    max_pages = MAX_PDF_PAGES if max_pages is None else max_pages
    max_chars = MAX_TEXT_CHARS if max_chars is None else max_chars
    budget = PDF_TIME_BUDGET_S if time_budget is None else time_budget
    warnings: list[str] = []
    engine = "pdfium"
    still_garbled = 0

    try:
        declared = page_count(content)
    except PdfReadError as first_error:
        # pdfium refused the file.  A password is final, and so is "busy" (that says nothing about
        # the file); anything else gets one try with pdfminer.
        if isinstance(first_error, PdfBusyError) or "password" in str(first_error).lower():
            raise
        pages = []
        total = 0
        deadline = time.monotonic() + budget
        try:
            with _time_limit(budget):
                for raw in _pdfminer_pages(content):
                    # Same ceilings as the main path: this reader is about ten times slower, so it
                    # is the one that could otherwise run on and on over a large damaged file.
                    if len(pages) >= max_pages:
                        raise PdfTooLongError(_too_long(len(pages) + 1, max_pages))
                    if time.monotonic() > deadline:
                        raise PdfReadError(_TOO_SLOW)
                    text = repair_text(raw)
                    total += len(text)
                    if total > max_chars:
                        raise PdfTooLongError(_too_much_text(max_chars))
                    pages.append(text)
        except _TimeUp:
            raise PdfReadError(_TOO_SLOW) from None
        except PdfReadError:
            raise
        except Exception:
            raise first_error from None
        if not pages:
            # Neither reader found a page: there is nothing to read, and "damaged" is the
            # honest description of a file with a page tree that holds no pages.
            raise first_error
        engine = "pdfminer"
    else:
        if declared == 0:
            raise PdfReadError("This PDF has no pages.")
        # The declared count is a claim. Too large (3 pages, /Count 450): find what loads. Too small
        # (401 pages, /Count 5): pdfium would read 5 and drop the rest silently, so a file that
        # visibly holds more is checked with the second reader's page walk.
        n = declared
        if n > max_pages:
            n = _loadable_pages(content, declared)
            if n > max_pages:
                raise PdfTooLongError(_too_long(n, max_pages))
        in_file = _pages_in_file(content, declared, max_pages) if n == declared else n
        if in_file > max_pages:
            raise PdfTooLongError(_too_long(in_file, max_pages, at_least=True))

        pages = []
        stats: dict = {}
        total = 0
        garbled: list[int] = []                       # indexes of the pages whose text looks garbled
        kept_raw: dict[int, str] = {}                 # their raw text, for as many as get a second opinion
        # The generator holds the PDF reader's lock while it is open. A for-loop that is left
        # by an exception does not close it: the traceback keeps the generator alive, and with
        # it the lock, until the exception is garbage collected. Close it explicitly so that a
        # limit being hit never leaves the next upload waiting.
        reader = iter_pdf_pages(content, stats, budget=budget, max_chars=max_chars, limit=n)
        try:
            for i, raw in enumerate(reader):
                text = repair_text(raw)           # garbled-ness is judged on the RAW text; repair drops control characters
                evidence = _garble_evidence(raw)
                if evidence == "strong":
                    # Only hard evidence earns the slow second reader. A page that merely has few
                    # ordinary words (a table of authorities, a page of scattered figures) used to
                    # get one too, and that is the reader that took minutes over a crafted page;
                    # on the test corpus and the bench documents the weak signal never fired
                    # on a page the second reader then improved.
                    garbled.append(i)
                    if len(kept_raw) < MAX_FALLBACK_PAGES:
                        kept_raw[i] = raw
                total += len(text)
                if total > max_chars:
                    raise PdfTooLongError(_too_much_text(max_chars))
                pages.append(text)
        finally:
            reader.close()
        deadline = stats.get("deadline") or time.monotonic() + budget

        # The second reader runs here, after the lock is released, for the first few pages that look
        # garbled, and only for as long as PDF_SECOND_OPINION_BUDGET_S (and the read's own deadline) allow.
        second_deadline = min(deadline, time.monotonic() + PDF_SECOND_OPINION_BUDGET_S)
        fallbacks = 0
        for i in garbled:
            replaced = False
            if fallbacks < MAX_FALLBACK_PAGES and i in kept_raw and time.monotonic() < second_deadline:
                fallbacks += 1
                alt = _second_opinion(content, i, kept_raw[i], second_deadline)
                if alt is not kept_raw[i]:
                    pages[i], replaced, engine = alt, True, "pdfium+pdfminer"
            # A page whose second opinion did not clearly improve it still counts toward
            # rejecting the file (only strong evidence is ever in this list).
            if not replaced or _looks_garbled(pages[i]):
                still_garbled += 1

        if in_file > n:
            # Pages the file holds beyond its declared count are read with the second reader.
            try:
                with _time_limit(max(0.0, deadline - time.monotonic())):
                    for raw in _pdfminer_pages(content, set(range(n, in_file))):
                        pages.append(repair_text(raw))
            except _TimeUp:
                raise PdfReadError(_TOO_SLOW) from None
            except PdfReadError:
                raise
            except Exception:
                pass
            engine = "pdfium+pdfminer"
            warnings.append(
                f"This PDF says it has {declared} pages but the file holds {len(pages)}. "
                "All of them were read, the extra ones with a slower reader."
            )
        else:
            # Trailing pages that do not exist (a /Count that is too large) are not pages: they are
            # not "skipped", and they are not scanned pages that need OCR.
            failed_to_load = set(stats.get("load_failed", []))
            real = len(pages)
            while real > 0 and (real - 1) in failed_to_load:
                real -= 1
            if real == 0:
                raise PdfReadError("This PDF looks damaged or incomplete (the upload may have been cut off).")
            if real < len(pages):
                stats["failed_pages"] -= len(pages) - real
                pages = pages[:real]
            if real < declared:
                warnings.append(
                    f"This PDF says it has {declared} pages but the file holds {real}. "
                    f"All {real} were read."
                )
        if sum(len(p) for p in pages) > max_chars:
            raise PdfTooLongError(_too_much_text(max_chars))
        if stats.get("failed_pages"):
            warnings.append(f"{stats['failed_pages']} page(s) of this PDF could not be read and were skipped.")
        if stats.get("unlaid_pages"):
            warnings.append(
                f"{stats['unlaid_pages']} page(s) hold an unusually large amount of text and were read "
                "without layout analysis, so footnote marks may be missing there."
            )

    empty = sum(1 for p in pages if len(p.strip()) < 20)
    if still_garbled and still_garbled >= 0.5 * len(pages):
        raise PdfReadError(
            "This PDF's text layer is unreadable (its fonts have no text map, so the letters come out as codes). "
            "Export it again from the original program, or run OCR on it."
        )
    if pages and empty == len(pages):
        return PdfResult("", len(pages), warnings, engine)             # scanned: main.py already explains OCR
    if empty:
        warnings.append(f"{empty} of {len(pages)} pages have no readable text (scanned pages need OCR).")
    if still_garbled:
        warnings.append(f"{still_garbled} page(s) have an unreadable text layer and may need OCR.")
    if b"/Encrypt" in content:
        warnings.append("This PDF is encrypted, so some text may be missing.")

    pages = strip_running_lines(pages, veto=_citation_veto)
    text = "\n\n".join(p for p in pages if p.strip())
    return PdfResult(text, len(pages), warnings, engine)


def _too_much_text(limit: int) -> str:
    return (
        f"This PDF holds more text than the {limit:,}-character limit. "
        "Split it into parts and upload each part."
    )


def _too_long(n: int, limit: int, at_least: bool = False) -> str:
    if at_least:
        return (f"This PDF has more than {limit} pages, which is over the {limit}-page limit. "
                f"Split it into parts of {limit} pages or fewer and upload each part.")
    return (f"This PDF has {n} pages, which is over the {limit}-page limit. "
            f"Split it into parts of {limit} pages or fewer and upload each part.")
