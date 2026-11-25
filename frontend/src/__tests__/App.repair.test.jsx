// @vitest-environment jsdom
// The Fix a citation page: what it says when a paste holds several citations or is too long,
// when a request fails, when the server answers with something it cannot draw, and when an old
// answer arrives after the person has moved on.
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { advance, renderApp, setup } from './harness';
import { deferred, json, networkError } from '../test/fakeServer';
import { UNEXPECTED_FORMAT_MESSAGE } from '../services/api';
import { ambiguousReply, incompleteReply, resolvedReply } from '../test/repairReplies';

const BROWN = 'Brown v. Board of Education, 347 U.S. 483 (1954)';
const MARBURY = 'Marbury v. Madison, 5 U.S. 137 (1803)';

const box = () => screen.getByLabelText('Citation to repair');
const fixIt = () => screen.getByRole('button', { name: /^(Fix it|Checking\.\.\.)$/ });
const paste = (value) => fireEvent.change(box(), { target: { value } });
const submit = () => fireEvent.click(fixIt());
const alerts = () => screen.queryAllByRole('alert').map((a) => a.textContent);
const tryAgain = () => screen.queryByRole('button', { name: /^Try again/ });
const settle = (ms = 30) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

describe('a paste with more than one citation is not reported as fully handled', () => {
  const ctx = setup();

  it('says which citation was formatted and which were left out, and is not "Ready to use"', async () => {
    renderApp();
    paste(`${BROWN}; ${MARBURY}.`);
    submit();
    const note = await screen.findByTestId('partial-note');
    expect(note.textContent).toBe(
      `Your paste has more than one citation. Only “${BROWN}” was formatted. ` +
        `Not formatted: “${MARBURY}”. Paste them one at a time, or use Check a document.`
    );
    expect(screen.queryByText('Ready to use')).toBeNull();
    expect(screen.getByText('Only part of your paste')).toBeTruthy();
    // The formatted citation is still there to use.
    expect(screen.getByText(/Brown v\. Bd\. of Educ\./)).toBeTruthy();
    expect(ctx.server.count('/api/repair')).toBe(0);
  });

  it('puts the note before the formatted citation, so it is read before Copy is reached', async () => {
    renderApp();
    paste(`${BROWN}; ${MARBURY}.`);
    submit();
    const note = await screen.findByTestId('partial-note');
    const copy = screen.getByRole('button', { name: 'Copy' });
    expect(note.compareDocumentPosition(copy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('is still "Ready to use", with no note, when prose surrounds a single citation', async () => {
    renderApp();
    paste(`In ${BROWN}, the Court held that separate is not equal.`);
    submit();
    expect(await screen.findByText('Ready to use')).toBeTruthy();
    expect(screen.queryByTestId('partial-note')).toBeNull();
    expect(screen.queryByText('Only part of your paste')).toBeNull();
  });

  it('keeps the note when the server answers for the part that needed a look-up', async () => {
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    paste('Moody v. NetChoice; Brown v. Board');
    submit();
    // The browser read one citation and found it incomplete, so the server was asked.
    await screen.findByText(/Verify on CourtListener/);
    expect(ctx.server.count('/api/repair')).toBe(1);
    const note = screen.getByTestId('partial-note');
    expect(note.textContent).toContain('Only “Moody v. NetChoice” was formatted');
    expect(note.textContent).toContain('Not formatted: “Brown v. Board”.');
    expect(screen.queryByText('Ready to use')).toBeNull();
  });
});

describe('the text is never cut to fit, and is refused openly when it is too long', () => {
  const ctx = setup();
  const counter = () => screen.queryByTestId('citation-count');
  const big = (n) => `${BROWN}; `.repeat(Math.ceil(n / (BROWN.length + 2))).slice(0, n);

  it('has no hidden limit on the text box: all of a long paste stays', () => {
    renderApp();
    expect(box().hasAttribute('maxlength')).toBe(false);
    paste(big(5000));
    expect(box().value).toHaveLength(5000);
  });

  it('shows no counter for a short paste, and a count from 80% of the limit', () => {
    renderApp();
    paste(big(1599));
    expect(counter()).toBeNull();
    paste(big(1600));
    expect(counter().textContent).toBe('1,600 of 2,000 characters.');
    paste(big(2000));
    expect(counter().textContent).toBe('2,000 of 2,000 characters.');
    expect(counter().className).not.toContain('text-red');
    expect(fixIt().disabled).toBe(false);
  });

  it('over the limit: says so, in words, and turns Fix it off instead of cutting the text', async () => {
    renderApp();
    paste(big(5000));
    expect(counter().textContent).toBe(
      '5,000 of 2,000 characters. That is too long for Fix a citation. Paste one citation at a time, ' +
        'or use Check a document for a longer text.'
    );
    expect(counter().className).toContain('text-red');
    expect(fixIt().disabled).toBe(true);
    expect(box().getAttribute('aria-invalid')).toBe('true');
    expect(box().getAttribute('aria-describedby')).toBe('citation-count');
    // Neither the keyboard shortcut nor the style buttons send anything.
    fireEvent.keyDown(box(), { key: 'Enter', ctrlKey: true });
    fireEvent.click(screen.getByRole('radio', { name: /Court document/ }));
    await settle();
    expect(ctx.server.count('/api/repair')).toBe(0);
    expect(box().value).toHaveLength(5000);
  });

  it('is on again as soon as the text fits', () => {
    renderApp();
    paste(big(2001));
    expect(fixIt().disabled).toBe(true);
    paste(big(2000));
    expect(fixIt().disabled).toBe(false);
    expect(screen.queryByText(/too long/)).toBeNull();
  });

  it('announces the limit once, not on every key', () => {
    renderApp();
    const status = () => within(document.body).getAllByRole('status').map((s) => s.textContent).join('|');
    paste(big(100));
    const quiet = status();
    expect(quiet).not.toMatch(/limit/);
    paste(big(1700));
    expect(status()).toContain('Close to the 2,000 character limit.');
    paste(big(1800));
    expect(status()).toContain('Close to the 2,000 character limit.');
    paste(big(2100));
    expect(status()).toContain('Over the 2,000 character limit. Fix it is off until the text is shorter.');
  });

  it('counts characters as the server does, not UTF-16 units: 1,700 emoji are 1,700 characters', () => {
    renderApp();
    paste('\u{1F600}'.repeat(1700)); // 3,400 UTF-16 units
    expect(counter().textContent).toBe('1,700 of 2,000 characters.');
    expect(fixIt().disabled).toBe(false);
    paste('\u{1F600}'.repeat(2001));
    expect(fixIt().disabled).toBe(true);
  });

  it('uses the limit the server reports, if it reports one', async () => {
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', limits: { max_repair_chars: 300 } }));
    renderApp();
    await settle();
    paste(big(301));
    expect(fixIt().disabled).toBe(true);
    expect(counter().textContent).toContain('301 of 300 characters');
  });
});

describe('when a request fails, the page says why in plain words', () => {
  const ctx = setup();

  it('a phone with no connection is told so, and the server is not blamed or probed', async () => {
    vi.stubGlobal('navigator', { onLine: false });
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByRole('alert');
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('You appear to be offline. Check your connection and try again.');
    expect(alert).not.toMatch(/allowed|origin|server may|asleep/i);
    expect(ctx.server.count('/api/repair')).toBe(0);
    // /health was asked once, when the page loaded, and not again to find out what went wrong.
    expect(ctx.server.count('/health')).toBeLessThanOrEqual(1);
    // The result worked out in the browser is still there.
    expect(screen.getByText(/What the finished citation looks like/)).toBeTruthy();
  });

  it('a server that does not answer is described without a word about origins', async () => {
    ctx.server.on('/api/repair', () => { throw networkError(); });
    ctx.server.on('/health', () => { throw networkError(); });
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByRole('alert', {}, { timeout: 3000 });
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('The citation server is not answering.');
    expect(alert).toContain('It may be asleep or starting up. Wait a minute and try again.');
    expect(alert).not.toMatch(/allowed|origin|localhost/i);
    expect(console.error).toHaveBeenCalledWith(expect.stringContaining('allowed-origins'), expect.anything());
  });

  it('a busy server (503 with Retry-After) makes Try again wait, as the document path does', async () => {
    vi.useFakeTimers();
    globalThis.jest = { advanceTimersByTime: (ms) => vi.advanceTimersByTime(ms) };
    ctx.server.sequence('/api/repair', [
      () => json({ detail: 'The server is busy.' }, 503, { 'Retry-After': '30' }),
      () => json(resolvedReply()),
    ]);
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await advance(100);
    const button = screen.getByRole('button', { name: 'Try again in 30 s' });
    expect(button.disabled).toBe(true);
    await advance(10000);
    expect(screen.getByRole('button', { name: 'Try again in 20 s' }).disabled).toBe(true);
    await advance(20000);
    const ready = screen.getByRole('button', { name: 'Try again' });
    expect(ready.disabled).toBe(false);
    fireEvent.click(ready);
    await advance(100);
    expect(screen.getByText(/Verify on CourtListener/)).toBeTruthy();
    expect(ctx.server.count('/api/repair')).toBe(2);
  });

  it('a 500 can be tried again at once', async () => {
    ctx.server.on('/api/repair', () => json({ detail: 'The server hit an error.' }, 500));
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByRole('alert');
    expect(tryAgain().disabled).toBe(false);
  });
});

describe('an answer the page cannot draw leaves the result that was worked out in the browser', () => {
  const ctx = setup();

  it.each([
    ['an empty object', {}],
    ['null', null],
    ['an array', []],
    ['only a status', { status: 'incomplete' }],
    ['lists that are not lists', { ...incompleteReply(), missing_details: 'year', candidates: {}, notes: 3 }],
    ['a candidate with no link', { ...ambiguousReply(), candidates: [{ label: 'x' }] }],
  ])('%s', async (_label, body) => {
    ctx.server.on('/api/repair', () => json(body));
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(UNEXPECTED_FORMAT_MESSAGE);
    expect(alert.textContent).toContain('still correct');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeTruthy();
    // The browser's own result is still on screen: the missing fields, in the finished shape.
    expect(screen.getByText('Missing information')).toBeTruthy();
    expect(screen.getByText(/What the finished citation looks like/)).toBeTruthy();
    expect(screen.getAllByText('volume number').length).toBeGreaterThan(0);
  });

  it('then Try again can succeed once the server has finished updating', async () => {
    ctx.server.sequence('/api/repair', [() => json({}), () => json(resolvedReply())]);
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByRole('alert');
    fireEvent.click(tryAgain());
    expect(await screen.findByText(/Verify on CourtListener/)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('a real answer is drawn', async () => {
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    expect(await screen.findByText('Ready to use')).toBeTruthy();
    expect(screen.getByText(/603 U\.S\. 707/)).toBeTruthy();
  });
});

describe('Clear and an empty paste cancel what is running, and an old answer never shows', () => {
  const ctx = setup();
  const reply = resolvedReply();

  it('Clear while checking: the answer for the cleared text does not come back, and Fix it is not stuck', async () => {
    const slow = deferred();
    ctx.server.on('/api/repair', () => slow.promise);
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await settle();
    expect(ctx.server.count('/api/repair')).toBe(1);
    expect(fixIt().textContent).toBe('Checking...');
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(box().value).toBe('');
    // Loading is reset, so nothing waits for the answer.
    paste('U.S. Const. amend. XIV');
    expect(fixIt().textContent).toBe('Fix it');
    expect(fixIt().disabled).toBe(false);
    // The request itself was cancelled, not just ignored.
    expect(ctx.server.callsTo('/api/repair')[0].signal.aborted).toBe(true);
    await act(async () => { slow.resolve(json(reply)); });
    await settle();
    expect(screen.queryByText(/603 U\.S\. 707/)).toBeNull();
    expect(screen.queryByText('Ready to use')).toBeNull();
    expect(alerts()).toEqual([]);
  });

  it('Clear while checking, and the failure that follows the cancel, shows nothing', async () => {
    ctx.server.on('/api/repair', () => new Promise(() => {}));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await settle(60);
    expect(alerts()).toEqual([]);
    expect(ctx.server.count('/health')).toBe(1); // only the one at page load: no probe after a cancel
  });

  it('an empty paste submitted while checking cancels it and clears the result', async () => {
    const slow = deferred();
    ctx.server.on('/api/repair', () => slow.promise);
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await settle();
    paste('');
    fireEvent.keyDown(box(), { key: 'Enter', ctrlKey: true });
    expect(ctx.server.callsTo('/api/repair')[0].signal.aborted).toBe(true);
    await act(async () => { slow.resolve(json(reply)); });
    await settle();
    expect(screen.queryByText(/603 U\.S\. 707/)).toBeNull();
    expect(screen.getByText('Try one of these')).toBeTruthy();
    paste('Moody v. NetChoice');
    expect(fixIt().disabled).toBe(false);
  });

  it('an error that is explained after a newer request has succeeded is not shown', async () => {
    const health = deferred();
    ctx.server.sequence('/api/repair', [() => { throw networkError(); }, () => json(reply)]);
    // After the page's own first call, /health is slow: diagnose() waits on it.
    let calls = 0;
    ctx.server.on('/health', () => {
      calls += 1;
      return calls === 1 ? json({ status: 'healthy', boot_id: 'a' }) : health.promise;
    });
    renderApp();
    paste('Moody v. NetChoice');
    submit(); // run A fails, and its explanation starts
    await settle();
    // The person chooses the other style, which starts run B; B succeeds.
    fireEvent.click(screen.getByRole('radio', { name: /Court document/ }));
    await settle();
    expect(screen.getByText(/603 U\.S\. 707/)).toBeTruthy();
    // Now the probe for run A finishes.
    await act(async () => { health.resolve(json({ status: 'healthy', boot_id: 'x', endpoints: ['/api/repair'] })); });
    await settle();
    expect(alerts()).toEqual([]);
    expect(screen.getByText(/603 U\.S\. 707/)).toBeTruthy();
  });

  it('a failure of the newer request is still shown, not swallowed by the older one', async () => {
    ctx.server.sequence('/api/repair', [() => json(reply), () => json({ detail: 'The server hit an error.' }, 500)]);
    ctx.server.on('/health', () => json({ status: 'healthy', boot_id: 'a', endpoints: ['/api/repair'] }));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByText(/603 U\.S\. 707/);
    fireEvent.click(screen.getByRole('radio', { name: /Court document/ }));
    await screen.findByRole('alert');
    expect(alerts()[0]).toContain('The server hit an error.');
  });
});

describe('a result is tied to the text it was worked out for', () => {
  const ctx = setup();

  it('typing after a result marks it as for the earlier text, and Copy is off', async () => {
    renderApp();
    paste(BROWN);
    submit();
    await screen.findByText('Ready to use');
    expect(screen.queryByTestId('stale-note')).toBeNull();
    expect(screen.getByRole('button', { name: 'Copy' }).disabled).toBe(false);

    paste(`${BROWN} and more`);
    expect(screen.getByTestId('stale-note').textContent).toBe(
      'This result is for the text before you changed it. Press Fix it to update it.'
    );
    expect(screen.getByRole('button', { name: 'Copy' }).disabled).toBe(true);

    // Going back to the same text makes it current again; so does asking again.
    paste(BROWN);
    expect(screen.queryByTestId('stale-note')).toBeNull();
    paste(MARBURY);
    expect(screen.getByTestId('stale-note')).toBeTruthy();
    submit();
    await settle();
    expect(screen.queryByTestId('stale-note')).toBeNull();
    expect(screen.getByText(/Marbury v\. Madison/, { selector: 'em' })).toBeTruthy();
  });

  it('an answer for text that has since been changed is not shown as current', async () => {
    const slow = deferred();
    ctx.server.on('/api/repair', () => slow.promise);
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await settle();
    paste('Moody v. NetChoice, 603 U.S. 707 (2024)'); // typed while it was checking
    await act(async () => { slow.resolve(json(resolvedReply())); });
    await settle();
    expect(screen.getByTestId('stale-note')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy' }).disabled).toBe(true);
  });

  it('a result for one style is not offered as current for the other when the page cannot ask again', async () => {
    renderApp();
    paste(BROWN);
    submit();
    await screen.findByText('Ready to use');
    paste(`${BROWN}; `.repeat(200)); // too long: choosing a style cannot run
    fireEvent.click(screen.getByRole('radio', { name: /Court document/ }));
    await settle();
    expect(screen.getByTestId('stale-note')).toBeTruthy();
    expect(ctx.server.count('/api/repair')).toBe(0);
  });
});

describe('links the server supplies are only links when they are http or https', () => {
  const ctx = setup();

  it('draws a verify link with its address, in a new tab, without handing over the page', async () => {
    ctx.server.on('/api/repair', () => json(resolvedReply()));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    const link = await screen.findByRole('link', { name: 'Verify on CourtListener' });
    expect(link.getAttribute('href')).toBe('https://www.courtlistener.com/opinion/9999999/moody-v-netchoice-llc/');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it.each([
    ['javascript:', 'javascript:alert(1)'],
    ['JaVaScRiPt: in mixed case', 'JaVaScRiPt:alert(1)'],
    ['javascript: after whitespace', '  \tjavascript:alert(1)'],
    ['data:', 'data:text/html,<script>alert(1)</script>'],
    ['vbscript:', 'vbscript:msgbox(1)'],
  ])('draws no verify link for %s', async (_label, url) => {
    ctx.server.on('/api/repair', () => json(resolvedReply({ verify_url: url })));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByText('Ready to use');
    expect(screen.queryByRole('link', { name: /Verify on/ })).toBeNull();
    expect(window.document.querySelector('a[href^="javascript" i], a[href^="data" i], a[href^="vbscript" i]')).toBeNull();
    // The citation itself is still shown.
    expect(screen.getByText(/603 U\.S\. 707/)).toBeTruthy();
  });

  it('draws a candidate’s link only for http and https, and the candidate itself either way', async () => {
    const reply = ambiguousReply({
      candidates: [
        { label: 'Good candidate', court: 'Supreme Court', date: '2024', verify_url: 'https://www.courtlistener.com/opinion/1/' },
        { label: 'Bad candidate', court: 'Nowhere', date: '2023', verify_url: 'javascript:alert(document.cookie)' },
      ],
    });
    ctx.server.on('/api/repair', () => json(reply));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByText('Needs your choice');
    const links = screen.getAllByRole('link', { name: 'Open source' });
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toBe('https://www.courtlistener.com/opinion/1/');
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer');
    expect(screen.getByText('Bad candidate')).toBeTruthy();
  });

  it('two candidates that share an address are both drawn', async () => {
    const same = { label: 'Same', court: 'A', date: '2024', verify_url: 'https://www.courtlistener.com/opinion/1/' };
    ctx.server.on('/api/repair', () => json(ambiguousReply({ candidates: [same, { ...same, court: 'B' }] })));
    renderApp();
    paste('Moody v. NetChoice');
    submit();
    await screen.findByText('Needs your choice');
    expect(screen.getAllByRole('link', { name: 'Open source' })).toHaveLength(2);
  });
});
