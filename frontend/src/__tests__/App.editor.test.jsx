// @vitest-environment jsdom
// The citation editor: what Look Up says, whose look-up an answer belongs to, what typed text
// survives, and what Back does while the editor is a sheet.
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { chooseFile, findResults, renderApp, setup, tab } from './harness';
import { deferred, json, networkError } from '../test/fakeServer';
import { analysisBody, citation, many, uploadBody } from '../test/fixtures';
import { DEVICE_OFFLINE_MESSAGE } from '../services/api';

const A = citation(1, { id: 'A', parties: ['Alpha', 'Aardvark'], volume: '111', page: '1', court: 'Court A', year: 1951 });
const B = citation(2, { id: 'B', parties: ['Beta', 'Bison'], volume: '222', page: '2', court: 'Court B', year: 1962 });

const card = (id) => window.document.querySelector(`[data-citation-id="${id}"]`);
const lookupButton = () => screen.getByRole('button', { name: /^(Look Up in Database|Looking up\.\.\.)$/ });
const status = () => screen.getByTestId('lookup-status');
const note = () => screen.queryByTestId('lookup-note');
const field = (label) => screen.getByLabelText(label);
const settle = (ms = 30) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

const found = (extra = {}) => ({
  found: true,
  source: 'CourtListener',
  data: { case_name: 'Alpha v. Aardvark (LOOKED UP)', court: 'scotus', date_filed: '1951-01-01', volume: '111', page: '1', absolute_url: 'https://www.courtlistener.com/opinion/A/' },
  ...extra,
});

/** Page width that tests can change: `set(true)` is a phone, `set(false)` a wide window. */
function mediaQuery(initialNarrow) {
  let narrow = initialNarrow;
  const listeners = new Set();
  vi.stubGlobal('matchMedia', (query) => ({
    get matches() { return narrow && query === '(max-width: 1023px)'; },
    media: query,
    addEventListener: (_, fn) => listeners.add(fn),
    removeEventListener: (_, fn) => listeners.delete(fn),
  }));
  return {
    set(next) {
      narrow = next;
      act(() => listeners.forEach((fn) => fn()));
    },
  };
}

async function openResults(ctx, { citations = [A, B], narrow = false, body = {} } = {}) {
  const media = mediaQuery(narrow);
  ctx.server.on('/api/analyze', () => json(analysisBody({ citations, ...body })));
  renderApp();
  await chooseFile(ctx);
  await findResults();
  return media;
}

describe('Look Up in Database says what happened', () => {
  const ctx = setup();

  it('a record found: fills in the form, says where it was found, and links to it', async () => {
    ctx.server.on('/api/lookup', () => json(found()));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    expect(await screen.findByText('Found in CourtListener')).toBeTruthy();
    expect(field('Parties').value).toBe('Alpha v. Aardvark (LOOKED UP)');
    expect(field('Court').value).toBe('scotus');
    expect(field('Year').value).toBe('1951');
    expect(note()).toBeNull();
    const link = screen.getByRole('link', { name: 'View source →' });
    expect(link.getAttribute('href')).toBe('https://www.courtlistener.com/opinion/A/');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('the "Found" result is announced: it sits in the same polite live region as the notes', async () => {
    ctx.server.on('/api/lookup', () => json(found()));
    await openResults(ctx);
    fireEvent.click(card('A'));
    // The region is in the page before anything is put in it, or nothing would be read out.
    expect(status().getAttribute('role')).toBe('status');
    expect(status().getAttribute('aria-live')).toBe('polite');
    expect(status().textContent).toBe('');
    fireEvent.click(lookupButton());
    await screen.findByText('Found in CourtListener');
    expect(within(status()).getByText('Found in CourtListener')).toBeTruthy();
  });

  it('nothing found: says so, that the citation was not changed, and that it is not a verdict', async () => {
    ctx.server.on('/api/lookup', () => json({ found: false, source: 'CourtListener', data: null }));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    expect(note().textContent).toBe(
      'No matching record was found in CourtListener. Your citation was not changed. ' +
        'That does not mean the citation is wrong.'
    );
    expect(within(status()).getByTestId('lookup-note')).toBe(note());
    expect(field('Parties').value).toBe('Alpha v. Aardvark');
    expect(screen.queryByText(/^Found in/)).toBeNull();
    expect(lookupButton().textContent).toBe('Look Up in Database');
    expect(lookupButton().disabled).toBe(false);
  });

  it.each([
    ['an error with the reason the server gave', { found: false, source: 'CourtListener', error: '403 Forbidden (agent proxy: not allowed)' }],
    ['an empty error, which is what a timeout leaves', { found: false, source: 'CourtListener', error: '' }],
    ['an error of null', { found: false, source: 'CourtListener', error: null }],
    ['a refused address', { found: false, source: 'CourtListener', blocked: true }],
    ['a refused address with a reason', { found: false, source: 'CourtListener', blocked: true, error: 'URL not allowed' }],
    ['an unavailable source', { found: false, source: 'CourtListener', unavailable: true }],
  ])('%s: says the source could not be reached, so nothing was checked, and shows none of the reason', async (_label, body) => {
    ctx.server.on('/api/lookup', () => json(body));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    expect(note().textContent).toBe(
      'CourtListener could not be reached, so this citation was not checked. Your citation was not changed.'
    );
    expect(note().textContent).not.toMatch(/403|Forbidden|proxy|not allowed/);
    expect(note().textContent).not.toContain('No matching record');
    expect(field('Parties').value).toBe('Alpha v. Aardvark');
  });

  it('names the place that was searched, and has a stand-in when the server did not say', async () => {
    ctx.server.on('/api/lookup', () => json({ found: false }));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    expect(note().textContent).toContain('No matching record was found in the database.');
  });

  it.each([
    ['null', null],
    ['text', 'ok'],
    ['a list', []],
  ])('an answer that is %s is reported as one this page cannot read', async (_label, body) => {
    ctx.server.on('/api/lookup', () => json(body));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    expect(note().textContent).toContain('format this page does not understand');
    expect(note().textContent).toContain('Your citation was not changed.');
    expect(field('Parties').value).toBe('Alpha v. Aardvark');
  });

  describe('when the request itself fails, in the same words the rest of the page uses', () => {
    const lookupFails = async (respond) => {
      ctx.server.on('/api/lookup', respond);
      await openResults(ctx);
      fireEvent.click(card('A'));
      fireEvent.click(lookupButton());
      await screen.findByTestId('lookup-note');
      return note().textContent;
    };

    it('no connection on the phone', async () => {
      ctx.server.on('/api/lookup', () => json(found()));
      await openResults(ctx);
      vi.stubGlobal('navigator', { onLine: false });
      fireEvent.click(card('A'));
      fireEvent.click(lookupButton());
      await screen.findByTestId('lookup-note');
      expect(note().textContent).toBe(`${DEVICE_OFFLINE_MESSAGE} Your citation was not changed.`);
      expect(ctx.server.count('/api/lookup')).toBe(0);
    });

    it('no answer from the server', async () => {
      expect(await lookupFails(() => { throw networkError(); })).toBe(
        'Could not reach the citation server. It may be starting up or temporarily down. Your citation was not changed.'
      );
    });

    it('a busy server that said how long to wait', async () => {
      expect(
        await lookupFails(() => json({ detail: 'raw busy text' }, 503, { 'Retry-After': '30' }))
      ).toBe('The server is busy. Try again in 30 seconds. Your citation was not changed.');
    });

    it('a busy server that did not', async () => {
      expect(await lookupFails(() => json({ detail: 'raw busy text' }, 503))).toBe(
        'The server is busy or starting up. Try again in a minute. Your citation was not changed.'
      );
    });

    it('a server that answered with something unusable', async () => {
      expect(await lookupFails(() => new Response('<html>proxy error</html>', { status: 200 }))).toContain(
        'format this page does not understand'
      );
    });

    it.each([
      [400, 'Citation validation failed: 1 validation error for Citation type'],
      [422, 'Unprocessable'],
      [500, 'Traceback (most recent call last): KeyError'],
      [413, 'Too large'],
      [404, 'no route'],
    ])('a %i: one fixed sentence, never what the backend wrote', async (status, raw) => {
      const text = await lookupFails(() => json({ detail: raw }, status));
      expect(text).toBe('The look-up could not be completed. Try again in a minute. Your citation was not changed.');
      expect(text).not.toContain(raw);
    });
  });

  describe('after a timeout', () => {
    const ctx2 = setup({ fakeTimers: true });

    it('says the server did not respond in time, and the citation was not changed', async () => {
      ctx2.server.on('/api/lookup', () => new Promise(() => {}));
      await (async () => {
        const media = mediaQuery(false);
        void media;
        ctx2.server.on('/api/analyze', () => json(analysisBody({ citations: [A, B] })));
        renderApp();
        await ctx2.user.click(tab('Check a document'));
        await ctx2.user.upload(screen.getByLabelText('Choose a document to check'), new File(['x'], 'a.txt'));
        await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      })();
      fireEvent.click(card('A'));
      fireEvent.click(lookupButton());
      await act(async () => { await vi.advanceTimersByTimeAsync(46000); });
      expect(note().textContent).toBe(
        'The server did not respond within 45 seconds. It may be waking up from idle. Please try again. ' +
          'Your citation was not changed.'
      );
      expect(lookupButton().disabled).toBe(false);
    });
  });

  it('asking again clears the last note while it looks, and the new answer replaces it', async () => {
    const second = deferred();
    ctx.server.sequence('/api/lookup', [() => json({ found: false, source: 'CourtListener' }), () => second.promise]);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    fireEvent.click(lookupButton());
    await settle();
    expect(note()).toBeNull();
    expect(lookupButton().textContent).toBe('Looking up...');
    await act(async () => { second.resolve(json(found())); });
    await screen.findByText('Found in CourtListener');
    expect(note()).toBeNull();
  });

  it('a link that is not http or https is not drawn, and a good second address is used instead', async () => {
    ctx.server.on('/api/lookup', () => json(found({ data: { ...found().data, absolute_url: 'javascript:alert(1)', url: 'https://example.org/record' } })));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByText('Found in CourtListener');
    expect(screen.getByRole('link', { name: 'View source →' }).getAttribute('href')).toBe('https://example.org/record');
  });

  it.each([['javascript:alert(1)'], ['JAVASCRIPT:alert(1)'], [' \tjavascript:alert(1)'], ['data:text/html,x'], ['vbscript:x']])(
    'no link is drawn for %s',
    async (url) => {
      ctx.server.on('/api/lookup', () => json(found({ data: { ...found().data, absolute_url: url, url } })));
      await openResults(ctx);
      fireEvent.click(card('A'));
      fireEvent.click(lookupButton());
      await screen.findByText('Found in CourtListener');
      expect(screen.queryByRole('link')).toBeNull();
      expect(window.document.querySelector('a[href^="javascript" i], a[href^="data" i], a[href^="vbscript" i]')).toBeNull();
    }
  );
});

describe('a look-up belongs to the citation it was asked for', () => {
  const ctx = setup();

  it('a slow answer for card A does not fill in card B, and does not say "Found" there', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(card('B'));
    expect(field('Parties').value).toBe('Beta v. Bison');
    // B has its own idle button, not A's "Looking up...".
    expect(lookupButton().textContent).toBe('Look Up in Database');
    expect(lookupButton().disabled).toBe(false);

    await act(async () => { slow.resolve(json(found())); });
    await settle();
    expect(field('Parties').value).toBe('Beta v. Bison');
    expect(field('Volume').value).toBe('222');
    expect(field('Court').value).toBe('Court B');
    expect(screen.queryByText(/^Found in/)).toBeNull();
    expect(note()).toBeNull();
  });

  it('what is saved from card B is B’s own data, not A’s', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(card('B'));
    await act(async () => { slow.resolve(json(found())); });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    expect(within(card('B')).queryByText('Edited')).toBeNull();
    expect(card('B').textContent).not.toContain('LOOKED UP');
    expect(card('A').textContent).not.toContain('LOOKED UP');
  });

  it('the look-up that was left behind is cancelled, not only ignored', async () => {
    ctx.server.on('/api/lookup', () => new Promise(() => {}));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    expect(ctx.server.callsTo('/api/lookup')[0].signal.aborted).toBe(false);
    fireEvent.click(card('B'));
    expect(ctx.server.callsTo('/api/lookup')[0].signal.aborted).toBe(true);
    expect(console.error).not.toHaveBeenCalledWith('Lookup failed:', expect.anything());
  });

  it('after going to card B and back, the answer for card A is dropped and the button is ready to ask again', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(card('B'));
    fireEvent.click(card('A'));
    expect(lookupButton().textContent).toBe('Look Up in Database');
    await act(async () => { slow.resolve(json(found())); });
    await settle();
    expect(field('Parties').value).toBe('Alpha v. Aardvark');
    expect(screen.queryByText(/^Found in/)).toBeNull();
  });

  it('an answer that was already on its way when the person left is dropped, though the request was aborted', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise, { ignoreAbort: true });
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(card('B'));
    expect(ctx.server.callsTo('/api/lookup')[0].signal.aborted).toBe(true);
    await act(async () => { slow.resolve(json(found())); });
    await settle();
    expect(field('Parties').value).toBe('Beta v. Bison');
    expect(screen.queryByText(/^Found in/)).toBeNull();
    // Nor is it kept for card A: when the person comes back, A is as it was.
    fireEvent.click(card('A'));
    expect(field('Parties').value).toBe('Alpha v. Aardvark');
    expect(screen.queryByText(/^Found in/)).toBeNull();
  });

  it('a failure that was already on its way when the person left is dropped too', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise, { ignoreAbort: true });
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(card('B'));
    await act(async () => { slow.reject(networkError()); });
    await settle();
    expect(note()).toBeNull();
    fireEvent.click(card('A'));
    expect(note()).toBeNull();
  });

  it('a late answer after the editor was closed is dropped quietly', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await act(async () => { slow.resolve(json(found())); });
    await settle();
    fireEvent.click(card('A'));
    expect(field('Parties').value).toBe('Alpha v. Aardvark');
    expect(screen.queryByText(/^Found in/)).toBeNull();
  });

  it('a failure for card A does not put its note on card B', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await settle();
    fireEvent.click(card('B'));
    await act(async () => { slow.reject(networkError()); });
    await settle();
    expect(note()).toBeNull();
  });

  it('the note belongs to its card: it is gone on another card, and there again when the person returns', async () => {
    ctx.server.on('/api/lookup', () => json({ found: false, source: 'CourtListener' }));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    fireEvent.click(card('B'));
    expect(note()).toBeNull();
    fireEvent.click(card('A'));
    expect(note().textContent).toContain('No matching record was found in CourtListener.');
  });
});

describe('what was typed in the editor is kept until Save or Cancel', () => {
  const ctx = setup();
  const type = (label, value) => fireEvent.change(field(label), { target: { value } });

  it('through a visit to another results tab', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    type('Court', 'TYPED BY PERSON');
    await ctx.user.click(tab('Unsourced Claims'));
    await ctx.user.click(tab('Citations'));
    expect(screen.getByText('Edit Citation')).toBeTruthy();
    expect(field('Court').value).toBe('TYPED BY PERSON');
  });

  it('through the preview tab too, and for every field', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    type('Parties', 'X v. Y');
    type('Pincite', '490');
    await ctx.user.click(tab('Document Preview'));
    await ctx.user.click(tab('Citations'));
    expect(field('Parties').value).toBe('X v. Y');
    expect(field('Pincite').value).toBe('490');
    expect(field('Volume').value).toBe('111');
  });

  it('through going to another card and back, each card keeping its own', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    type('Court', 'TYPED ON A');
    fireEvent.click(card('B'));
    expect(field('Court').value).toBe('Court B');
    type('Court', 'TYPED ON B');
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('TYPED ON A');
    fireEvent.click(card('B'));
    expect(field('Court').value).toBe('TYPED ON B');
  });

  it('a look-up that filled the form, and its note, are kept too', async () => {
    ctx.server.on('/api/lookup', () => json(found()));
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    await screen.findByText('Found in CourtListener');
    await ctx.user.click(tab('Unsourced Claims'));
    await ctx.user.click(tab('Citations'));
    expect(field('Parties').value).toBe('Alpha v. Aardvark (LOOKED UP)');
    expect(screen.getByText('Found in CourtListener')).toBeTruthy();

    ctx.server.on('/api/lookup', () => json({ found: false, source: 'CourtListener' }));
    fireEvent.click(lookupButton());
    await screen.findByTestId('lookup-note');
    fireEvent.click(card('B'));
    fireEvent.click(card('A'));
    expect(note().textContent).toContain('No matching record was found');
  });

  it('a look-up that finishes while the person is typing adds to what they typed', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    await openResults(ctx);
    fireEvent.click(card('A'));
    fireEvent.click(lookupButton());
    type('Pincite', '490');
    await act(async () => { slow.resolve(json(found())); });
    await screen.findByText('Found in CourtListener');
    expect(field('Pincite').value).toBe('490');
    expect(field('Parties').value).toBe('Alpha v. Aardvark (LOOKED UP)');
  });

  it('Cancel throws the draft away', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    type('Court', 'DRAFT');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('Court A');
  });

  it('Save throws it away, and the card shows what was saved', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    // Saved as two names with the spaces trimmed, which is not what was typed.
    type('Parties', '  Xavier   v.   Yolanda  ');
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    fireEvent.click(card('A'));
    expect(field('Parties').value).toBe('Xavier v. Yolanda');
    type('Court', 'SECOND DRAFT');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('Court A');
    expect(field('Parties').value).toBe('Xavier v. Yolanda');
  });

  it('a new document starts with no drafts, and so does starting over', async () => {
    await openResults(ctx);
    fireEvent.click(card('A'));
    type('Court', 'DRAFT');
    fireEvent.click(card('B'));
    await ctx.user.click(screen.getByRole('button', { name: 'Upload New Document' }));
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(screen.getByLabelText('Choose a document to check'), new File(['x'], 'again.txt'));
    await findResults();
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('Court A');
  });

  it('a draft is only for its own citation: another document that reuses an id does not inherit it', async () => {
    await openResults(ctx, { citations: [A] });
    fireEvent.click(card('A'));
    type('Court', 'DRAFT');
    await ctx.user.click(screen.getByRole('button', { name: 'Upload New Document' }));
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(screen.getByLabelText('Choose a document to check'), new File(['x'], 'again.txt'));
    await findResults();
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('Court A');
  });

  it('typing does not redraw the list of cards', async () => {
    await openResults(ctx, { citations: many(30) });
    fireEvent.click(card('c3'));
    const before = card('c7');
    type('Court', 'x');
    expect(card('c7')).toBe(before);
  });
});

describe('the editor is not remounted when the window crosses the width where a sheet becomes a panel', () => {
  const ctx = setup();
  const type = (label, value) => fireEvent.change(field(label), { target: { value } });

  it('keeps what was typed, the very same inputs, and a look-up in flight, through widening and narrowing', async () => {
    const slow = deferred();
    ctx.server.on('/api/lookup', () => slow.promise);
    const media = await openResults(ctx, { narrow: true });
    fireEvent.click(card('A'));
    const court = field('Court');
    type('Court', 'TYPED BY PERSON');
    fireEvent.click(lookupButton());
    expect(screen.getByRole('dialog', { name: 'Edit citation' })).toBeTruthy();

    media.set(false); // an iPad turned on its side
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByTestId('sheet-backdrop')).toBeNull();
    expect(field('Court')).toBe(court); // the same element: nothing was mounted again
    expect(field('Court').value).toBe('TYPED BY PERSON');
    expect(lookupButton().textContent).toBe('Looking up...');

    media.set(true);
    expect(screen.getByRole('dialog', { name: 'Edit citation' })).toBeTruthy();
    expect(field('Court')).toBe(court);
    expect(field('Court').value).toBe('TYPED BY PERSON');

    await act(async () => { slow.resolve(json(found())); });
    await screen.findByText('Found in CourtListener');
    expect(field('Court').value).toBe('scotus');
  });

  it('the sheet’s role, label and classes follow the width, and nothing else about the element changes', async () => {
    const media = await openResults(ctx, { narrow: true });
    fireEvent.click(card('A'));
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.className).toContain('fixed');
    media.set(false);
    const shell = field('Court').closest('div.bg-white').parentElement;
    expect(shell).toBe(dialog);
    expect(shell.getAttribute('role')).toBeNull();
    expect(shell.getAttribute('aria-modal')).toBeNull();
    expect(shell.getAttribute('aria-label')).toBeNull();
    expect(shell.getAttribute('tabindex')).toBeNull();
    expect(shell.className).not.toContain('fixed');
    // On a wide screen Escape does nothing to the editor.
    fireEvent.keyDown(shell, { key: 'Escape' });
    expect(screen.getByText('Edit Citation')).toBeTruthy();
  });

  it('focus goes to the sheet when the window narrows, and the page behind stops scrolling', async () => {
    const media = await openResults(ctx, { narrow: false });
    fireEvent.click(card('A'));
    expect(window.document.body.style.overflow).toBe('');
    media.set(true);
    expect(window.document.activeElement).toBe(screen.getByRole('dialog'));
    expect(window.document.body.style.overflow).toBe('hidden');
    media.set(false);
    expect(window.document.body.style.overflow).toBe('');
  });
});

describe('on a phone, Back closes the sheet', () => {
  const ctx = setup();
  const type = (label, value) => fireEvent.change(field(label), { target: { value } });
  const phone = async () => {
    // A history that starts from one known entry, whatever earlier tests left behind.
    window.history.replaceState(null, '');
    return openResults(ctx, { narrow: true });
  };
  const wait = (ms = 40) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

  /** What the Back button does: go back one entry, and let the popstate that follows arrive. */
  const pressBack = async () => {
    window.history.back();
    await wait();
  };

  it('opening the sheet adds one history entry', async () => {
    await phone();
    const push = vi.spyOn(window.history, 'pushState');
    fireEvent.click(card('A'));
    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0][0]).toEqual({ sheet: true });
    expect(window.history.state).toEqual({ sheet: true });
  });

  it('Back closes the sheet, and the results and the card are still there', async () => {
    await phone();
    fireEvent.click(card('B'));
    expect(screen.getByRole('dialog')).toBeTruthy();
    await pressBack();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText('Analysis Summary')).toBeTruthy();
    expect(window.document.body.style.overflow).toBe('');
    expect(window.document.activeElement.getAttribute('data-citation-id')).toBe('B');
    expect(window.history.state).toBeNull();
  });

  it('Back throws the draft away, as Cancel does', async () => {
    await phone();
    fireEvent.click(card('A'));
    type('Court', 'DRAFT');
    await pressBack();
    fireEvent.click(card('A'));
    expect(field('Court').value).toBe('Court A');
  });

  it('the page does not take its own entry away a second time when Back already did', async () => {
    await phone();
    fireEvent.click(card('A'));
    const back = vi.spyOn(window.history, 'back');
    await pressBack();
    expect(back).toHaveBeenCalledTimes(1); // the test’s own call, and none made by the page
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it.each([
    ['Close', async () => fireEvent.click(screen.getByRole('button', { name: 'Close editor and go back to the list' }))],
    ['Cancel', async () => fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))],
    ['Save', async () => fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))],
    ['a tap outside', async () => fireEvent.click(screen.getByTestId('sheet-backdrop'))],
    ['Escape', async () => fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })],
  ])('closing with %s takes the history entry away again, so nothing piles up', async (_label, close) => {
    await phone();
    fireEvent.click(card('A'));
    expect(window.history.state).toEqual({ sheet: true });
    await close();
    await wait();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(window.history.state).toBeNull();
    // Nothing is left over to swallow or to cause a Back: the next sheet closes with Back as usual.
    fireEvent.click(card('B'));
    expect(screen.getByRole('dialog')).toBeTruthy();
    await pressBack();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('leaving the Citations tab takes the entry away, and the sheet that comes back has its own', async () => {
    await phone();
    fireEvent.click(card('A'));
    await ctx.user.click(tab('Unsourced Claims'));
    await wait();
    expect(window.history.state).toBeNull();
    await ctx.user.click(tab('Citations'));
    // The card is still selected, so the sheet is open again, with a new entry.
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(window.history.state).toEqual({ sheet: true });
    await pressBack();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('the entry the page took away is not mistaken for Back when the next sheet opens at once', async () => {
    await phone();
    fireEvent.click(card('A'));
    fireEvent.click(screen.getByRole('button', { name: 'Close editor and go back to the list' }));
    fireEvent.click(card('B')); // before the popstate from the entry taken away has arrived
    await wait(80);
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(field('Parties').value).toBe('Beta v. Bison');
    // The person’s own Back still closes it.
    await pressBack();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('widening the window takes the entry away without closing the editor', async () => {
    const media = await phone();
    fireEvent.click(card('A'));
    media.set(false);
    await wait();
    expect(window.history.state).toBeNull();
    expect(screen.getByText('Edit Citation')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    media.set(true);
    expect(window.history.state).toEqual({ sheet: true });
  });

  it('on a wide screen the editor adds no history entry', async () => {
    window.history.replaceState(null, '');
    await openResults(ctx, { narrow: false });
    const push = vi.spyOn(window.history, 'pushState');
    fireEvent.click(card('A'));
    expect(push).not.toHaveBeenCalled();
    expect(window.history.state).toBeNull();
  });

  it('does not touch the history when the page is taken down with the sheet open', async () => {
    window.history.replaceState(null, '');
    mediaQuery(true);
    ctx.server.on('/api/analyze', () => json(analysisBody({ citations: [A, B] })));
    const view = renderApp();
    await chooseFile(ctx);
    await findResults();
    fireEvent.click(card('A'));
    const back = vi.spyOn(window.history, 'back');
    view.unmount();
    expect(back).not.toHaveBeenCalled();
  });
});

describe('what the page draws from the document’s warnings', () => {
  const ctx = setup();

  it('two warnings that say the same thing are both shown, with no duplicate-key warning', async () => {
    ctx.server.on('/api/upload', () => json(uploadBody({ warnings: ['2 pages could not be read', '2 pages could not be read'] })));
    await openResults(ctx);
    expect(screen.getAllByText('2 pages could not be read')).toHaveLength(2);
    const keyWarnings = console.error.mock.calls.filter((call) => /same key/.test(String(call[0])));
    expect(keyWarnings).toEqual([]);
  });
});
