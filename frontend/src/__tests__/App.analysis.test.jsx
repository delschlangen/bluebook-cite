// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { act, screen } from '@testing-library/react';
import { chooseFile, advance, findResults, renderApp, results, setup, tab, tick, visible } from './harness';
import { deferred, json, networkError } from '../test/fakeServer';
import { analysisBody, citation, claim, many, uploadBody } from '../test/fixtures';

const total = () => screen.getByText('Total Citations').previousSibling.textContent;
const reset = (user) => user.click(screen.getByRole('button', { name: 'Upload New Document' }));
const tryAgain = () => screen.queryByRole('button', { name: /Try again/ });

describe('a run that was reset or replaced cannot change the page', () => {
  const ctx = setup();

  it('an old answer that arrives after a newer document finished does not replace its results', async () => {
    const slow = deferred();
    ctx.server
      .sequence('/api/upload', [
        () => json(uploadBody({ document_id: 'doc-A', filename: 'a.txt' })),
        () => json(uploadBody({ document_id: 'doc-B', filename: 'b.txt' })),
      ])
      .sequence('/api/analyze', [() => slow.promise, () => json(analysisBody({ citations: many(3) }))], {
        ignoreAbort: true,
      });
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    await reset(ctx.user);
    await chooseFile(ctx, undefined, { open: false });
    await findResults();
    expect(total()).toBe('3');

    await act(async () => {
      slow.resolve(json(analysisBody({ citations: [citation(1)] })));
    });
    await tick();
    expect(total()).toBe('3');
    expect(screen.getByText('b.txt')).toBeTruthy();
  });

  it('an old failure that arrives after the person reset does not appear on the landing page', async () => {
    const slow = deferred();
    ctx.server.on('/api/analyze', () => slow.promise, { ignoreAbort: true });
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    await reset(ctx.user);

    await act(async () => {
      slow.resolve(json({ detail: 'The server hit an unexpected error.' }, 500));
    });
    await tick();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/Failed to analyze/)).toBeNull();
    expect(visible(tab('Check a document'))).toBe(true);
  });

  it('resetting aborts the request that is in flight', async () => {
    ctx.server.on('/api/analyze', () => new Promise(() => {}));
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    const [call] = ctx.server.callsTo('/api/analyze');
    expect(call.signal.aborted).toBe(false);
    await reset(ctx.user);
    expect(call.signal.aborted).toBe(true);
  });

  it('the answer of a replaced run does not clear the spinner of the run that replaced it', async () => {
    const first = deferred();
    const second = deferred();
    ctx.server.sequence('/api/analyze', [() => first.promise, () => second.promise], { ignoreAbort: true });
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    await reset(ctx.user);
    await chooseFile(ctx, undefined, { open: false });
    await screen.findByText('Analyzing citations...');

    await act(async () => {
      first.resolve(json({ detail: 'old failure' }, 500));
    });
    await tick();
    expect(screen.getByText('Analyzing citations...')).toBeTruthy();

    await act(async () => {
      second.resolve(json(analysisBody({ citations: many(2) })));
    });
    await findResults();
    expect(total()).toBe('2');
  });

  it('Cancel stops the wait, keeps the document, and says so instead of reporting an error', async () => {
    ctx.server.sequence('/api/analyze', [() => new Promise(() => {}), () => json(analysisBody({ citations: many(4) }))]);
    renderApp();
    await chooseFile(ctx);
    await screen.findByText('Analyzing citations...');
    await ctx.user.click(screen.getByRole('button', { name: 'Cancel' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Stopped before the analysis finished. Your document is still loaded. Try again when you are ready.'
    );
    expect(alert.textContent).not.toContain('Failed');
    expect(results()).toBeNull();

    await ctx.user.click(tryAgain());
    await findResults();
    expect(total()).toBe('4');
    expect(ctx.server.count('/api/upload')).toBe(1);
  });
});

describe('Try again and what it is told about the failure', () => {
  const ctx = setup();

  it('after a server error, Try again runs the analysis again without uploading again', async () => {
    ctx.server.sequence('/api/analyze', [
      () => json({ detail: 'The server hit an unexpected error while processing this request. (error ab12)' }, 500),
      () => json(analysisBody({ citations: many(5) })),
    ]);
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Failed to analyze document: The server hit an unexpected error while processing this request. (error ab12)'
    );
    await ctx.user.click(tryAgain());
    await findResults();
    expect(total()).toBe('5');
    expect(ctx.server.count('/api/analyze')).toBe(2);
    expect(ctx.server.count('/api/upload')).toBe(1);
    expect(screen.queryByRole('alert')).toBeNull();
    // The second request carried the same document.
    const bodies = ctx.server.callsTo('/api/analyze').map((c) => JSON.parse(c.body));
    expect(bodies[1]).toEqual(bodies[0]);
  });

  it('a failure with no response asks the server what happened before blaming anyone', async () => {
    ctx.server.on('/api/analyze', () => {
      throw networkError();
    });
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(ctx.server.count('/health')).toBe(2); // once at load, once to find out
    expect(alert.textContent).toBe(
      'Failed to analyze document: the server is running, but this request did not complete. It may ' +
        'have taken too long on a slow connection, or the connection dropped. Try again, and if it keeps ' +
        'happening try a smaller file.'
    );
    expect(tryAgain()).not.toBeNull();
  });

  it('says the server restarted while working on the document when the id changed after the request had been running a while', async () => {
    // The clock is moved by the route itself: the request was in flight for four seconds.
    let clock = 1_800_000_000_000;
    vi.spyOn(Date, 'now').mockImplementation(() => clock);
    ctx.server.sequence('/api/analyze', [
      () => {
        clock += 4000;
        ctx.bootId = 'boot-B';
        throw networkError();
      },
      () => json(analysisBody({ citations: many(2) })),
    ]);
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Failed to analyze document: the server restarted while working on your document. That can happen ' +
        'when the document is very large, or when the server was updated at that moment. Try again; if it ' +
        'happens again with this document, split it.'
    );
    expect(alert.textContent).not.toContain('too large or complex');
    await ctx.user.click(tryAgain());
    await findResults();
  });

  it('does not tell the person to split the document when the request was refused at once', async () => {
    // Connection refused: the id differs, but the document never reached the server.
    ctx.server.sequence('/api/analyze', [
      () => {
        ctx.bootId = 'boot-B';
        throw networkError();
      },
      () => json(analysisBody({ citations: many(2) })),
    ]);
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Failed to analyze document. The server was not running when this was sent, so it never received ' +
        'your document. It is back now. Try again.'
    );
    expect(alert.textContent).not.toContain('split it');
    expect(alert.textContent).not.toContain('while working on your document');
    await ctx.user.click(tryAgain());
    await findResults();
  });

  it('does not claim a restart when it never saw the server before the request failed', async () => {
    // The first /health, at page load, never answered, so there is no earlier id to compare with.
    let healthCalls = 0;
    ctx.server.on('/health', () => {
      healthCalls += 1;
      if (healthCalls === 1) throw networkError();
      return json({ boot_id: 'boot-B' });
    });
    ctx.server.on('/api/analyze', () => {
      throw networkError();
    });
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('the server is running, but this request did not complete');
    expect(alert.textContent).not.toContain('restarted');
  });

  it('shows the analysis as soon as the server answers, and the stats it gave', async () => {
    ctx.server.on(
      '/api/analyze',
      () => json(analysisBody({ citations: many(3), claims: [claim(1)], stats: { complete: 2, incomplete: 1 } }))
    );
    renderApp();
    await chooseFile(ctx);
    await findResults();
    expect(screen.getByText('Complete').previousSibling.textContent).toBe('2');
    expect(screen.getByText('Incomplete').previousSibling.textContent).toBe('1');
    expect(screen.getByText('Unsourced Claims', { selector: 'div' }).previousSibling.textContent).toBe('1');
  });

  it('puts a long file name in the summary without a way to widen the page', async () => {
    const name = 'Smith_v_Jones_Defendants_Motion_to_Dismiss_FINAL_v7_edited_2024-11-03_signed_by_partner.txt';
    ctx.server.on('/api/upload', () => json(uploadBody({ filename: name })));
    renderApp();
    await chooseFile(ctx);
    await findResults();
    const label = screen.getByText(name);
    expect(label.className).toContain('wrap-anywhere');
    expect(label.className).toContain('min-w-0');
    // Its row may wrap, so the name never has to sit beside the heading.
    expect(label.parentElement.className).toContain('flex-wrap');
  });
});

describe('what the page tells the person is cut or unchecked', () => {
  const ctx = setup();

  it('says how many citations are shown, how the lookups went, and how many claims are shown', async () => {
    ctx.server.on(
      '/api/analyze',
      () =>
        json(
          analysisBody({
            citations: many(3),
            claims: many(2, claim),
            stats: { total_citations: 2450, citations_shown: 3, unsourced_claims: 8003, claims_shown: 2 },
            lookup: { eligible: 218, completed: 200, skipped: 18, matched: 150, failed: 30, budget_exhausted: false },
          })
        )
    );
    renderApp();
    await chooseFile(ctx);
    await findResults();
    expect(screen.getByText('Found 2,450 citations. Showing the first 3, in document order.')).toBeTruthy();
    expect(
      screen.getByText(
        'Checked 200 of 218 incomplete citations in outside sources: 150 matched, 30 could not be reached. ' +
          'The rest, and any that did not match, need checking by hand.'
      )
    ).toBeTruthy();

    await ctx.user.click(tab('Unsourced Claims'));
    expect(screen.getByTestId('claims-notice').textContent).toBe(
      'Found 8,003 statements that may need a citation. Showing the 2 most likely.'
    );
  });

  it('shows what the upload warned about, and how many footnotes were read', async () => {
    ctx.server.on(
      '/api/upload',
      () => json(uploadBody({ footnote_count: 1, endnote_count: 2, warnings: ['2 page(s) of this PDF could not be read and were skipped.'] }))
    );
    renderApp();
    await chooseFile(ctx);
    await findResults();
    expect(screen.getByText(/Read 1 footnote and 2 endnotes from the Word file\./)).toBeTruthy();
    expect(screen.getByText('2 page(s) of this PDF could not be read and were skipped.')).toBeTruthy();
  });
});

describe('an answer the page cannot read is reported, not rendered', () => {
  const ctx = setup();

  it.each([
    ['an empty object', () => json({})],
    ['stats missing', () => json({ ...analysisBody(), stats: undefined })],
    ['citations that are not a list', () => json({ ...analysisBody(), analysis: { citations: 'none', unsourced_claims: [] } })],
    ['a citation without a status', () => json(analysisBody({ citations: [{ ...citation(1), status: undefined }] }))],
    ['a page that is not JSON at all', () => new Response('<html>Bad gateway</html>', { status: 200 })],
  ])('with %s the page says so and offers Try again, and does not go blank', async (_name, answer) => {
    ctx.server.on('/api/analyze', answer);
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(
      'The server answered in a format this page does not understand. It may be in the middle of an update. Wait a minute and try again.'
    );
    expect(tryAgain()).not.toBeNull();
    expect(screen.getByRole('heading', { name: 'Bluebook Citation Generator' })).toBeTruthy();
  });

  it('then Try again can still succeed when the server has finished updating', async () => {
    ctx.server.sequence('/api/analyze', [() => json({}), () => json(analysisBody({ citations: many(2) }))]);
    renderApp();
    await chooseFile(ctx);
    await screen.findByRole('alert');
    await ctx.user.click(tryAgain());
    await findResults();
    expect(total()).toBe('2');
  });

  it('an upload answer with no text is reported on the upload box, and no analysis is started', async () => {
    ctx.server.on('/api/upload', () => json({ filename: 'a.txt' }));
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The server answered in a format this page does not understand.');
    expect(ctx.server.count('/api/analyze')).toBe(0);
  });
});

describe('failures that Try again cannot fix say what to change instead', () => {
  const ctx = setup();

  it('a 413 offers no Try again and tells the person to shorten the document', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'This document has 1,700,000 characters, over the 1,500,000 limit.' }, 413));
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Failed to analyze document: This document has 1,700,000 characters, over the 1,500,000 limit.' +
        'Sending it again would be refused the same way. Use a shorter document, or split it at a chapter ' +
        'or section boundary and check the parts one at a time.'
    );
    expect(tryAgain()).toBeNull();
    expect(screen.getByRole('button', { name: 'Upload New Document' })).toBeTruthy();
  });

  it('a 504 offers no Try again and says to try a shorter document', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'The server took longer than 90 seconds to read this.' }, 504));
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(
      'Failed to analyze document: The server took longer than 90 seconds to read this.' +
        'Try a shorter document, or split it at a chapter or section boundary and check the parts one at a time.'
    );
    expect(tryAgain()).toBeNull();
  });

  it('a 504 whose own text already says "shorter document" is not told it twice', async () => {
    ctx.server.on('/api/analyze', () =>
      json({ detail: 'Analyzing took too long. Try a shorter document, or split it at a chapter.' }, 504)
    );
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent.match(/shorter document/g)).toHaveLength(1);
  });

  describe.each([[422], [401], [403]])('a %i, where the page and the server are out of step', (status) => {
    const reloadSpy = () => {
      const reload = vi.fn();
      vi.stubGlobal('location', { ...window.location, reload });
      return reload;
    };

    it('offers Reload page, not Try again, and says the document will need choosing again', async () => {
      ctx.server.on('/api/analyze', () => json([{ loc: ['body', 'text'], msg: 'field required' }], status));
      renderApp();
      await chooseFile(ctx);
      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toContain('Reload the page and try again.');
      expect(alert.textContent).toContain('you will need to choose it again');
      expect(alert.textContent).not.toContain('Upload New Document');
      expect(tryAgain()).toBeNull();
      expect(screen.getByRole('button', { name: 'Reload page' }).className).toContain('min-h-[44px]');
    });

    it('Reload page reloads the page, and Try again was never sent', async () => {
      ctx.server.on('/api/analyze', () => json({ detail: 'no' }, status));
      const reload = reloadSpy();
      renderApp();
      await chooseFile(ctx);
      await screen.findByRole('alert');
      expect(ctx.server.count('/api/analyze')).toBe(1);
      await ctx.user.click(screen.getByRole('button', { name: 'Reload page' }));
      expect(reload).toHaveBeenCalledTimes(1);
      expect(ctx.server.count('/api/analyze')).toBe(1);
    });
  });

  it('a 500 and a 400 do not ask for a reload', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'The PDF is encrypted.' }, 400));
    renderApp();
    await chooseFile(ctx);
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'Reload page' })).toBeNull();
    expect(tryAgain()).not.toBeNull();
  });

  it('a 500 still offers Try again', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'The server hit an unexpected error.' }, 500));
    renderApp();
    await chooseFile(ctx);
    await screen.findByRole('alert');
    expect(tryAgain()).not.toBeNull();
  });
});

describe('a busy server says how long to wait, and the button waits that long', () => {
  const ctx = setup({ fakeTimers: true });

  it('counts down the Retry-After the server sent, then lets the person try again', async () => {
    ctx.server.sequence('/api/analyze', [
      () => json({ detail: 'The server is busy analyzing other documents. Please try again in a minute.' }, 503, { 'Retry-After': '30' }),
      () => json(analysisBody({ citations: many(2) })),
    ]);
    renderApp();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(screen.getByLabelText('Choose a document to check'), new File(['x'], 'a.txt'));
    await advance(100);

    expect(screen.getByRole('alert').textContent).toContain('The server is busy analyzing other documents.');
    const button = screen.getByRole('button', { name: 'Try again in 30 s' });
    expect(button.disabled).toBe(true);

    await advance(10000);
    expect(screen.getByRole('button', { name: 'Try again in 20 s' }).disabled).toBe(true);
    await advance(19000);
    expect(screen.getByRole('button', { name: 'Try again in 1 s' }).disabled).toBe(true);
    await advance(1000);

    const ready = screen.getByRole('button', { name: 'Try again' });
    expect(ready.disabled).toBe(false);
    await ctx.user.click(ready);
    await advance(100);
    expect(results()).not.toBeNull();
    expect(ctx.server.count('/api/analyze')).toBe(2);
  });

  it('a busy answer with no Retry-After can be retried at once', async () => {
    ctx.server.on('/api/analyze', () => json({ detail: 'busy' }, 503));
    renderApp();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(screen.getByLabelText('Choose a document to check'), new File(['x'], 'a.txt'));
    await advance(100);
    expect(screen.getByRole('button', { name: 'Try again' }).disabled).toBe(false);
  });
});
