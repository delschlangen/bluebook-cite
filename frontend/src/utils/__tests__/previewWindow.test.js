import { describe, expect, it } from 'vitest';
import {
  SNAP_LIMIT,
  WINDOW,
  buildHighlights,
  buildWindow,
  firstWindowStart,
  hasNext,
  hasPrevious,
  nextPosition,
  openingPosition,
  previousPosition,
  segmentsFor,
  snapToWhitespace,
  windowAt,
} from '../previewWindow';

const words = (n) => Array.from({ length: n }, (_, i) => `word${i}`).join(' ');

describe('buildWindow', () => {
  const text = words(20000); // about 140,000 characters

  it('shows exactly the text between its start and end, joined from its segments', () => {
    const highlights = [
      { start: 5000, end: 5040, type: 'citation', status: 'complete' },
      { start: 9000, end: 9100, type: 'unsourced' },
    ];
    const { segments, start, end } = buildWindow(text, highlights, 4000);
    expect(segments.map((s) => s.text).join('')).toBe(text.slice(start, end));
  });

  it('never shows more than a window, give or take the word it snaps to', () => {
    const { start, end } = buildWindow(text, [], 50000);
    expect(end - start).toBeLessThan(WINDOW + 250);
    expect(end - start).toBeGreaterThan(WINDOW - 250);
  });

  it('marks a highlight inside the window and leaves the rest plain', () => {
    const highlights = [{ start: 5000, end: 5040, type: 'citation', status: 'complete' }];
    const { segments } = buildWindow(text, highlights, 4000);
    const marked = segments.filter((s) => s.type === 'citation');
    expect(marked).toHaveLength(1);
    expect(marked[0].text).toBe(text.slice(5000, 5040));
    expect(marked[0].status).toBe('complete');
  });

  it('leaves out highlights that are entirely outside the window', () => {
    const highlights = [
      { start: 10, end: 50, type: 'citation', status: 'complete' },
      { start: 120000, end: 120050, type: 'citation', status: 'complete' },
    ];
    const { segments } = buildWindow(text, highlights, 60000);
    expect(segments.every((s) => s.type === 'normal')).toBe(true);
  });

  it('clips a highlight that starts before the window to the part inside it', () => {
    const { start } = buildWindow(text, [], 40000);
    const highlights = [{ start: start - 30, end: start + 30, type: 'citation', status: 'complete' }];
    const { segments } = buildWindow(text, highlights, 40000);
    expect(segments[0].type).toBe('citation');
    expect(segments[0].text).toBe(text.slice(start, start + 30));
  });

  it('clips a highlight that runs past the end of the window', () => {
    const { end } = buildWindow(text, [], 40000);
    const highlights = [{ start: end - 30, end: end + 30, type: 'citation', status: 'complete' }];
    const { segments, end: windowEnd } = buildWindow(text, highlights, 40000);
    const last = segments[segments.length - 1];
    expect(last.type).toBe('citation');
    expect(last.text).toBe(text.slice(end - 30, windowEnd));
  });

  it('copes with overlapping highlights without repeating text', () => {
    const highlights = [
      { start: 5000, end: 5100, type: 'citation', status: 'complete' },
      { start: 5050, end: 5200, type: 'unsourced' },
    ];
    const { segments, start, end } = buildWindow(text, highlights, 4000);
    expect(segments.map((s) => s.text).join('')).toBe(text.slice(start, end));
  });

  it('walks the whole document, window by window, without a gap or a repeat', () => {
    let from = 0;
    let rebuilt = '';
    for (let guard = 0; guard < 100; guard += 1) {
      const { segments, end } = buildWindow(text, [], from);
      rebuilt += segments.map((s) => s.text).join('');
      if (end >= text.length) break;
      from = end;
    }
    expect(rebuilt).toBe(text);
  });

  it('clamps a start beyond the end of the text', () => {
    const { start, end } = buildWindow('short text', [], 999);
    expect(start).toBeLessThanOrEqual('short text'.length);
    expect(end).toBe('short text'.length);
  });

  it('handles a text shorter than a window', () => {
    const short = 'A short document with a citation in it.';
    const { segments, start, end } = buildWindow(short, [], 0);
    expect([start, end]).toEqual([0, short.length]);
    expect(segments.map((s) => s.text).join('')).toBe(short);
  });
});

describe('snapToWhitespace', () => {
  it('does not start or end a window in the middle of a word', () => {
    const text = 'alpha bravo charlie delta echo';
    const forward = snapToWhitespace(text, 8, true); // inside "bravo"
    expect(text[forward]).toBe(' ');
    const back = snapToWhitespace(text, 8, false);
    expect(text[back - 1] === ' ' || back === 0).toBe(true);
  });

  it('stays at the ends of the text', () => {
    expect(snapToWhitespace('abc', 0, false)).toBe(0);
    expect(snapToWhitespace('abc', 3, true)).toBe(3);
  });
});

describe('buildHighlights and firstWindowStart', () => {
  it('merges citations and claims in document order', () => {
    const list = buildHighlights(
      [{ position_start: 50, position_end: 60, status: 'complete' }],
      [{ position_start: 10, position_end: 20 }]
    );
    expect(list.map((h) => h.type)).toEqual(['unsourced', 'citation']);
  });

  it('opens at the first highlight, not at the top, so a footnoted document shows something', () => {
    const list = buildHighlights([{ position_start: 90000, position_end: 90040, status: 'complete' }], []);
    expect(firstWindowStart(list)).toBe(89500);
  });

  it('opens at the top when there is nothing to highlight, or the first one is near it', () => {
    expect(firstWindowStart([])).toBe(0);
    expect(firstWindowStart([{ start: 100, end: 140 }])).toBe(0);
  });

  it('tolerates missing lists', () => {
    expect(buildHighlights(undefined, undefined)).toEqual([]);
  });
});

// --- Every part of the text is shown exactly once ------------------------------------------------

/** A small deterministic random number generator, so a failing text can be reproduced from its seed. */
function mulberry32(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const LONG_TOKENS = [
  '_'.repeat(300), // a signature line
  '.'.repeat(250), // a table-of-contents leader
  `https://example.com/${'x'.repeat(300)}`, // a long URL
  '\u{1F600}'.repeat(150), // 300 UTF-16 units of emoji with no space in them
  '\u{1D4B3}'.repeat(120),
  '\u5B57'.repeat(260), // a run of CJK with no space in it
];
const SEPARATORS = [' ', ' ', ' ', ' ', '\n', '\t', '\u00a0', '\u3000', '\r\n', '  '];

function randomText(rand, targetLength) {
  const parts = [];
  let length = 0;
  while (length < targetLength) {
    const roll = rand();
    let piece;
    if (roll < 0.06) piece = LONG_TOKENS[Math.floor(rand() * LONG_TOKENS.length)];
    else if (roll < 0.12) piece = '\u{1F469}\u200D\u{1F469}\u200D\u{1F467}'; // a family emoji joined with ZWJs
    else piece = 'abcdefghijklmnopqrstuvwxyz'.slice(0, 1 + Math.floor(rand() * 14));
    parts.push(piece, SEPARATORS[Math.floor(rand() * SEPARATORS.length)]);
    length += piece.length + 1;
  }
  return parts.join('');
}

const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

/** Every window from the top, by Next, as the page would show them. */
function walkNext(text, size) {
  let position = { ...windowAt(text, 0, size), back: [] };
  const windows = [position];
  for (let guard = 0; guard < 5000 && hasNext(text, position); guard += 1) {
    position = nextPosition(text, position, size);
    windows.push(position);
  }
  return windows;
}

describe('walking Next shows every character exactly once', () => {
  it('for random texts with emoji, odd spaces and tokens longer than the snap distance', () => {
    for (let seed = 1; seed <= 250; seed += 1) {
      const rand = mulberry32(seed);
      const text = randomText(rand, Math.floor(rand() * 6000));
      const size = 20 + Math.floor(rand() * 380);
      const windows = walkNext(text, size);

      expect(windows.map((w) => text.slice(w.start, w.end)).join(''), `seed ${seed}`).toBe(text);
      windows.forEach((w, i) => {
        if (i > 0) expect(w.start, `seed ${seed} seam ${i}`).toBe(windows[i - 1].end);
        if (text.length) expect(w.end, `seed ${seed}`).toBeGreaterThan(w.start);
        expect(w.end - w.start, `seed ${seed}`).toBeLessThanOrEqual(size + SNAP_LIMIT + 1);
        expect(LONE_SURROGATE.test(text.slice(w.start, w.end)), `seed ${seed} window ${i}`).toBe(false);
      });
    }
  });

  it('with a 300-underscore signature line across the seam, which used to be shown twice', () => {
    const text = `${'word '.repeat(3996)}${'_'.repeat(300)} signed`;
    const windows = walkNext(text, WINDOW);
    expect(windows.length).toBeGreaterThan(1);
    expect(windows.map((w) => text.slice(w.start, w.end)).join('')).toBe(text);
  });

  it('with 250-dot leaders and 300-character URLs on every line', () => {
    const lines = [];
    for (let i = 0; i < 120; i += 1) {
      lines.push(`Section ${i} ${'.'.repeat(250)} ${i}`, `https://example.org/${'q'.repeat(300)}/${i}`);
    }
    const text = lines.join('\n');
    const windows = walkNext(text, WINDOW);
    expect(windows.map((w) => text.slice(w.start, w.end)).join('')).toBe(text);
  });

  it('never cuts an emoji in two at the 20,000-character seam', () => {
    const text = `${'a'.repeat(19999)}${'\u{1F600}'.repeat(300)}`;
    const windows = walkNext(text, WINDOW);
    expect(windows.length).toBeGreaterThan(1);
    windows.forEach((w) => expect(LONE_SURROGATE.test(text.slice(w.start, w.end))).toBe(false));
    expect(windows.map((w) => text.slice(w.start, w.end)).join('')).toBe(text);
  });
});

describe('walking Previous shows every character exactly once', () => {
  it('replays the windows Next showed, so each ends where the one after it begins', () => {
    for (let seed = 1; seed <= 250; seed += 1) {
      const rand = mulberry32(seed + 1000);
      const text = randomText(rand, 200 + Math.floor(rand() * 6000));
      const size = 20 + Math.floor(rand() * 380);
      const forward = walkNext(text, size);

      let position = forward[forward.length - 1];
      const backward = [position];
      for (let guard = 0; guard < 5000 && hasPrevious(position); guard += 1) {
        const before = position;
        position = previousPosition(text, position, size);
        expect(position.end, `seed ${seed}`).toBe(before.start);
        backward.push(position);
      }

      expect(backward.map((w) => [w.start, w.end])).toEqual(
        forward.map((w) => [w.start, w.end]).reverse()
      );
      expect(backward.map((w) => text.slice(w.start, w.end)).reverse().join(''), `seed ${seed}`).toBe(text);
    }
  });

  it('from a window the preview opened on part-way through, back to the top with no gap or repeat', () => {
    for (let seed = 1; seed <= 250; seed += 1) {
      const rand = mulberry32(seed + 5000);
      const text = randomText(rand, 1000 + Math.floor(rand() * 8000));
      const size = 20 + Math.floor(rand() * 380);
      const at = Math.floor(rand() * text.length);
      const highlights = [{ start: at, end: Math.min(text.length, at + 10), type: 'citation' }];
      const opening = openingPosition(text, highlights, size);

      const before = [];
      let position = opening;
      for (let guard = 0; guard < 5000 && hasPrevious(position); guard += 1) {
        const next = previousPosition(text, position, size);
        expect(next.end, `seed ${seed}`).toBe(position.start);
        before.push(next);
        position = next;
      }
      expect(position.start).toBe(0);

      const after = [];
      position = opening;
      for (let guard = 0; guard < 5000 && hasNext(text, position); guard += 1) {
        position = nextPosition(text, position, size);
        after.push(position);
      }

      const all = [...before.reverse(), opening, ...after];
      expect(all.map((w) => text.slice(w.start, w.end)).join(''), `seed ${seed}`).toBe(text);
      all.forEach((w) => expect(LONE_SURROGATE.test(text.slice(w.start, w.end)), `seed ${seed}`).toBe(false));
    }
  });

  it('Next after Previous comes back to the window that was left', () => {
    const text = randomText(mulberry32(7), 5000);
    const forward = walkNext(text, 300);
    const middle = forward[3];
    const back = previousPosition(text, middle, 300);
    const again = nextPosition(text, back, 300);
    expect([again.start, again.end]).toEqual([middle.start, middle.end]);
  });

  it('does nothing at the very top or the very bottom', () => {
    const text = 'a short text';
    const only = openingPosition(text, [], WINDOW);
    expect(hasPrevious(only)).toBe(false);
    expect(hasNext(text, only)).toBe(false);
    expect(previousPosition(text, only)).toBe(only);
    expect(nextPosition(text, only)).toBe(only);
  });
});

describe('one idea of whitespace, in both directions', () => {
  it('snaps back to a word start after a tab, a no-break space or a full-width space', () => {
    expect(snapToWhitespace('aaaa\tbbbb', 7, false)).toBe(5);
    expect(snapToWhitespace('aaaa\u00a0bbbb', 7, false)).toBe(5);
    expect(snapToWhitespace('aaaa\u3000bbbb', 7, false)).toBe(5);
  });

  it('snaps forward to the same kinds of space', () => {
    expect(snapToWhitespace('aaaa\tbbbb', 2, true)).toBe(4);
    expect(snapToWhitespace('aaaa\u00a0bbbb', 2, true)).toBe(4);
  });

  it('gives up after the snap distance and stays put, moving only off the middle of an emoji', () => {
    const token = 'x'.repeat(SNAP_LIMIT * 3);
    expect(snapToWhitespace(token, 400, true)).toBe(400);
    expect(snapToWhitespace(token, 400, false)).toBe(400);
    const emoji = '\u{1F600}'.repeat(400);
    expect(snapToWhitespace(emoji, 401, true)).toBe(402);
    expect(snapToWhitespace(emoji, 401, false)).toBe(400);
  });

  it('is exact at the edges and tolerates a position that is not a number', () => {
    expect(snapToWhitespace('abc def', NaN, true)).toBe(0);
    expect(snapToWhitespace('abc def', undefined, false)).toBe(0);
  });
});

describe('highlights that mark nothing repeat nothing', () => {
  const text = 'abcdefgh';
  const join = (highlights, start = 0, end = text.length) =>
    segmentsFor(text, highlights, start, end).map((s) => s.text).join('');

  it('a highlight with no length', () => {
    expect(join([{ start: 3, end: 3, type: 'citation' }])).toBe('abcdefgh');
  });

  it('a highlight that ends before it starts', () => {
    expect(join([{ start: 5, end: 2, type: 'citation' }])).toBe('abcdefgh');
  });

  it('a highlight with a missing or non-finite position', () => {
    expect(join([{ start: 2, end: undefined, type: 'citation' }])).toBe('abcdefgh');
    expect(join([{ start: NaN, end: 4, type: 'citation' }])).toBe('abcdefgh');
    expect(join([{ start: 1, end: Infinity, type: 'citation' }])).toBe('abcdefgh');
  });

  it('is still marked correctly next to the odd ones', () => {
    const segments = segmentsFor(text, [
      { start: 1, end: 1, type: 'unsourced' },
      { start: 2, end: 4, type: 'citation', status: 'complete' },
      { start: 6, end: undefined, type: 'citation' },
    ], 0, text.length);
    expect(segments.map((s) => [s.type, s.text])).toEqual([
      ['normal', 'ab'],
      ['citation', 'cd'],
      ['normal', 'efgh'],
    ]);
  });

  it('buildWindow keeps its text whole for 3,000 random highlights, odd ones included', () => {
    const rand = mulberry32(99);
    const body = randomText(rand, 4000);
    const odd = [0, NaN, undefined, null, Infinity, -5, 3, 2.5];
    for (let round = 0; round < 60; round += 1) {
      const highlights = Array.from({ length: 50 }, () => {
        const pick = () => (rand() < 0.12 ? odd[Math.floor(rand() * odd.length)] : Math.floor(rand() * (body.length + 200)));
        return { start: pick(), end: pick(), type: rand() < 0.5 ? 'citation' : 'unsourced', status: 'complete' };
      }).filter((h) => Number.isFinite(h.start)).sort((a, b) => a.start - b.start);
      const { segments, start, end } = buildWindow(body, highlights, Math.floor(rand() * body.length), 300);
      expect(segments.map((s) => s.text).join(''), `round ${round}`).toBe(body.slice(start, end));
    }
  });

  it('stops looking at highlights once one starts after the window, since they are sorted', () => {
    // A 4,000-citation document has thousands of highlights past any window; each build of a
    // window must not read them all.
    let reads = 0;
    const highlights = Array.from({ length: 10000 }, (_, i) => ({
      get start() { reads += 1; return 1000 + i * 100; },
      get end() { return 1000 + i * 100 + 50; },
      type: 'citation',
    }));
    const body = 'word '.repeat(5000);
    const { end } = windowAt(body, 0, 2000);
    segmentsFor(body, highlights, 0, end);
    expect(reads).toBeLessThan(100);
  });

  it('buildHighlights drops a position the server left out, so the list still sorts', () => {
    const list = buildHighlights(
      [
        { position_start: 50, position_end: 60, status: 'complete' },
        { position_start: undefined, position_end: 9, status: 'complete' },
      ],
      [{ position_start: 10, position_end: null }, { position_start: 20, position_end: 30 }]
    );
    expect(list.map((h) => h.start)).toEqual([20, 50]);
  });

  it('opens at the top when the only highlight has no position', () => {
    const list = buildHighlights([{ position_start: undefined, position_end: undefined }], []);
    expect(firstWindowStart(list)).toBe(0);
  });
});
