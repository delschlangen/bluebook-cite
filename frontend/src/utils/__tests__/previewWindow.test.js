import { describe, expect, it } from 'vitest';
import {
  WINDOW,
  buildHighlights,
  buildWindow,
  firstWindowStart,
  snapToWhitespace,
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
