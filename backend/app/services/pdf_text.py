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
import statistics
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import NamedTuple

from ..limits import MAX_PDF_FALLBACK_PAGES, MAX_PDF_PAGES, MAX_TEXT_CHARS, PDF_TIME_BUDGET_S

# =========================== text repair ===========================
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
}
_LIG_TABLE = str.maketrans(_LIGATURES)
# characters some producers use for the hyphen drawn at a line end
_HYPHENS = "-\u2010\u2011\u00ad"

# word-fragment, hyphen, line break, lower-case continuation  ->  join, drop the hyphen
_SPLIT_WORD = re.compile(rf"([A-Za-z]{{2,}})[{_HYPHENS}][ \t]*\n+[ \t]*([a-z]{{2,}})")
# hyphen, line break, then a digit or capital: a real hyphen (GAO-16-\n552, 111-\n148) -> keep it, join
_KEEP_HYPHEN = re.compile(rf"([A-Za-z0-9])[{_HYPHENS}][ \t]*\n+[ \t]*(?=[0-9A-Z])")


# pdfium writes U+0002 (get_text_bounded) or U+FFFE (get_text_range) where it removed a line-end hyphen
# and joined the two halves of the word
_PDFIUM_HYPHEN_LOWER = re.compile(r"[\x02\ufffe](?=[a-z])")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")


# the same marker followed by the line break that pdfium_layout keeps between rectangles
_PDFIUM_HYPHEN_NL_LOWER = re.compile(r"[\x02\ufffe][ \t]*\n+[ \t]*(?=[a-z])")
_PDFIUM_HYPHEN_NL_KEEP = re.compile(r"[\x02\ufffe][ \t]*\n+[ \t]*(?=[0-9A-Z])")


_URL_START = re.compile(r"(?:https?://|www\.)", re.I)
_CONT_CHARS = "/-_=&?#%"
_CONT_TOKEN = re.compile(r"[A-Za-z0-9/_\-.%~#?=&:@+,;()]+")


def _join_wrapped_urls(text: str) -> str:
    """Re-join a URL that the producer wrapped.  Only on strong evidence: the line's last token is a URL and
    either it ends in / - _ = & ? # %  and the next line's first token looks like a path fragment (has a digit or
    one of / - _ = . &), or the next line's first token starts with one of those characters.  A URL broken in the
    middle of a segment with no punctuation cannot be recognised and is left alone."""
    if "http" not in text and "www." not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        while i + 1 < len(lines):
            parts = cur.split()
            nxt_parts = lines[i + 1].split()
            if not parts or not nxt_parts or not _URL_START.match(parts[-1]):
                break
            tok, first = parts[-1], nxt_parts[0]
            body = first.rstrip(".,;)")
            starts_cont = first[0] in _CONT_CHARS
            ends_open = tok[-1] in _CONT_CHARS and any(c.isdigit() or c in "/-_=.&" for c in body)
            if (starts_cont or ends_open) and _CONT_TOKEN.fullmatch(body or first):
                cur = cur.rstrip() + lines[i + 1].lstrip()
                i += 1
            else:
                break
        out.append(cur)
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
    text = _SPLIT_WORD.sub(r"\1\2", text)
    text = _KEEP_HYPHEN.sub(r"\1-", text)
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


def _normalise(line: str) -> str:
    return _DIGITS.sub("#", _WS.sub(" ", line.strip()))


def _letter_count(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


def _is_boilerplate(raw: str, key: str) -> bool:
    return bool(_URL.search(raw) or _PAGE_LIKE.match(key) and "#" in key and not _NUM_ONLY.match(key) or _DATE_LIKE.match(key))


def _edge_indices(lines: list[str], k: int) -> set[int]:
    nonblank = [i for i, line in enumerate(lines) if line.strip()]
    return set(nonblank[:k]) | set(nonblank[-k:]) if nonblank else set()


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
    """
    n_text_pages = sum(1 for p in pages if p and p.strip())
    if n_text_pages < boilerplate_min_pages:
        return (list(pages), {}) if return_report else list(pages)

    split = [p.split("\n") for p in pages]
    zones = [_edge_indices(lines, edge_lines) for lines in split]

    pages_with: dict[str, set[int]] = defaultdict(set)
    sample: dict[str, str] = {}
    page_number_candidates: list[tuple[int, int, int]] = []     # (page index, line index, value)
    for pi, (lines, zone) in enumerate(zip(split, zones, strict=True)):
        for li in zone:
            raw = lines[li]
            key = _normalise(raw)
            if not key:
                continue
            if _NUM_ONLY.match(key):
                # a bare number is judged below, on its own rule (it must climb with the page index)
                m = _DIGITS.search(raw)
                if m:
                    page_number_candidates.append((pi, li, int(m.group())))
                continue
            pages_with[key].add(pi)
            sample.setdefault(key, raw)

    running: set[str] = set()
    for key, pset in pages_with.items():
        raw = sample[key]
        count = len(pset)
        if count < min_count:
            continue
        if protect_citations and _CITATION_LIKE.search(raw):
            continue
        if veto is not None and veto(raw):
            continue
        if protect_short and _letter_count(key) < 3 and not _is_boilerplate(raw, key):
            continue                                       # "Id.", "Ex. #", "Tr." and friends
        if _is_boilerplate(raw, key):
            if n_text_pages >= boilerplate_min_pages and count >= max(min_count, math.ceil(boilerplate_fraction * n_text_pages)):
                running.add(key)
        elif n_text_pages >= min_pages and count >= max(min_count, math.ceil(min_fraction * n_text_pages)):
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
            if li in zone:
                key = _normalise(raw)
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


def _build_lines(tp, whole: str, page_w: float, page_h: float):
    lines: list[dict] = []
    cur = None
    for i, ch in enumerate(whole):
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


def _page_text(page, tp, state):
    whole_raw = tp.get_text_range()
    plain = _plain(tp)
    if len(whole_raw) != tp.count_chars() or not whole_raw.strip():
        return plain
    page_w, page_h = page.get_size()
    try:
        lines = _build_lines(tp, whole_raw, page_w, page_h)
        before = sum(len(_squash(L["text"])) for L in lines)
        lines = _drop_pleading_numbers(lines, page_w)
    except Exception:
        return plain
    n_plain = len(_squash(plain))
    if not lines or before < 0.97 * n_plain or before > 1.03 * n_plain:
        return plain
    _mark_footnotes(lines, page_h, state)
    return "\n".join(L["text"] for L in lines)


# ===========================================================================================
# Reader: page cap, pdfium (+ layout) as primary, pdfminer.six as fallback, repair, strip.
# ===========================================================================================

MAX_FALLBACK_PAGES = MAX_PDF_FALLBACK_PAGES

# pdfium is not thread-safe by contract.  Taking one lock around every use is both safe and, measured,
# 4.5x faster than letting 8 threads contend (14.6 s vs 67 s for 200 parses).
_PDFIUM_LOCK = threading.Lock()

# How long one upload will wait for another to finish being read. A read is capped at
# PDF_TIME_BUDGET_S, so a wait this long means either a queue of large files or a bug that left
# the lock held. Either way the person gets "busy, try again" instead of a request that never
# answers.
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
    substitute: it reports 0 pages for PDFs that keep their page objects in compressed object streams."""
    with _pdfium_session():
        pdf = _open(content)
        try:
            return len(pdf)
        finally:
            pdf.close()


def iter_pdf_pages(content: bytes, stats: dict | None = None, deadline: float | None = None) -> Iterator[str]:
    """Generator over the RAW text of each page (pdfium + layout).  Memory is one page at a time.

    A page that fails to load yields "" and is counted in stats["failed_pages"]; the document goes on.
    """
    stats = stats if stats is not None else {}
    stats.setdefault("failed_pages", 0)
    with _pdfium_session():
        pdf = _open(content)
        state: dict = {}
        try:
            for i in range(len(pdf)):
                if deadline is not None and time.monotonic() > deadline:
                    raise PdfReadError("Reading this PDF took too long. Try a shorter file.")
                try:
                    page = pdf[i]
                    tp = page.get_textpage()
                    try:
                        yield _page_text(page, tp, state)
                    finally:
                        tp.close()
                        page.close()
                except PdfReadError:
                    raise
                except GeneratorExit:
                    raise
                except Exception:
                    stats["failed_pages"] += 1
                    yield ""
        finally:
            pdf.close()


# ---- garbled-text detection and the pdfminer fallback ------------------------------------------------
_STOP = frozenset("the of and to in a is that for it as was with be by on not this are or from at which but have an had they their were has been if more when will would who so no".split())
_WORD = re.compile(r"[A-Za-z']+")


def _quality(text: str) -> tuple[float, float, bool]:
    words = _WORD.findall(text)
    stop = sum(1 for w in words if w.lower() in _STOP) / max(1, len(words))
    ctrl = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t") / max(1, len(text))
    return stop, ctrl, "(cid:" in text


def _garble_evidence(text: str) -> str | None:
    """How sure we are that a page's text is corrupt: "strong", "weak" or None.

    Strong evidence is control characters or "(cid:N)" in the text: a font with no text map
    makes a reader emit codes instead of letters, and real text never contains either. Weak
    evidence is a very low share of ordinary words ("the", "of", "and"). Normal prose has
    25-40%, but a table of authorities, a works-cited list or a page of footnotes that is all
    citations can sit below 5% and be perfectly good text. So a weak signal only earns a second
    opinion (which is used only if it is clearly better) and is never grounds to reject a file.
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


def _second_opinion(content: bytes, index: int, first: str) -> str:
    try:
        for alt in _pdfminer_pages(content, [index]):
            alt = repair_text(alt)
            s1, c1, id1 = _quality(first)
            s2, c2, id2 = _quality(alt)
            better = (s2 >= s1 + 0.10 and c2 <= c1) or (c1 > 0.01 and c2 < c1 / 2 and not id2)
            return alt if better else first
    except Exception:
        pass
    return first


def read_pdf(content: bytes, *, max_pages: int | None = None, max_chars: int | None = None,
             time_budget: float | None = None) -> PdfResult:
    """Read a PDF into one string.  Raises PdfReadError / PdfTooLongError with a message fit to show the user."""
    max_pages = MAX_PDF_PAGES if max_pages is None else max_pages
    max_chars = MAX_TEXT_CHARS if max_chars is None else max_chars
    deadline = time.monotonic() + (PDF_TIME_BUDGET_S if time_budget is None else time_budget)
    warnings: list[str] = []
    engine = "pdfium"
    still_garbled = 0

    try:
        n = page_count(content)
    except PdfReadError as first_error:
        # pdfium refused the file.  A password is final, and so is "busy" (that says nothing about
        # the file); anything else gets one try with pdfminer.
        if isinstance(first_error, PdfBusyError) or "password" in str(first_error).lower():
            raise
        pages = []
        total = 0
        try:
            for raw in _pdfminer_pages(content):
                # Same ceilings as the main path: this reader is about ten times slower, so it
                # is the one that could otherwise run on and on over a large damaged file.
                if len(pages) >= max_pages:
                    raise PdfTooLongError(_too_long(len(pages) + 1, max_pages))
                if time.monotonic() > deadline:
                    raise PdfReadError("Reading this PDF took too long. Try a shorter file.")
                text = repair_text(raw)
                total += len(text)
                if total > max_chars:
                    raise PdfTooLongError(_too_much_text(max_chars))
                pages.append(text)
        except PdfReadError:
            raise
        except Exception:
            raise first_error from None
        if not pages:
            # Neither reader found a page: there is nothing to read, and "damaged" is the
            # honest description of a file with a page tree that holds no pages.
            raise first_error
        engine = "pdfminer"
        n = len(pages)
    else:
        if n == 0:
            raise PdfReadError("This PDF has no pages.")
        if n > max_pages:
            raise PdfTooLongError(_too_long(n, max_pages))
        pages = []
        stats: dict = {}
        total = 0
        fallbacks = 0
        # The generator holds the PDF reader's lock while it is open. A for-loop that is left
        # by an exception does not close it: the traceback keeps the generator alive, and with
        # it the lock, until the exception is garbage collected. Close it explicitly so that a
        # limit being hit never leaves the next upload waiting.
        reader = iter_pdf_pages(content, stats, deadline)
        try:
            for i, raw in enumerate(reader):
                text = repair_text(raw)           # garbled-ness is judged on the RAW text; repair drops control characters
                evidence = _garble_evidence(raw)
                if evidence:
                    replaced = False
                    if fallbacks < MAX_FALLBACK_PAGES:
                        fallbacks += 1
                        alt = _second_opinion(content, i, raw)
                        if alt is not raw:
                            text, replaced, engine = alt, True, "pdfium+pdfminer"
                    # Only hard evidence counts toward rejecting the file. A page that merely
                    # has few ordinary words has been given its second opinion and is kept.
                    if evidence == "strong" and (not replaced or _looks_garbled(text)):
                        still_garbled += 1
                total += len(text)
                if total > max_chars:
                    raise PdfTooLongError(_too_much_text(max_chars))
                pages.append(text)
        finally:
            reader.close()
        if stats.get("failed_pages"):
            warnings.append(f"{stats['failed_pages']} page(s) of this PDF could not be read and were skipped.")

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

    pages = strip_running_lines(pages)
    text = "\n\n".join(p for p in pages if p.strip())
    return PdfResult(text, len(pages), warnings, engine)


def _too_much_text(limit: int) -> str:
    return (
        f"This PDF holds more text than the {limit:,}-character limit. "
        "Split it into parts and upload each part."
    )


def _too_long(n: int, limit: int) -> str:
    return (f"This PDF has {n} pages, which is over the {limit}-page limit. "
            f"Split it into parts of {limit} pages or fewer and upload each part.")
