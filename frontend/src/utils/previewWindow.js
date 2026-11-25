// The document preview shows one window of the text at a time. Putting the whole document in the
// DOM with one <span> per highlight is tens of thousands of nodes for a long text, which a phone
// cannot scroll. This is the arithmetic for choosing a window and marking what is in it.
//
// The rule the rest of this file serves: walking Next from the top, or Previous from the bottom,
// shows every character exactly once. So a window's end IS the next window's start, with no
// second snapping that could move one of them, and Previous replays the windows already shown
// instead of computing a different one.

export const WINDOW = 20000;

// How far a window edge may move to land on a word boundary. A token longer than this (a row
// of underscores, a dot leader, a long URL) is cut where it falls instead.
export const SNAP_LIMIT = 200;

/** The one definition of "a place a window may break", used in both directions. */
export function isWhitespace(ch) {
  return ch !== undefined && /\s/.test(ch);
}

const isHighSurrogate = (ch) => ch !== undefined && ch >= '\ud800' && ch <= '\udbff';
const isLowSurrogate = (ch) => ch !== undefined && ch >= '\udc00' && ch <= '\udfff';

/** True when `index` falls between the two halves of a surrogate pair (an emoji, say). */
function splitsPair(text, index) {
  return index > 0 && index < text.length && isHighSurrogate(text[index - 1]) && isLowSurrogate(text[index]);
}

/** Move off the middle of a surrogate pair: forward keeps the pair with the text before it. */
function alignToCodePoint(text, index, forward) {
  if (!splitsPair(text, index)) return index;
  return forward ? index + 1 : index - 1;
}

/**
 * Move `index` to the nearest word boundary so a window does not begin or end mid-word.
 * `forward` looks ahead, otherwise back, for at most SNAP_LIMIT characters. With no boundary in
 * reach it stays where it is, moved only as far as needed to keep an emoji whole.
 */
export function snapToWhitespace(text, index, forward) {
  if (!Number.isFinite(index) || index <= 0) return 0;
  if (index >= text.length) return text.length;
  // Already on a boundary: stay, or the word at the seam is shown twice.
  if (isWhitespace(text[index]) || isWhitespace(text[index - 1])) return index;
  if (forward) {
    const stop = Math.min(text.length, index + SNAP_LIMIT);
    for (let i = index; i < stop; i += 1) {
      if (isWhitespace(text[i])) return i;
    }
    return alignToCodePoint(text, index, true);
  }
  const stop = Math.max(0, index - SNAP_LIMIT);
  for (let i = index - 1; i >= stop; i -= 1) {
    if (isWhitespace(text[i])) return i + 1;
  }
  return alignToCodePoint(text, index, false);
}

const SURROGATES = /[\ud800-\udfff]/;
// What a text with no surrogate in it needs: nothing. One shared function, so no table is built.
const SAME_INDEX = (index) => index;

/**
 * The server counts positions in code points (Python indexes a string by them); this page slices
 * UTF-16 units, in which an emoji, a rare CJK character or a mathematical italic letter is two.
 * Used as they came, every such character before a citation moved its highlight one character
 * to the left. Returns a function that turns a code-point index into a UTF-16 index, built in one
 * pass over the text; 0 stays 0, the index just past the last character is `text.length`, and
 * anything beyond is clamped to it. A text with no surrogates needs no conversion at all.
 */
export function codePointIndexer(text) {
  if (!text || !SURROGATES.test(text)) return SAME_INDEX;
  // starts[i] is where the i-th code point begins; the one after the last is text.length.
  const starts = new Uint32Array(text.length + 1);
  let count = 0;
  for (let unit = 0; unit < text.length; count += 1) {
    starts[count] = unit;
    const high = text.charCodeAt(unit);
    const low = unit + 1 < text.length ? text.charCodeAt(unit + 1) : 0;
    unit += high >= 0xd800 && high <= 0xdbff && low >= 0xdc00 && low <= 0xdfff ? 2 : 1;
  }
  starts[count] = text.length;
  return (index) => {
    if (index <= 0) return 0;
    if (index >= count) return text.length;
    return starts[Math.floor(index)];
  };
}

/**
 * Citations and claims as one list of highlights, in document order. `text` is the text the
 * positions are into; with it, positions counted in code points (the server's) are converted to
 * the UTF-16 indexes the rest of this file slices with. Without it they are used as they are.
 */
export function buildHighlights(citations, unsourcedClaims, text) {
  const list = [];
  const toUnit = codePointIndexer(text);
  const add = (start, end, rest) => {
    // A position the server left out would be NaN after the sort and break its order.
    if (Number.isFinite(start) && Number.isFinite(end)) list.push({ start: toUnit(start), end: toUnit(end), ...rest });
  };
  (citations || []).forEach((c) =>
    add(c.position_start, c.position_end, { type: 'citation', status: c.status })
  );
  (unsourcedClaims || []).forEach((c) => add(c.position_start, c.position_end, { type: 'unsourced' }));
  list.sort((a, b) => a.start - b.start);
  return list;
}

/**
 * Where the first window should open. A Word file keeps its citations in footnotes at the end,
 * so offset 0 is body text with nothing highlighted; open at the first highlight instead.
 */
export function firstWindowStart(highlights) {
  return highlights.length ? Math.max(0, highlights[0].start - 500) : 0;
}

/**
 * The text between `start` and `end` split into plain and highlighted segments. Joined, the
 * segments are exactly text.slice(start, end). A highlight with no length, one that ends before
 * it starts, or one with a missing position marks nothing and repeats nothing.
 */
export function segmentsFor(text, highlights, start, end) {
  const segments = [];
  let lastEnd = start;
  for (const h of highlights) {
    if (!Number.isFinite(h.start) || !Number.isFinite(h.end)) continue;
    if (h.start >= end) break; // sorted, so nothing further is inside it
    const hs = Math.max(h.start, lastEnd);
    const he = Math.min(h.end, end);
    // Empty, inverted, entirely before the window, or already covered by an earlier highlight.
    if (he <= hs) continue;
    if (hs > lastEnd) segments.push({ text: text.slice(lastEnd, hs), type: 'normal' });
    segments.push({ text: text.slice(hs, he), type: h.type, status: h.status });
    lastEnd = he;
  }
  if (lastEnd < end) segments.push({ text: text.slice(lastEnd, end), type: 'normal' });
  return segments;
}

/** The window that begins exactly at `start` (only moved off the middle of an emoji). */
export function windowAt(text, start, size = WINDOW) {
  const from = alignToCodePoint(text, Math.max(0, Math.min(Number(start) || 0, text.length)), false);
  const end = snapToWhitespace(text, Math.min(text.length, from + size), true);
  return { start: from, end };
}

/**
 * The window beginning at `from`: its start and end, and its text split into plain and
 * highlighted segments. The segments, joined, are exactly text[start:end].
 */
export function buildWindow(text, highlights, from, size = WINDOW) {
  const { start, end } = windowAt(text, from, size);
  return { segments: segmentsFor(text, highlights, start, end), start, end };
}

// --- Position: the window being shown, and the windows already shown before it ---------------
//
// A position is { start, end, back }, `back` being the windows left behind by Next, newest last.

/** The window the preview opens on: just before the first highlight, on a word boundary. */
export function openingPosition(text, highlights, size = WINDOW) {
  const start = snapToWhitespace(text, firstWindowStart(highlights), false);
  return { ...windowAt(text, start, size), back: [] };
}

export const hasNext = (text, position) => position.end < text.length;
export const hasPrevious = (position) => position.start > 0;

/** The window that starts exactly where this one ends. */
export function nextPosition(text, position, size = WINDOW) {
  if (!hasNext(text, position)) return position;
  const { start, end } = windowAt(text, position.end, size);
  return { start, end, back: [...position.back, { start: position.start, end: position.end }] };
}

/**
 * The window shown before this one. When Next brought us here, that is the very window that was
 * left, so seams match. When the preview opened part-way through, there is nothing to replay:
 * build one that ends exactly where this one starts.
 */
export function previousPosition(text, position, size = WINDOW) {
  if (!hasPrevious(position)) return position;
  if (position.back.length) {
    const back = position.back.slice(0, -1);
    const { start, end } = position.back[position.back.length - 1];
    return { start, end, back };
  }
  const start = snapToWhitespace(text, Math.max(0, position.start - size), false);
  return { start, end: position.start, back: [] };
}
