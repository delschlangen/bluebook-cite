// @vitest-environment jsdom
// Keyboard, focus, what is read out, and what a person does not lose by accident.
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { chooseFile, findResults, renderApp, setup, tab } from './harness';
import { deferred, json } from '../test/fakeServer';
import { analysisBody, citation, many, uploadBody, claim } from '../test/fixtures';
import { ambiguousReply, incompleteReply, resolvedReply } from '../test/repairReplies';

const A = citation(1, { id: 'A', parties: ['Alpha', 'Aardvark'], volume: '111', page: '1', court: 'Court A', year: 1951 });
const B = citation(2, { id: 'B', parties: ['Beta', 'Bison'], volume: '222', page: '2', court: 'Court B', year: 1962 });
const card = (id) => window.document.querySelector(`[data-citation-id="${id}"]`);
const field = (label) => screen.getByLabelText(label);
const active = () => window.document.activeElement;
const settle = (ms = 30) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

function mediaQuery(initialNarrow) {
  let narrow = initialNarrow;
  const listeners = new Set();
  vi.stubGlobal('matchMedia', (query) => ({
    get matches() { return narrow && query === '(max-width: 1023px)'; },
    media: query,
    addEventListener: (_, fn) => listeners.add(fn),
    removeEventListener: (_, fn) => listeners.delete(fn),
  }));
  return { set(next) { narrow = next; act(() => listeners.forEach((fn) => fn())); } };
}

async function openResults(ctx, { citations = [A, B], narrow = false, claims = [], suggestions = [] } = {}) {
  const media = mediaQuery(narrow);
  ctx.server.on('/api/analyze', () => json(analysisBody({ citations, claims, suggestions })));
  renderApp();
  await chooseFile(ctx);
  await findResults();
  return media;
}

/** Edit citation A (its court) and save it: the card is now marked Edited. */
async function editAndSave(id = 'A', court = 'Court Z') {
  fireEvent.click(card(id));
  fireEvent.change(field('Court'), { target: { value: court } });
  fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
}

// ---------------------------------------------------------------------------------------------

describe('starting over does not throw edited citations away without asking', () => {
  const ctx = setup();
  const reset = () => screen.getByRole('button', { name: 'Upload New Document' });

  it('with an edited citation, asks first, in the page, with the safe answer focused', async () => {
    const confirmBox = vi.spyOn(window, 'confirm').mockReturnValue(true);
    await openResults(ctx);
    await editAndSave();
    fireEvent.click(reset());
    const dialog = screen.getByRole('alertdialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(within(dialog).getByRole('heading', { name: 'Discard your edits?' })).toBeTruthy();
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy();
    expect(dialog.getAttribute('aria-describedby')).toBeTruthy();
    expect(dialog.textContent).toContain('1 citation has been edited here.');
    expect(dialog.textContent).toContain('Copy buttons');
    expect(active()).toBe(within(dialog).getByRole('button', { name: 'Keep working' }));
    expect(window.document.body.contains(screen.getByText('Analysis Summary'))).toBe(true); // nothing was removed
    expect(confirmBox).not.toHaveBeenCalled(); // not window.confirm
  });

  it('says how many, in the plural too', async () => {
    await openResults(ctx);
    await editAndSave('A');
    await editAndSave('B', 'Court Y');
    fireEvent.click(reset());
    expect(screen.getByRole('alertdialog').textContent).toContain('2 citations have been edited here.');
  });

  it.each([
    ['Keep working', () => fireEvent.click(screen.getByRole('button', { name: 'Keep working' }))],
    ['Escape', () => fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' })],
    ['a tap outside', () => fireEvent.click(screen.getByTestId('confirm-backdrop'))],
  ])('%s keeps the results and the edits, and puts focus back on the button that was pressed', async (_label, answer) => {
    await openResults(ctx);
    await editAndSave();
    fireEvent.click(reset());
    answer();
    await settle();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.getByText('Analysis Summary')).toBeTruthy();
    expect(within(card('A')).getByText('Edited')).toBeTruthy();
    expect(active()).toBe(reset());
  });

  it('"Start over and discard" does start over, and puts focus on the first control of the landing page', async () => {
    await openResults(ctx);
    await editAndSave();
    fireEvent.click(reset());
    fireEvent.click(screen.getByRole('button', { name: 'Start over and discard' }));
    await settle();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.queryByText('Analysis Summary')).toBeNull();
    // The test chose a document, so the mode it was in is "Check a document".
    expect(active()).toBe(tab('Check a document'));
  });

  it('Tab stays inside the dialog', async () => {
    await openResults(ctx);
    await editAndSave();
    fireEvent.click(reset());
    const dialog = screen.getByRole('alertdialog');
    const discard = within(dialog).getByRole('button', { name: 'Start over and discard' });
    discard.focus();
    fireEvent.keyDown(discard, { key: 'Tab' });
    expect(active()).toBe(within(dialog).getByRole('button', { name: 'Keep working' }));
    fireEvent.keyDown(active(), { key: 'Tab', shiftKey: true });
    expect(active()).toBe(discard);
  });

  it('with nothing edited it starts over at once, with no question, and focus goes to the landing page', async () => {
    await openResults(ctx);
    fireEvent.click(reset());
    await settle();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.queryByText('Analysis Summary')).toBeNull();
    expect(active()).toBe(tab('Check a document'));
  });

  it('a save that changed nothing is not an edit', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    fireEvent.click(reset());
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('focus goes to the tab of the mode the person was in', async () => {
    await openResults(ctx);
    fireEvent.click(reset());
    await settle();
    fireEvent.click(tab('Check a document'));
    // A second round: results again, then start over from the upload side.
    await chooseFile(ctx, undefined, { open: false });
    await findResults();
    fireEvent.click(reset());
    await settle();
    expect(active()).toBe(tab('Check a document'));
  });
});

// ---------------------------------------------------------------------------------------------

describe('focus is not dropped to the page when the button that has it is turned off or goes', () => {
  const ctx = setup();
  const box = () => screen.getByLabelText('Citation to repair');
  const fixIt = () => screen.getByRole('button', { name: /^(Fix it|Checking\.\.\.)$/ });

  it('Fix it stays focused while it works (it is aria-disabled, not disabled), then focus goes to the result', async () => {
    const slow = deferred();
    ctx.server.on('/api/repair', () => slow.promise);
    renderApp();
    fireEvent.change(box(), { target: { value: 'Moody v. NetChoice' } });
    fixIt().focus();
    await ctx.user.keyboard('{Enter}');
    await settle();
    expect(fixIt().textContent).toBe('Checking...');
    expect(fixIt().disabled).toBe(false);
    expect(fixIt().getAttribute('aria-disabled')).toBe('true');
    expect(active()).toBe(fixIt());
    // Pressing it again while it works does nothing.
    await ctx.user.keyboard('{Enter}');
    expect(ctx.server.count('/api/repair')).toBe(1);

    await act(async () => { slow.resolve(json(resolvedReply())); });
    await settle();
    expect(active()).toBe(screen.getByRole('heading', { name: 'Your result' }));
  });

  it('a result that needs no server takes focus too', async () => {
    renderApp();
    fireEvent.change(box(), { target: { value: 'Brown v. Board of Education, 347 U.S. 483 (1954)' } });
    fixIt().focus();
    await ctx.user.keyboard('{Enter}');
    await settle();
    expect(active()).toBe(screen.getByRole('heading', { name: 'Your result' }));
  });

  it('an example chip does the same', async () => {
    renderApp();
    await ctx.user.click(screen.getByRole('button', { name: 'U.S. Const. amend. XIV' }));
    await settle();
    expect(active()).toBe(screen.getByRole('heading', { name: 'Your result' }));
  });

  it('choosing a style does not take focus from the style buttons', async () => {
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    fireEvent.change(box(), { target: { value: 'Brown v. Board of Education, 347 U.S. 483 (1954)' } });
    fireEvent.click(fixIt());
    await settle();
    const other = screen.getAllByRole('radio').find((radio) => radio.getAttribute('aria-checked') === 'false');
    other.focus();
    fireEvent.click(other);
    await settle();
    expect(active()).toBe(screen.getByRole('radio', { checked: true }));
  });

  it('Clear goes with the text, so focus goes to the box', async () => {
    renderApp();
    fireEvent.change(box(), { target: { value: 'Moody v. NetChoice' } });
    const clear = screen.getByRole('button', { name: 'Clear' });
    clear.focus();
    await ctx.user.keyboard('{Enter}');
    expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull();
    expect(active()).toBe(box());
  });

  it('Fix it with an empty box is off and stays where it is', async () => {
    renderApp();
    expect(fixIt().getAttribute('aria-disabled')).toBe('true');
    fixIt().focus();
    await ctx.user.keyboard('{Enter}');
    expect(active()).toBe(fixIt());
    expect(ctx.server.count('/api/repair')).toBe(0);
  });

  it('Try again after a failure leads to the result, as Fix it does', async () => {
    ctx.server.sequence('/api/repair', [() => json({ detail: 'boom' }, 500), () => json(resolvedReply())]);
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    fireEvent.change(box(), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(fixIt());
    const again = await screen.findByRole('button', { name: 'Try again' });
    again.focus();
    fireEvent.click(again);
    await settle(80);
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(active()).toBe(screen.getByRole('heading', { name: 'Your result' }));
  });

  it('Look Up stays focused while it works, and Escape still closes the sheet', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx, { narrow: true });
    fireEvent.click(card('A'));
    const lookup = screen.getByRole('button', { name: 'Look Up in Database' });
    lookup.focus();
    await ctx.user.keyboard('{Enter}');
    await settle();
    const working = screen.getByRole('button', { name: 'Looking up...' });
    expect(working.disabled).toBe(false);
    expect(working.getAttribute('aria-disabled')).toBe('true');
    expect(active()).toBe(working);
    await ctx.user.keyboard('{Enter}');
    expect(ctx.server.count('/api/lookup')).toBe(1);
    await ctx.user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(active()).toBe(card('A'));
  });

  it('when the analysis finishes after the file was chosen, focus goes to the summary', async () => {
    await openResults(ctx);
    expect(active()).toBe(screen.getByRole('heading', { name: 'Analysis Summary' }));
  });

  it('focus that is on something the person can still use is left alone when the analysis finishes', async () => {
    const slow = deferred();
    ctx.server.on('/api/analyze', () => slow.promise);
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx);
    // While it works the person is on the header button, which is still there afterwards.
    const header = await screen.findByRole('button', { name: 'Upload New Document' });
    header.focus();
    await act(async () => { slow.resolve(json(analysisBody({ citations: [A] }))); });
    await findResults();
    expect(active()).toBe(header);
  });

  it('and when it fails', async () => {
    const slow = deferred();
    ctx.server.on('/api/analyze', () => slow.promise);
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx);
    const header = await screen.findByRole('button', { name: 'Upload New Document' });
    header.focus();
    await act(async () => { slow.resolve(json({ detail: 'The server hit an unexpected error.' }, 500)); });
    await screen.findByRole('alert');
    await settle();
    expect(active()).toBe(header);
  });

  it('but focus on a control that has been hidden, or taken out of the page, is lost focus', async () => {
    const slow = deferred();
    ctx.server.on('/api/analyze', () => slow.promise);
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx);
    // The landing page is hidden while the analysis runs; a control in it that still had focus is no use.
    const hiddenTab = window.document.getElementById('mode-upload');
    expect(hiddenTab.closest('[hidden]')).not.toBeNull();
    hiddenTab.focus();
    expect(active()).toBe(hiddenTab);
    await act(async () => { slow.resolve(json(analysisBody({ citations: [A] }))); });
    await findResults();
    expect(active()).toBe(screen.getByRole('heading', { name: 'Analysis Summary' }));
  });

  it('when the analysis finishes after the Cancel that had focus has gone, focus goes to the summary', async () => {
    const slow = deferred();
    ctx.server.on('/api/analyze', () => slow.promise);
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx);
    const cancel = await screen.findByRole('button', { name: 'Cancel' });
    cancel.focus();
    await act(async () => { slow.resolve(json(analysisBody({ citations: [A] }))); });
    await findResults();
    expect(active()).toBe(screen.getByRole('heading', { name: 'Analysis Summary' }));
  });

  it('a failure that takes the Cancel button away puts focus on the message', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'The server hit an unexpected error.' }, 500));
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    await settle();
    expect(active()).toBe(alert);
  });

  it('a refused file leaves focus on the file box, which is still there to use', async () => {
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx, new File(['x'], 'brief.doc'));
    await screen.findByRole('alert');
    await settle();
    expect(active()).toBe(screen.getByLabelText('Choose a document to check'));
  });

  it('a failed upload, which took the Cancel button away, puts focus on the message', async () => {
    ctx.server.on('/api/upload', () => json({ detail: 'The PDF is encrypted.' }, 400));
    mediaQuery(false);
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    await settle();
    expect(active()).toBe(alert);
  });
});

// ---------------------------------------------------------------------------------------------

describe('what is read out: one region per job, in the page before it has anything to say', () => {
  const ctx = setup();
  const box = () => screen.getByLabelText('Citation to repair');

  it('Fix a citation: the region is there and empty, then gets a short summary, in the same element', async () => {
    ctx.server.on('/api/repair', () => json(ambiguousReply()));
    renderApp();
    const region = screen.getByTestId('repair-status');
    expect(region.getAttribute('role')).toBe('status');
    expect(region.textContent).toBe('');
    fireEvent.change(box(), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Needs your choice');
    expect(screen.getByTestId('repair-status')).toBe(region);
    expect(region.textContent).toBe('Needs your choice. 2 details are still needed. 2 possible matches.');
  });

  it('the result card itself is not a live region (it would be created with its text)', async () => {
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    fireEvent.change(box(), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Ready to use');
    expect(screen.getByRole('heading', { name: 'Your result' }).parentElement.hasAttribute('aria-live')).toBe(false);
    for (const live of window.document.querySelectorAll('[aria-live], [role="status"]')) {
      expect(live.textContent.length, live.outerHTML.slice(0, 80)).toBeLessThan(140);
    }
    expect(screen.getByTestId('repair-status').textContent).toBe('Ready to use.');
  });

  it('says a paste that was only partly handled', async () => {
    renderApp();
    fireEvent.change(box(), {
      target: { value: 'Brown v. Board of Education, 347 U.S. 483 (1954); Marbury v. Madison, 5 U.S. 137 (1803).' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByTestId('partial-note');
    expect(screen.getByTestId('repair-status').textContent).toBe('Only part of your paste. Only part of your paste was formatted.');
  });

  it('says nothing when the result no longer fits the text', async () => {
    renderApp();
    fireEvent.change(box(), { target: { value: 'Brown v. Board of Education, 347 U.S. 483 (1954)' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Ready to use');
    fireEvent.change(box(), { target: { value: 'Brown v. Board of Education, 347 U.S. 483 (1954) and' } });
    expect(screen.getByTestId('repair-status').textContent).toBe('');
  });

  it('the analysis: a region that is there from the start says "Analyzing citations." and then how it ended', async () => {
    const slow = deferred();
    ctx.server.on('/api/analyze', () => slow.promise);
    mediaQuery(false);
    renderApp();
    const region = screen.getByTestId('progress-status');
    expect(region.getAttribute('role')).toBe('status');
    expect(region.textContent).toBe('');
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    expect(screen.getByTestId('progress-status')).toBe(region);
    expect(region.textContent).toBe('Analyzing citations.');
    // The words on the screen are not a second region.
    expect(screen.getByText('Analyzing citations...').hasAttribute('role')).toBe(false);
    await act(async () => { slow.resolve(json(analysisBody({ citations: many(3) }))); });
    await findResults();
    expect(region.textContent).toBe('Analysis finished. 3 citations found.');
  });

  it('says 1 citation, not 1 citations', async () => {
    mediaQuery(false);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [A] })));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    expect(screen.getByTestId('progress-status').textContent).toBe('Analysis finished. 1 citation found.');
  });

  it('the page has exactly the live regions it needs, each in the page from the start', () => {
    renderApp();
    const roles = [...window.document.querySelectorAll('[role="status"]')].map((el) => el.getAttribute('data-testid') || el.className);
    expect(roles).toEqual(expect.arrayContaining(['progress-status', 'repair-status']));
    for (const el of window.document.querySelectorAll('[role="status"]')) expect(el.textContent).toBe('');
  });
});

// ---------------------------------------------------------------------------------------------

describe('tabs and radio buttons: one stop in the Tab order, and the arrow keys move between them', () => {
  const ctx = setup();
  const press = (element, key) => fireEvent.keyDown(element, { key });

  it('the two modes: only the selected tab is a Tab stop, and ArrowRight, ArrowLeft, End and Home choose another', () => {
    renderApp();
    const repair = tab('Fix a citation');
    const upload = tab('Check a document');
    expect(repair.getAttribute('tabindex')).toBe('0');
    expect(upload.getAttribute('tabindex')).toBe('-1');
    repair.focus();
    press(repair, 'ArrowRight');
    expect(upload.getAttribute('aria-selected')).toBe('true');
    expect(active()).toBe(upload);
    expect(upload.getAttribute('tabindex')).toBe('0');
    expect(repair.getAttribute('tabindex')).toBe('-1');
    press(upload, 'ArrowRight'); // wraps
    expect(repair.getAttribute('aria-selected')).toBe('true');
    press(repair, 'ArrowLeft'); // wraps back
    expect(upload.getAttribute('aria-selected')).toBe('true');
    press(upload, 'Home');
    expect(repair.getAttribute('aria-selected')).toBe('true');
    press(repair, 'End');
    expect(upload.getAttribute('aria-selected')).toBe('true');
    expect(window.document.getElementById('panel-upload').hidden).toBe(false);
  });

  it('other keys, and ArrowUp and ArrowDown on tabs, do nothing', () => {
    renderApp();
    const repair = tab('Fix a citation');
    repair.focus();
    for (const key of ['ArrowDown', 'ArrowUp', 'a', 'Enter']) press(repair, key);
    expect(repair.getAttribute('aria-selected')).toBe('true');
  });

  it('the style radio group: one Tab stop, the arrows (all four) and Home and End choose, and it asks again', async () => {
    window.localStorage.clear();
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    const radios = screen.getAllByRole('radio');
    expect(radios.map((r) => r.getAttribute('tabindex'))).toEqual(['0', '-1']);
    radios[0].focus();
    press(radios[0], 'ArrowRight');
    expect(radios[1].getAttribute('aria-checked')).toBe('true');
    expect(active()).toBe(radios[1]);
    expect(radios.map((r) => r.getAttribute('tabindex'))).toEqual(['-1', '0']);
    press(radios[1], 'ArrowUp');
    expect(radios[0].getAttribute('aria-checked')).toBe('true');
    press(radios[0], 'ArrowDown');
    expect(radios[1].getAttribute('aria-checked')).toBe('true');
    press(radios[1], 'Home');
    expect(radios[0].getAttribute('aria-checked')).toBe('true');
    press(radios[0], 'End');
    expect(radios[1].getAttribute('aria-checked')).toBe('true');
    window.localStorage.clear();
  });

  it('choosing a style with an arrow key asks again for the text that is there, as a click does', async () => {
    window.localStorage.clear();
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: 'Moody v. NetChoice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    await screen.findByText('Ready to use');
    const [first] = screen.getAllByRole('radio');
    first.focus();
    press(first, 'ArrowRight');
    await settle();
    expect(ctx.server.count('/api/repair')).toBe(2);
    window.localStorage.clear();
  });

  it('the results tabs follow the same pattern', async () => {
    await openResults(ctx);
    const [citations, claims, preview] = ['Citations', 'Unsourced Claims', 'Document Preview'].map(tab);
    expect([citations, claims, preview].map((t) => t.getAttribute('tabindex'))).toEqual(['0', '-1', '-1']);
    citations.focus();
    press(citations, 'ArrowRight');
    expect(claims.getAttribute('aria-selected')).toBe('true');
    expect(active()).toBe(claims);
    press(claims, 'End');
    expect(preview.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('region', { name: 'Document text' })).toBeTruthy();
    press(preview, 'ArrowRight');
    expect(citations.getAttribute('aria-selected')).toBe('true');
    expect(active()).toBe(citations);
  });

  it('on three tabs, Home and End go to the ends, not to the next one', async () => {
    await openResults(ctx);
    const [citations, claims, preview] = ['Citations', 'Unsourced Claims', 'Document Preview'].map(tab);
    citations.focus();
    press(citations, 'End');
    expect(preview.getAttribute('aria-selected')).toBe('true'); // the next one would be Unsourced Claims
    press(preview, 'ArrowLeft');
    expect(claims.getAttribute('aria-selected')).toBe('true');
    press(claims, 'Home');
    expect(citations.getAttribute('aria-selected')).toBe('true'); // the next one would be Document Preview
  });

  it('an arrow key does not also scroll the page', () => {
    renderApp();
    const repair = tab('Fix a citation');
    repair.focus();
    expect(fireEvent.keyDown(repair, { key: 'ArrowRight' })).toBe(false);
  });

  it('the tab that is off while a file goes up is dark grey on light grey, not faded', async () => {
    const slow = deferred();
    ctx.server.on('/api/upload', () => slow.promise);
    renderApp();
    await chooseFile(ctx);
    const off = tab('Fix a citation');
    expect(off.disabled).toBe(true);
    expect(off.className).toContain('disabled:bg-gray-100');
    expect(off.className).toContain('disabled:text-gray-600');
    expect(off.className).not.toMatch(/opacity/);
  });

  it('a tab that is disabled (the other mode while a file goes up) is skipped', async () => {
    const slow = deferred();
    ctx.server.on('/api/upload', () => slow.promise);
    renderApp();
    await chooseFile(ctx);
    const upload = tab('Check a document');
    upload.focus();
    press(upload, 'ArrowRight');
    press(upload, 'Home');
    expect(upload.getAttribute('aria-selected')).toBe('true'); // the only one that can be chosen
  });
});

// ---------------------------------------------------------------------------------------------

describe('the editor beside the list (1024 px and wider)', () => {
  const ctx = setup();

  it('takes focus, at its heading, when a card is chosen, and gives it back to the card on Close', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    expect(active()).toBe(screen.getByRole('heading', { name: 'Edit Citation' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close editor and go back to the list' }));
    await settle();
    expect(active()).toBe(card('A'));
  });

  it('has a Close button at every width, not only on a phone', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    const close = screen.getByRole('button', { name: 'Close editor and go back to the list' });
    expect(close.className).not.toContain('lg:hidden');
    expect(close.className).toContain('min-h-[44px]');
  });

  it('Escape closes it, from the heading and from a field, and the draft goes with it', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.change(field('Court'), { target: { value: 'DRAFT' } });
    fireEvent.keyDown(field('Court'), { key: 'Escape' });
    expect(screen.queryByText('Edit Citation')).toBeNull();
    await settle();
    expect(active()).toBe(card('A'));
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('Court A');
    fireEvent.keyDown(screen.getByRole('heading', { name: 'Edit Citation' }), { key: 'Escape' });
    expect(screen.queryByText('Edit Citation')).toBeNull();
  });

  it('Tab may leave it (the page is not covered)', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    const save = screen.getByRole('button', { name: 'Save Changes' });
    save.focus();
    const proceed = fireEvent.keyDown(save, { key: 'Tab' });
    expect(proceed).toBe(true); // not prevented
  });

  it('does not take focus when it comes back with the Citations tab, only when a card is chosen', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    await ctx.user.click(tab('Unsourced Claims'));
    await ctx.user.click(tab('Citations'));
    expect(screen.getByText('Edit Citation')).toBeTruthy();
    expect(active()).toBe(tab('Citations'));
  });

  it('chosing the next card moves focus to its editor', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(card('B'));
    expect(field('Parties').value).toBe('Beta v. Bison');
    expect(active()).toBe(screen.getByRole('heading', { name: 'Edit Citation' }));
  });

  it('sits in a column that stays in view beside a long list, and scrolls inside itself', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    const column = screen.getByRole('heading', { name: 'Edit Citation' }).closest('div.min-w-0.lg\\:sticky');
    expect(column).not.toBeNull();
    for (const name of ['lg:sticky', 'lg:top-4', 'lg:self-start', 'lg:max-h-[calc(100vh-2rem)]', 'lg:overflow-y-auto']) {
      expect(column.className, name).toContain(name);
    }
  });

  it('on a phone focus is still on the sheet, which is a dialog', async () => {
    await openResults(ctx, { narrow: true });
    fireEvent.click(card('A'));
    expect(active()).toBe(screen.getByRole('dialog', { name: 'Edit citation' }));
  });
});
