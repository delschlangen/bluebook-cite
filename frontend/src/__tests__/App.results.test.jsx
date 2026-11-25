// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { chooseFile, findResults, renderApp, setup, tab } from './harness';
import { json } from '../test/fakeServer';
import { analysisBody, citation, claim, many, uploadBody } from '../test/fixtures';
import { ambiguousReply, resolvedReply } from '../test/repairReplies';

const TEXT = 'The court reasoned carefully about the statutory text. '.repeat(2200); // 121,000 characters

function serve(ctx, { citations = many(250), claims = many(250, claim) } = {}) {
  ctx.server
    .on('/api/upload', () => json(uploadBody({ full_text: TEXT })))
    .on('/api/analyze', () => json(analysisBody({ citations, claims })));
}

const cards = () => window.document.querySelectorAll('[data-card-index]');
const claimCards = () => window.document.querySelectorAll('[data-claim-index]');
const showMore = () => screen.getByRole('button', { name: /^Show \d+ more/ });
const range = () => screen.getByText(/^Characters /).textContent;
const bounds = () => range().match(/Characters ([\d,]+) to ([\d,]+) of ([\d,]+)/).slice(1).map((n) => Number(n.replace(/,/g, '')));

function stubMatchMedia(narrow) {
  vi.stubGlobal('matchMedia', (query) => ({
    matches: narrow && query === '(max-width: 1023px)',
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  }));
}

describe('where the person had got to in each tab is kept when they change tabs', () => {
  const ctx = setup();

  it('the citation cards that were opened with "Show more" are still open on coming back', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    expect(cards()).toHaveLength(100);
    await ctx.user.click(showMore());
    expect(cards()).toHaveLength(200);

    await ctx.user.click(tab('Unsourced Claims'));
    await ctx.user.click(tab('Citations'));
    expect(cards()).toHaveLength(200);
    expect(showMore().textContent).toBe('Show 50 more (50 not shown)');
  });

  it('the claims opened with "Show more" are too, and each tab keeps its own count', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(tab('Unsourced Claims'));
    expect(claimCards()).toHaveLength(100);
    await ctx.user.click(showMore());
    await ctx.user.click(showMore());
    expect(claimCards()).toHaveLength(250);

    await ctx.user.click(tab('Citations'));
    expect(cards()).toHaveLength(100); // not touched
    await ctx.user.click(tab('Unsourced Claims'));
    expect(claimCards()).toHaveLength(250);
  });

  it('the preview is on the window the person moved to, not back at the first one', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(tab('Document Preview'));
    const [start0, end0, length] = bounds();
    expect(start0).toBe(0);
    expect(length).toBe(121000);

    await ctx.user.click(screen.getByRole('button', { name: 'Next' }));
    const [start1, end1] = bounds();
    expect(start1).toBe(end0);

    await ctx.user.click(tab('Citations'));
    await ctx.user.click(tab('Document Preview'));
    expect(bounds().slice(0, 2)).toEqual([start1, end1]);
  });

  it('a new document starts again from the first page of cards and the first window', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(showMore());
    await ctx.user.click(tab('Document Preview'));
    await ctx.user.click(screen.getByRole('button', { name: 'Next' }));

    await ctx.user.click(screen.getByRole('button', { name: 'Upload New Document' }));
    await chooseFile(ctx, undefined, { open: false });
    await findResults();
    expect(cards()).toHaveLength(100);
    await ctx.user.click(tab('Document Preview'));
    expect(bounds()[0]).toBe(0);
  });

  it('the card that was selected is still selected, and its editor still shown, after a trip to another tab', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(showMore());
    const card = window.document.querySelector('[data-citation-id="c150"]');
    await ctx.user.click(card);
    expect(screen.getByText('Edit Citation')).toBeTruthy();

    await ctx.user.click(tab('Document Preview'));
    await ctx.user.click(tab('Citations'));
    const again = window.document.querySelector('[data-citation-id="c150"]');
    expect(again).not.toBeNull(); // still rendered, because the cards that were open stayed open
    expect(again.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Edit Citation')).toBeTruthy();
  });
});

describe('after "Show more", the person is where the new cards begin', () => {
  const ctx = setup();

  it('focus moves to the first card that was added', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(showMore());
    expect(window.document.activeElement.getAttribute('data-card-index')).toBe('100');
    expect(window.document.activeElement.getAttribute('data-citation-id')).toBe('c101');
  });

  it('and to the first claim that was added', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(tab('Unsourced Claims'));
    await ctx.user.click(showMore());
    expect(window.document.activeElement.getAttribute('data-claim-index')).toBe('100');
  });

  it('it also works from the keyboard', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    showMore().focus();
    await ctx.user.keyboard('{Enter}');
    expect(window.document.activeElement.getAttribute('data-card-index')).toBe('100');
  });

  it('announces how many are shown', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const live = screen.getByText('Showing 100 of 250 citations');
    expect(live.getAttribute('aria-live')).toBe('polite');
    await ctx.user.click(showMore());
    expect(screen.getByText('Showing 200 of 250 citations')).toBeTruthy();
  });

  it('writes the numbers on the button with separators', async () => {
    serve(ctx, { citations: many(2450) });
    renderApp();
    await chooseFile(ctx);
    await findResults();
    expect(showMore().textContent).toBe('Show 100 more (2,350 not shown)');
  });
});

describe('the results can be used from the keyboard and read by a screen reader', () => {
  const ctx = setup();

  it('the three results tabs are tabs, and one is selected', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const list = screen.getByRole('tablist', { name: 'Results' });
    const tabs = within(list).getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['Citations250', 'Unsourced Claims250', 'Document Preview']);
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false']);
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(tabs[0].id);

    await ctx.user.click(tabs[2]);
    expect(within(list).getAllByRole('tab').map((t) => t.getAttribute('aria-selected'))).toEqual(['false', 'false', 'true']);
  });

  it('a citation card is a button that Enter and Space select', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const first = cards()[0];
    expect(first.getAttribute('role')).toBe('button');
    expect(first.getAttribute('tabindex')).toBe('0');
    expect(first.getAttribute('aria-pressed')).toBe('false');

    first.focus();
    await ctx.user.keyboard('{Enter}');
    expect(screen.getByText('Edit Citation')).toBeTruthy();
    expect(cards()[0].getAttribute('aria-pressed')).toBe('true');

    await ctx.user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText('Edit Citation')).toBeNull();

    cards()[1].focus();
    await ctx.user.keyboard(' ');
    expect(cards()[1].getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Edit Citation')).toBeTruthy();
  });

  it('other keys do nothing to a card', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    cards()[0].focus();
    await ctx.user.keyboard('a');
    expect(screen.queryByText('Edit Citation')).toBeNull();
  });

  it('the upload box can be reached by keyboard: its input is hidden from the eye, not from Tab', async () => {
    renderApp();
    await ctx.user.click(tab('Check a document'));
    const input = screen.getByLabelText('Choose a document to check');
    expect(input.className).toContain('sr-only');
    expect(input.className).not.toMatch(/(^|\s)hidden(\s|$)/);
    expect(input.getAttribute('tabindex')).toBeNull();
    input.focus();
    expect(window.document.activeElement).toBe(input);
  });
});

describe('what a saved edit does to the card', () => {
  const ctx = setup();

  async function open(id = 'c1') {
    serve(ctx, { citations: [citation(1), citation(2)], claims: [] });
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(window.document.querySelector(`[data-citation-id="${id}"]`));
  }

  it('shows the saved fields on the card, marks it Edited, and keeps what was found in the document', async () => {
    await open();
    const year = screen.getByLabelText('Year');
    await ctx.user.clear(year);
    await ctx.user.type(year, '1955');
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(screen.queryByText('Edit Citation')).toBeNull();
    const card = window.document.querySelector('[data-citation-id="c1"]');
    expect(within(card).getByText('Edited')).toBeTruthy();
    expect(within(card).getByTestId('edited-text').textContent).toBe('Brown v. Bd. of Educ., 347 U.S. 1 (1955).');
    expect(card.textContent).toContain('As found in the document: Brown v. Board of Education, 347 U.S. 1 (1954)');
    const other = window.document.querySelector('[data-citation-id="c2"]');
    expect(within(other).queryByText('Edited')).toBeNull();
    expect(screen.getByText('Saved changes to citation 1.')).toBeTruthy();
  });

  it('a field that was emptied is removed from the citation, not kept', async () => {
    await open();
    await ctx.user.clear(screen.getByLabelText('Year'));
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));
    const text = within(window.document.querySelector('[data-citation-id="c1"]')).getByTestId('edited-text').textContent;
    expect(text).toBe('Brown v. Bd. of Educ., 347 U.S. 1.');
  });

  it('emptied parties are removed too, and the card shows what is left', async () => {
    await open();
    await ctx.user.clear(screen.getByLabelText('Parties'));
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));
    const card = window.document.querySelector('[data-citation-id="c1"]');
    expect(within(card).getByTestId('edited-text').textContent).toBe('347 U.S. 1 (1954)');
  });

  it('saving without changing anything says so and does not mark the card', async () => {
    await open();
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));
    const card = window.document.querySelector('[data-citation-id="c1"]');
    expect(within(card).queryByText('Edited')).toBeNull();
    expect(screen.getByText('No changes to save.')).toBeTruthy();
  });

  it('a card that was edited and edited again stays marked', async () => {
    await open();
    await ctx.user.type(screen.getByLabelText('Pincite'), '490');
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));
    await ctx.user.click(window.document.querySelector('[data-citation-id="c1"]'));
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));
    const card = window.document.querySelector('[data-citation-id="c1"]');
    expect(within(card).getByText('Edited')).toBeTruthy();
    expect(within(card).getByTestId('edited-text').textContent).toContain('347 U.S. 1, 490');
  });

  it('puts focus back on the card it came from', async () => {
    await open('c2');
    await ctx.user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(window.document.activeElement.getAttribute('data-citation-id')).toBe('c2');
  });

  it('on a wide screen the editor sits beside the list, not over it', async () => {
    await open();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText('Edit Citation')).toBeTruthy();
  });
});

describe('on a phone the editor opens over the list, with a way back', () => {
  const ctx = setup();

  async function open(id = 'c3') {
    stubMatchMedia(true);
    serve(ctx, { citations: many(5), claims: [] });
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(window.document.querySelector(`[data-citation-id="${id}"]`));
  }

  it('tapping a card opens the editor as a dialog that has focus, and the page behind does not scroll', async () => {
    await open();
    const dialog = screen.getByRole('dialog', { name: 'Edit citation' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(within(dialog).getByText('Edit Citation')).toBeTruthy();
    expect(window.document.activeElement).toBe(dialog);
    expect(window.document.body.style.overflow).toBe('hidden');
    expect(dialog.className).toContain('fixed');
    expect(dialog.className).toContain('bottom-0');
  });

  it('Close goes back to the list, to the card that was tapped, and lets the page scroll again', async () => {
    await open();
    await ctx.user.click(screen.getByRole('button', { name: 'Close editor and go back to the list' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(window.document.activeElement.getAttribute('data-citation-id')).toBe('c3');
    expect(window.document.body.style.overflow).toBe('');
  });

  it('tapping outside the sheet closes it', async () => {
    await open();
    await ctx.user.click(screen.getByTestId('sheet-backdrop'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('Escape closes it', async () => {
    await open();
    await ctx.user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(window.document.activeElement.getAttribute('data-citation-id')).toBe('c3');
  });

  it('Save closes it and the card shows the change', async () => {
    await open();
    await ctx.user.type(screen.getByLabelText('Pincite'), '490');
    await ctx.user.click(screen.getByRole('button', { name: 'Save Changes' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    const card = window.document.querySelector('[data-citation-id="c3"]');
    expect(within(card).getByText('Edited')).toBeTruthy();
    expect(window.document.body.style.overflow).toBe('');
  });

  it('Tab stays inside the sheet', async () => {
    await open();
    const dialog = screen.getByRole('dialog');
    const save = within(dialog).getByRole('button', { name: 'Save Changes' });
    save.focus();
    await ctx.user.tab();
    expect(window.document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Close editor and go back to the list' }));
    await ctx.user.tab({ shift: true });
    expect(window.document.activeElement).toBe(save);
  });

  it('does not show the "select a citation" placeholder, which would sit at the bottom of a long list', async () => {
    stubMatchMedia(true);
    serve(ctx, { citations: many(5), claims: [] });
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const placeholder = screen.getByText('Select a citation to view details and edit').parentElement;
    expect(placeholder.className).toMatch(/(^|\s)hidden(\s|$)/);
    expect(placeholder.className).toContain('lg:block');
  });

  it('follows the screen when it changes width: the editor becomes a sheet on narrowing, and stops being one on widening', async () => {
    let listener;
    let narrow = false;
    const list = {
      get matches() { return narrow; },
      addEventListener: vi.fn((_, fn) => { listener = fn; }),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal('matchMedia', () => list);
    serve(ctx, { citations: many(5), claims: [] });
    const view = renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(window.document.querySelector('[data-citation-id="c3"]'));
    expect(screen.queryByRole('dialog')).toBeNull();

    narrow = true;
    act(() => listener());
    expect(screen.getByRole('dialog', { name: 'Edit citation' })).toBeTruthy();
    narrow = false;
    act(() => listener());
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText('Edit Citation')).toBeTruthy();

    view.unmount();
    expect(list.removeEventListener).toHaveBeenCalledWith('change', listener);
  });

  it('picks up a screen width that changed between the first render and the effect', async () => {
    let reads = 0;
    vi.stubGlobal('matchMedia', () => ({
      get matches() { reads += 1; return reads > 1; },
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    serve(ctx, { citations: many(5), claims: [] });
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(window.document.querySelector('[data-citation-id="c3"]'));
    expect(screen.getByRole('dialog', { name: 'Edit citation' })).toBeTruthy();
  });

  it('works where matchMedia only has the old addListener (Safari before 14)', async () => {
    let listener;
    const list = {
      matches: true,
      addListener: vi.fn((fn) => { listener = fn; }),
      removeListener: vi.fn(),
    };
    vi.stubGlobal('matchMedia', () => list);
    serve(ctx, { citations: many(5), claims: [] });
    const view = renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(window.document.querySelector('[data-citation-id="c3"]'));
    expect(screen.getByRole('dialog')).toBeTruthy();
    view.unmount();
    expect(list.removeListener).toHaveBeenCalledWith(listener);
  });

  it('the editor fields are 16 px on a phone, so iOS does not zoom the page when one is tapped', async () => {
    await open();
    expect(screen.getByLabelText('Year').className).toContain('text-base');
  });

  it('every button in the sheet is a full-size touch target', async () => {
    await open();
    const dialog = screen.getByRole('dialog');
    for (const name of ['Close editor and go back to the list', 'Look Up in Database', 'Cancel', 'Save Changes']) {
      expect(within(dialog).getByRole('button', { name }).className, name).toContain('min-h-[44px]');
    }
  });
});

describe('touch targets and contrast of the controls the page owns', () => {
  const ctx = setup();

  it('the mode buttons, Upload New Document, Try again and Cancel are at least 44 px tall', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'The server hit an unexpected error.' }, 500));
    renderApp();
    expect(tab('Fix a citation').className).toContain('min-h-[44px]');
    expect(tab('Check a document').className).toContain('min-h-[44px]');
    await chooseFile(ctx);
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Upload New Document' }).className).toContain('min-h-[44px]');
    expect(screen.getByRole('button', { name: 'Try again' }).className).toContain('min-h-[44px]');
  });

  it('on the Fix a citation panel, Fix it and its Try again are at least 44 px tall', async () => {
    ctx.server.on('/api/repair', () => json({ detail: 'The server hit an unexpected error.' }, 500));
    renderApp();
    const fixIt = screen.getByRole('button', { name: 'Fix it' });
    expect(fixIt.className).toContain('min-h-[44px]');
    // Something only the server can read, so the page asks it, and it fails.
    await ctx.user.type(screen.getByLabelText('Citation to repair'), 'Smith, The Law of Things (2001)');
    await ctx.user.click(fixIt);
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByRole('button', { name: 'Try again' }).className).toContain('min-h-[44px]');
  });

  describe('everything that can be tapped on the Fix a citation page is at least 44 px tall', () => {
    const panel = () => window.document.getElementById('panel-repair');
    const tappable = () =>
      [...panel().querySelectorAll('button, a[href], [role="radio"]')].filter((el) => !el.closest('.sr-only'));
    const allTall = (where) => {
      const controls = tappable();
      expect(controls.length, where).toBeGreaterThan(0);
      const short = controls.filter((el) => !el.className.includes('min-h-[44px]')).map((el) => el.textContent.slice(0, 40));
      expect(short, `${where}: controls without min-h-[44px]`).toEqual([]);
    };
    const type = (value) => fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value } });

    it('on the landing: the two styles, the five examples and the link that browses every kind', async () => {
      renderApp();
      allTall('landing');
      expect(screen.getAllByRole('radio')).toHaveLength(2);
      expect(tappable().filter((el) => el.className.includes('font-mono'))).toHaveLength(5);
      expect(screen.getByRole('button', { name: /Browse every kind/ }).className).toContain('inline-flex');
    });

    it('with text typed: Clear', async () => {
      renderApp();
      type('Moody');
      expect(screen.getByRole('button', { name: 'Clear' }).className).toContain('min-h-[44px]');
      allTall('typed');
    });

    it('with a result: Copy, and the link that verifies it, which is as tall as a button', async () => {
      ctx.server.on('/api/repair', () => json(resolvedReply()));
      renderApp();
      type('Moody v. NetChoice');
      await ctx.user.click(screen.getByRole('button', { name: 'Fix it' }));
      const verify = await screen.findByRole('link', { name: 'Verify on CourtListener' });
      expect(verify.className).toContain('min-h-[44px]');
      expect(verify.className).toContain('inline-flex');
      expect(verify.className).toContain('items-center');
      expect(screen.getByRole('button', { name: 'Copy' }).className).toContain('min-h-[44px]');
      allTall('result');
    });

    it('with candidates: each Open source link', async () => {
      ctx.server.on('/api/repair', () => json(ambiguousReply()));
      renderApp();
      type('Moody v. NetChoice');
      await ctx.user.click(screen.getByRole('button', { name: 'Fix it' }));
      const links = await screen.findAllByRole('link', { name: 'Open source' });
      expect(links).toHaveLength(2);
      links.forEach((link) => {
        expect(link.className).toContain('min-h-[44px]');
        expect(link.className).toContain('inline-flex');
      });
      allTall('candidates');
    });

    it('with the guide open: every row of it', async () => {
      renderApp();
      await ctx.user.click(screen.getByRole('button', { name: /Browse every kind/ }));
      const rows = [...panel().querySelectorAll('button[aria-expanded]')].filter((el) => el.textContent.match(/Show|Hide/));
      expect(rows.length).toBeGreaterThan(20);
      allTall('guide');
      await ctx.user.click(rows[0]);
      allTall('guide with an item open');
    });

    it('when the guide is shown for a paste that is not recognised', async () => {
      renderApp();
      type('zzzz qqqq');
      await ctx.user.click(screen.getByRole('button', { name: 'Fix it' }));
      await screen.findByText('What kind of source is it?');
      allTall('unrecognised');
    });

    it('the claims\u2019 search-term links, and every field of the editor', async () => {
      serve(ctx, { citations: [citation(1)], claims: [claim(1, { suggested_search_terms: ['voter turnout study'] })] });
      stubMatchMedia(true);
      renderApp();
      await chooseFile(ctx);
      await findResults();
      await ctx.user.click(tab('Unsourced Claims'));
      expect(screen.getByRole('link', { name: /voter turnout study/ }).className).toContain('min-h-[44px]');
      await ctx.user.click(tab('Citations'));
      await ctx.user.click(window.document.querySelector('[data-citation-id="c1"]'));
      for (const input of screen.getByRole('dialog').querySelectorAll('input')) expect(input.className, input.id).toContain('min-h-[44px]');
    });

    it('the editor sheet\u2019s source link, once a record is found', async () => {
      ctx.server.on('/api/lookup', () => json({ found: true, source: 'CourtListener', data: { absolute_url: 'https://www.courtlistener.com/x/' } }));
      serve(ctx, { citations: [citation(1)], claims: [] });
      stubMatchMedia(true);
      renderApp();
      await chooseFile(ctx);
      await findResults();
      await ctx.user.click(window.document.querySelector('[data-citation-id="c1"]'));
      await ctx.user.click(screen.getByRole('button', { name: 'Look Up in Database' }));
      const link = await screen.findByRole('link', { name: 'View source →' });
      expect(link.className).toContain('min-h-[44px]');
    });
  });

  it('Cancel, while a file is going up and while the analysis runs, is at least 44 px tall', async () => {
    ctx.server.on('/api/upload', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Uploading 1 KB...');
    expect(screen.getByRole('button', { name: 'Cancel' }).className).toContain('min-h-[44px]');
  });

  it('the hint under the spinner is dark enough to read', async () => {
    ctx.server.on('/api/analyze', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    const hint = await screen.findByText(/A long document can take up to a minute/);
    expect(hint.className).toContain('text-gray-600');
    expect(hint.className).not.toContain('text-gray-400');
  });

  it('Previous and Next are 44 px tall and, when disabled, still readable', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    await ctx.user.click(tab('Document Preview'));
    const previous = screen.getByRole('button', { name: 'Previous' });
    const next = screen.getByRole('button', { name: 'Next' });
    for (const button of [previous, next]) {
      expect(button.className).toContain('min-h-[44px]');
      expect(button.className).toContain('disabled:text-gray-600');
      expect(button.className).not.toContain('disabled:opacity');
    }
  });

  it('the three results tabs share the row, so none is pushed out of sight on a narrow phone', async () => {
    serve(ctx);
    renderApp();
    await chooseFile(ctx);
    await findResults();
    for (const name of ['Citations', 'Unsourced Claims', 'Document Preview']) {
      const button = tab(name);
      expect(button.className).toContain('flex-1');
      expect(button.className).toContain('min-w-0');
    }
    expect(screen.getByRole('tablist', { name: 'Results' }).className).not.toContain('overflow-x-auto');
  });
});
