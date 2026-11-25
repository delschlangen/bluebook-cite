// @vitest-environment jsdom
// What keeps the page the width of the screen, and readable: text that cannot break a line breaks
// anyway, boxes can shrink, rows wrap, inputs are 16 px, and the colours are strong enough.
// jsdom has no layout, so these are structural; checks_overflow.mjs measures the real thing.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { chooseFile, findResults, renderApp, setup, tab } from './harness';
import { json } from '../test/fakeServer';
import { analysisBody, citation, claim, uploadBody } from '../test/fixtures';
import { ambiguousReply, incompleteReply, resolvedReply } from '../test/repairReplies';
import CitationList from '../components/CitationList';
import DocumentPreview from '../components/DocumentPreview';
import ErrorBoundary from '../components/ErrorBoundary';
import FileUpload from '../components/FileUpload';
import SourceSuggestions from '../components/SourceSuggestions';

afterEach(() => {
  cleanup();
});

const URL150 = `https://example.org/${'a'.repeat(130)}`;
const STR200 = 'x'.repeat(200);
const css = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../index.css'), 'utf8');

/** The elements whose own text holds `token`. */
const holding = (root, token) =>
  [...root.querySelectorAll('*')].filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.includes(token)));
const wraps = (el) => Boolean(el.closest('[class*="overflow-wrap:anywhere"], .wrap-anywhere'));
const expectWrapped = (root, token, where) => {
  const found = holding(root, token);
  expect(found.length, `${where}: "${token.slice(0, 12)}..." is on the page`).toBeGreaterThan(0);
  for (const el of found) expect(wraps(el), `${where}: <${el.tagName.toLowerCase()} class="${el.className}">`).toBe(true);
};
const noNoWrap = (root) => {
  for (const el of root.querySelectorAll('[class*="whitespace-nowrap"]')) expect(el.textContent, 'only a rule number may not break').toMatch(/^Rule [\d.]+$/);
};

function stubMatchMedia(narrow) {
  vi.stubGlobal('matchMedia', (query) => ({
    matches: narrow && query === '(max-width: 1023px)',
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe('text that comes from the document or the server breaks anywhere rather than widen the page', () => {
  const ctx = setup();

  it('on the results: the file name, the warnings, and every part of a card', async () => {
    stubMatchMedia(false);
    ctx.server.on('/api/upload', () => json(uploadBody({ filename: `${STR200}.txt`, warnings: [URL150] })));
    const incomplete = citation(1, { status: 'incomplete', raw_text: URL150, kind_label: `K${STR200}`, missing: ['year'], template: `T ${'t'.repeat(200)}`, type: 'regulation' });
    const complete = citation(2, { raw_text: `R${STR200}` });
    ctx.server.on('/api/analyze', () =>
      json(
        analysisBody({
          citations: [incomplete, complete],
          suggestions: [
            { citation_id: 'c1', suggested_form: `S${'s'.repeat(200)}`, short_form_type: 'full', explanation: `E${'e'.repeat(200)}` },
            { citation_id: 'c2', suggested_form: `U${'u'.repeat(200)}`, short_form_type: `P${'p'.repeat(200)}`, explanation: `Q${'q'.repeat(200)}` },
          ],
        })
      )
    );
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const main = screen.getByRole('main');
    expectWrapped(main, 'xxxxxxxxxx', 'file name');
    expectWrapped(main, URL150, 'warning, and the raw text of a card');
    expectWrapped(main, `K${'x'.repeat(5)}`.slice(0, 1) + 'xxxxx', 'kind label');
    expectWrapped(main, 'tttttttttt', 'template');
    expectWrapped(main, 'ssssssssss', 'suggested form (incomplete)');
    expectWrapped(main, 'eeeeeeeeee', 'explanation');
    expectWrapped(main, 'uuuuuuuuuu', 'suggested form (complete)');
    expectWrapped(main, 'pppppppppp', 'short form type');
    expectWrapped(main, 'qqqqqqqqqq', 'explanation (complete)');
    expectWrapped(main, 'RRRRRRRR'.slice(0, 1) + 'xxxxxxxx', 'raw text');
    noNoWrap(main);
  });

  it('in the editor: the raw text, the suggestion, what was found, what was said', async () => {
    stubMatchMedia(true);
    const c = citation(1, { status: 'complete', raw_text: `R${STR200}` });
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [c], suggestions: [{ citation_id: 'c1', suggested_form: `S${'s'.repeat(200)}`, short_form_type: 'full' }] })));
    ctx.server.on('/api/lookup', () => json({ found: true, source: `Z${'z'.repeat(200)}`, data: { absolute_url: URL150 } }));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    fireEvent.click(window.document.querySelector('[data-citation-id="c1"]'));
    fireEvent.click(screen.getByRole('button', { name: 'Look Up in Database' }));
    await screen.findByText(/^Found in/);
    const dialog = screen.getByRole('dialog');
    expectWrapped(dialog, 'xxxxxxxx', 'raw text in the editor');
    expectWrapped(dialog, 'ssssssssss', 'suggestion in the editor');
    expectWrapped(dialog, 'zzzzzzzzzz', 'source that was searched');
    // A note that names the source.
    ctx.server.on('/api/lookup', () => json({ found: false, source: `N${'n'.repeat(200)}`, error: 'x' }));
    fireEvent.click(screen.getByRole('button', { name: 'Look Up in Database' }));
    await screen.findByTestId('lookup-note');
    expectWrapped(dialog, 'nnnnnnnnnn', 'note that names the source');
  });

  it('on Fix a citation: the shape, the notes, the candidates, the details, the kind', async () => {
    ctx.server.on('/api/repair', () =>
      json(
        ambiguousReply({
          kind_label: `K${STR200}`,
          template: `shape ${'h'.repeat(200)}`,
          notes: [`note ${'n'.repeat(200)}`],
          missing_details: [{ field: 'f', label: `L${'l'.repeat(200)}`, why: `W${'w'.repeat(200)}`, display_rule: { number: '15', title: `D${'d'.repeat(200)}` } }],
          candidates: [{ label: `C${'c'.repeat(200)}`, court: `O${'o'.repeat(200)}`, date: `A${'a'.repeat(200)}`, verify_url: 'https://example.org/1' }],
        })
      )
    );
    renderApp();
    fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Needs your choice');
    const panel = window.document.getElementById('panel-repair');
    for (const token of ['xxxxxxxxxx', 'hhhhhhhhhh', 'nnnnnnnnnn', 'llllllllll', 'wwwwwwwwww', 'dddddddddd', 'cccccccccc', 'oooooooooo']) {
      expectWrapped(panel, token, 'repair result');
    }
    noNoWrap(panel);
  });

  it('on Fix a citation: the formatted citation and the name of the source on the link', async () => {
    ctx.server.on('/api/repair', () => json(resolvedReply({ formatted: `*F*, ${URL150}`, source: `S${'s'.repeat(200)}` })));
    renderApp();
    fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Ready to use');
    const panel = window.document.getElementById('panel-repair');
    expectWrapped(panel, URL150, 'formatted citation');
    expectWrapped(panel, 'ssssssssss', 'source on the link');
  });

  it('the note about the citations that were not formatted, when their names are long', async () => {
    renderApp();
    const longCase = (a, b, n) => `${a.repeat(60)} v. ${b.repeat(60)}, ${n} U.S. ${n} (199${n})`;
    fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: `${longCase('A', 'B', 1)}; ${longCase('C', 'D', 2)}` } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    const note = await screen.findByTestId('partial-note');
    expectWrapped(note.parentElement, 'AAAAAAAAAA', 'the note about the other citations');
    expect(note.textContent).toContain('CCCCCCCCCC');
  });

  it('an error message from the server', async () => {
    ctx.server.on('/api/repair', () => json({ detail: STR200 }, 500));
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    const alert = await screen.findByRole('alert');
    expectWrapped(alert, 'xxxxxxxxxx', 'repair error');
  });

  it('a claim: its text, its type, its search terms and the note above them', () => {
    render(
      <SourceSuggestions
        notice={`N${'n'.repeat(200)}`}
        claims={[{ id: 'k', text: STR200, claim_type: `T${'t'.repeat(200)}`, confidence: 0.5, suggested_search_terms: [`Q${'q'.repeat(200)}`] }]}
      />
    );
    const root = window.document.body;
    for (const token of ['xxxxxxxxxx', 'tttttttttt', 'qqqqqqqqqq', 'nnnnnnnnnn']) expectWrapped(root, token, 'claims');
  });

  it('the upload box: a file name in a note and in an error', () => {
    render(<FileUpload notice={`${STR200}.pdf was ignored`} error={`${STR200}.doc is not supported`} onFiles={() => {}} />);
    expectWrapped(window.document.body, 'xxxxxxxxxx', 'upload note and error');
  });

  it('the preview of the document', () => {
    render(<DocumentPreview text={`A ${STR200} B`} citations={[]} unsourcedClaims={[]} />);
    expectWrapped(window.document.body, 'xxxxxxxxxx', 'preview');
  });

  it('a card does not leave a long kind label or footnote number to widen its row', () => {
    render(<CitationList citations={[citation(1, { kind_label: STR200 })]} shortFormSuggestions={[]} onSelect={() => {}} />);
    expect(window.document.querySelector('[data-card-index] .flex.flex-wrap')).not.toBeNull();
  });
});

describe('boxes that hold such text may shrink, rows wrap, and the page clips what is left', () => {
  const ctx = setup();

  it('the page itself clips sideways overflow as a last defence, without becoming a scroll box', () => {
    renderApp();
    const root = screen.getByRole('banner').parentElement;
    expect(root.className).toContain('overflow-x-clip');
    expect(root.className).not.toMatch(/overflow-x-(hidden|auto|scroll)\b|(^|\s)overflow-hidden/);
  });

  it('the header row wraps, its title may shrink, and the button never wider than the row', async () => {
    renderApp();
    const row = screen.getByRole('heading', { level: 1 }).parentElement.parentElement;
    expect(row.className).toContain('flex-wrap');
    const title = screen.getByRole('heading', { level: 1 }).parentElement;
    expect(title.className).toContain('min-w-0');
    expect(title.className).toContain('basis-[11rem]');
    stubMatchMedia(false);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [citation(1)] })));
    await chooseFile(ctx);
    await findResults();
    const button = screen.getByRole('button', { name: 'Upload New Document' });
    expect(button.className).toContain('max-w-full');
    expect(button.className).not.toContain('max-w-[8.5rem]');
  });

  it('the two modes, and the style choice, wrap when text is enlarged', () => {
    renderApp();
    expect(screen.getByRole('tablist', { name: 'Choose a mode' }).className).toContain('flex-wrap');
    const group = screen.getByRole('radiogroup', { name: 'Citation style' });
    expect(group.className).toContain('flex-wrap');
    expect(group.className).toContain('max-w-full');
  });

  it('a claim’s badges wrap, and so does a citation’s', () => {
    render(<SourceSuggestions claims={[claim(1)]} />);
    expect(window.document.querySelector('[data-claim-index] .flex.flex-wrap')).not.toBeNull();
  });

  it('the editor sheet is as wide as the screen and no wider, and may shrink', async () => {
    stubMatchMedia(true);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [citation(1)] })));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    fireEvent.click(window.document.querySelector('[data-citation-id="c1"]'));
    const dialog = screen.getByRole('dialog');
    for (const name of ['max-w-full', 'min-w-0', 'fixed', 'inset-x-0']) expect(dialog.className, name).toContain(name);
    expect(css).toMatch(/\.editor-sheet\s*\{[^}]*max-width:\s*100%/);
    expect(css).toMatch(/\.editor-sheet\s*\{[^}]*min-width:\s*0/);
    // The editor inside shrinks with it, and so do the fields in its grid.
    expect(within(dialog).getByLabelText('Volume').parentElement.className).toContain('min-w-0');
    expect(within(dialog).getByLabelText('Volume').className).toContain('min-w-0');
  });

  it('a field that is tabbed to is scrolled to below the sticky header of the sheet, not under it', () => {
    expect(css).toMatch(/\.editor-sheet\s*\{[^}]*scroll-padding-top:\s*6rem/);
  });
});

describe('every box a person can type in is 16 px on a phone, so iOS does not zoom the page', () => {
  const ctx = setup();
  const phoneSized = (el) => {
    const tokens = el.className.split(/\s+/);
    return tokens.includes('text-base') && !tokens.some((t) => t === 'text-sm' || t === 'text-xs');
  };
  const allBoxes = (root) =>
    [...root.querySelectorAll('input, textarea, select')].filter((el) => !['file', 'hidden', 'checkbox', 'radio', 'button', 'submit'].includes(el.type));

  it('the citation box on Fix a citation', () => {
    renderApp();
    const boxes = allBoxes(window.document.body);
    expect(boxes.length).toBeGreaterThan(0);
    for (const el of boxes) expect(phoneSized(el), `${el.tagName} #${el.id}: ${el.className}`).toBe(true);
    expect(screen.getByLabelText('Citation to repair').className).toContain('lg:text-sm');
  });

  it.each([
    ['case', { type: 'case' }],
    ['statute', { type: 'statute' }],
    ['regulation', { type: 'regulation' }],
    ['law_review', { type: 'law_review' }],
    ['book', { type: 'book' }],
    ['website', { type: 'website' }],
  ])('every field of the editor for a %s', async (_name, extra) => {
    stubMatchMedia(true);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [citation(1, extra)] })));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    fireEvent.click(window.document.querySelector('[data-citation-id="c1"]'));
    const boxes = allBoxes(screen.getByRole('dialog'));
    expect(boxes.length).toBeGreaterThan(0);
    for (const el of boxes) expect(phoneSized(el), `${el.id}: ${el.className}`).toBe(true);
  });

  it('there is no select or other box anywhere else in the page', async () => {
    stubMatchMedia(false);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [citation(1)], claims: [claim(1)] })));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    for (const name of ['Citations', 'Unsourced Claims', 'Document Preview']) {
      fireEvent.click(tab(name));
      for (const el of allBoxes(window.document.body)) expect(phoneSized(el), `${name}: ${el.className}`).toBe(true);
    }
    expect(window.document.querySelectorAll('select').length).toBe(0);
  });
});

describe('the colours of what is on the page, and the motion', () => {
  const ctx = setup();

  it('the page’s placeholders are the strong grey, not the browser’s', () => {
    expect(css).toMatch(/input::placeholder,\s*textarea::placeholder\s*\{[^}]*color:\s*#6b7280/);
  });

  it('a marked passage in the preview is not drawn as something to click', () => {
    expect(css).not.toMatch(/cursor:\s*pointer/);
    expect(css).not.toMatch(/\.citation-highlight:hover/);
    expect(css).toMatch(/\.citation-highlight,\s*\.unsourced-highlight\s*\{[^}]*color:\s*inherit/);
  });

  it('the stat labels are not faded, and Save is dark enough for white text', async () => {
    stubMatchMedia(true);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [citation(1)] })));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const labels = [...window.document.querySelectorAll('.grid.grid-cols-2 > div > .text-sm')];
    expect(labels.map((el) => el.textContent)).toEqual(['Total Citations', 'Complete', 'Incomplete', 'Needs Review', 'Unsourced Claims']);
    for (const label of labels) expect(label.className, label.textContent).not.toMatch(/opacity/);
    fireEvent.click(window.document.querySelector('[data-citation-id="c1"]'));
    expect(screen.getByRole('button', { name: 'Save Changes' }).className).toContain('bg-green-700');
    expect(screen.getByRole('button', { name: 'Save Changes' }).className).not.toContain('bg-green-600');
  });

  it('the shortcut hint is dark enough to read, and not shown where there is no such key', () => {
    renderApp();
    const hint = screen.getByText('Cmd/Ctrl + Enter');
    expect(hint.className).toContain('text-gray-600');
    expect(hint.className).toContain('hidden');
    expect(hint.className).toContain('sm:inline');
  });

  it('a button that is off is dark grey on light grey, not a washed-out colour', () => {
    renderApp();
    const fix = screen.getByRole('button', { name: 'Fix it' });
    expect(fix.className).toContain('aria-disabled:bg-gray-200');
    expect(fix.className).toContain('aria-disabled:text-gray-700');
    expect(fix.className).not.toContain('opacity-50');
  });

  it('Show and Hide, and "(optional)", in the guide are the darker grey', () => {
    renderApp();
    fireEvent.click(screen.getByRole('button', { name: /Browse every kind/ }));
    const row = window.document.querySelector('#panel-repair section button[aria-expanded]');
    expect(row.lastElementChild.className).toContain('text-gray-600');
    fireEvent.click(row);
    for (const el of window.document.querySelectorAll('#panel-repair [class*="text-gray-400"], #panel-repair [class*="text-gray-500"]')) {
      throw new Error(`faint grey text: <${el.tagName.toLowerCase()} class="${el.className}">`);
    }
  });

  it('the spinners stand still for people who asked for less motion', async () => {
    ctx.server.on('/api/analyze', () => new Promise(() => {}));
    stubMatchMedia(false);
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    const spinners = window.document.querySelectorAll('.animate-spin');
    expect(spinners.length).toBeGreaterThan(0);
    for (const spinner of spinners) expect(spinner.className).toContain('motion-reduce:animate-none');
  });

  it('and the one in the upload box', () => {
    render(<FileUpload uploading={{ file: new File(['x'], 'a.txt'), phase: 'sending' }} onFiles={() => {}} onCancel={() => {}} />);
    for (const spinner of window.document.querySelectorAll('.animate-spin')) expect(spinner.className).toContain('motion-reduce:animate-none');
    expect(window.document.querySelectorAll('.animate-spin').length).toBe(1);
  });
});

describe('the preview of the document is a place a keyboard and a screen reader can use', () => {
  const text = 'Intro text. Brown v. Board of Education, 347 U.S. 483 (1954). Then Voters were undecided. End.';
  const at = (needle) => ({ position_start: text.indexOf(needle), position_end: text.indexOf(needle) + needle.length });
  const renderIt = () =>
    render(
      <DocumentPreview
        text={text}
        citations={[{ id: 'c1', status: 'complete', ...at('Brown v. Board of Education, 347 U.S. 483 (1954)') }]}
        unsourcedClaims={[{ id: 'k1', ...at('Voters were undecided') }]}
      />
    );

  it('the scrolling pane is a named region that takes focus, so the arrow keys scroll it', () => {
    renderIt();
    const pane = screen.getByRole('region', { name: 'Document text' });
    expect(pane.getAttribute('tabindex')).toBe('0');
    expect(pane).toBe(screen.getByTestId('preview-pane'));
  });

  it('a citation is a <mark>, with words in front of it that say what it is and that are not copied with it', () => {
    renderIt();
    const mark = window.document.querySelector('mark.citation-highlight');
    expect(mark.textContent).toBe('Brown v. Board of Education, 347 U.S. 483 (1954)');
    const prefix = mark.previousElementSibling;
    expect(prefix.textContent).toBe('Citation (complete): ');
    expect(prefix.className).toContain('sr-only');
    expect(prefix.className).toContain('select-none');
  });

  it('a claim that may need a citation is a <mark> too, and says so', () => {
    renderIt();
    const mark = window.document.querySelector('mark.unsourced-highlight');
    expect(mark.textContent).toBe('Voters were undecided');
    expect(mark.previousElementSibling.textContent).toBe('Statement that may need a citation: ');
    expect(mark.previousElementSibling.className).toContain('sr-only');
    expect(mark.previousElementSibling.className).toContain('select-none');
  });

  it('nothing about a mark suggests it can be pressed', () => {
    renderIt();
    for (const mark of window.document.querySelectorAll('mark')) {
      expect(mark.getAttribute('role')).toBeNull();
      expect(mark.getAttribute('tabindex')).toBeNull();
      expect(mark.getAttribute('onclick')).toBeNull();
    }
  });

  it('the text the page reads aloud, joined, is the document with the labels added', () => {
    renderIt();
    const spoken = screen.getByTestId('preview-pane').textContent;
    expect(spoken).toContain('Citation (complete): Brown v. Board');
    expect(spoken.replace(/Citation \(complete\): |Statement that may need a citation: /g, '')).toBe(text);
  });
});

describe('text in the document’s own language reads in its own direction', () => {
  const ctx = setup();
  const HEBREW = 'ראש הממשלה נגד מדינת ישראל, 123 פ"ד 45 (2019)';

  it('on a card: the text found, the suggestion, the finished shape', () => {
    render(
      <CitationList
        citations={[citation(1, { status: 'incomplete', raw_text: HEBREW, missing: ['year'], template: `${HEBREW} [year]`, type: 'regulation' })]}
        shortFormSuggestions={[{ citation_id: 'c1', suggested_form: `${HEBREW} (2019)`, short_form_type: 'full' }]}
        onSelect={() => {}}
      />
    );
    for (const el of holding(window.document.body, 'ראש')) {
      expect(el.closest('[dir="auto"]'), el.outerHTML.slice(0, 80)).not.toBeNull();
    }
    expect(holding(window.document.body, 'ראש').length).toBeGreaterThanOrEqual(3);
  });

  it('on Fix a citation, in claims, in the preview, in the file name and in messages', async () => {
    ctx.server.on('/api/repair', () => json(incompleteReply({ template: `${HEBREW} [year]`, notes: [HEBREW] })));
    renderApp();
    fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Missing information');
    for (const el of holding(window.document.getElementById('panel-repair'), 'ראש')) expect(el.closest('[dir="auto"]')).not.toBeNull();
    render(<SourceSuggestions claims={[{ id: 'k', text: HEBREW, claim_type: 'legal', confidence: 0.5 }]} />);
    render(<DocumentPreview text={HEBREW} citations={[]} unsourcedClaims={[]} />);
    for (const el of holding(window.document.body, 'ראש')) expect(el.closest('[dir="auto"]'), el.outerHTML.slice(0, 80)).not.toBeNull();
  });
});

describe('the crash screen', () => {
  function Bomb() {
    throw new Error('boom');
  }

  it('is a main landmark, so it is not the one screen with nothing to jump to', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    const main = screen.getByRole('main');
    expect(within(main).getByRole('alert')).toBeTruthy();
    expect(within(main).getByRole('heading', { level: 1 })).toBeTruthy();
    vi.restoreAllMocks();
  });
});
