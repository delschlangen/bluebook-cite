// The document preview shows one window of the text at a time. Putting the whole document in the
// DOM with one <span> per highlight is tens of thousands of nodes for a long text, which a phone
// cannot scroll. This is the arithmetic for choosing a window and marking what is in it.

export const WINDOW = 20000;

/**
 * Move `index` to the nearest word boundary so a window does not begin or end mid-word.
 * `forward` looks ahead, otherwise back, for at most 200 characters.
 */
export function snapToWhitespace(text, index, forward) {
  if (index <= 0) return 0;
  if (index >= text.length) return text.length;
  if (forward) {
    const ws = text.slice(index, index + 200).search(/\s/);
    return ws === -1 ? index : index + ws;
  }
  // Already on a boundary (the previous window ended here): stay, or the word at the seam is
  // shown twice, once at the end of one window and again at the start of the next.
  if (/\s/.test(text[index]) || /\s/.test(text[index - 1])) return index;
  const slice = text.slice(Math.max(0, index - 200), index);
  const ws = Math.max(slice.lastIndexOf(' '), slice.lastIndexOf('\n'));
  return ws === -1 ? index : index - (slice.length - ws - 1);
}

/** Citations and claims as one list of highlights, in document order. */
export function buildHighlights(citations, unsourcedClaims) {
  const list = [];
  (citations || []).forEach((c) =>
    list.push({ start: c.position_start, end: c.position_end, type: 'citation', status: c.status })
  );
  (unsourcedClaims || []).forEach((c) =>
    list.push({ start: c.position_start, end: c.position_end, type: 'unsourced' })
  );
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
 * The window beginning near `from`: its snapped start and end, and the text between them
 * split into plain and highlighted segments. The segments, joined, are exactly text[start:end].
 */
export function buildWindow(text, highlights, from, size = WINDOW) {
  const start = snapToWhitespace(text, Math.min(from, text.length), false);
  const end = snapToWhitespace(text, Math.min(text.length, start + size), true);
  const segments = [];
  let lastEnd = start;
  for (const h of highlights) {
    if (h.end <= start) continue; // entirely before the window
    if (h.start >= end) break; // sorted, so nothing further is inside it
    const hs = Math.max(h.start, lastEnd);
    const he = Math.min(h.end, end);
    if (hs > lastEnd) segments.push({ text: text.slice(lastEnd, hs), type: 'normal' });
    if (he > hs) {
      segments.push({ text: text.slice(hs, he), type: h.type, status: h.status });
      lastEnd = he;
    }
  }
  if (lastEnd < end) segments.push({ text: text.slice(lastEnd, end), type: 'normal' });
  return { segments, start, end };
}
