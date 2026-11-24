// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import { advance, chooseFile, fileInput, file, findResults, renderApp, results, setup, tab, tick } from './harness';
import { json, networkError } from '../test/fakeServer';
import { analysisBody, many } from '../test/fixtures';

const OFFLINE = 'You appear to be offline. Check your connection and try again.';
const goOffline = (online = { value: false }) =>
  vi.spyOn(window.navigator, 'onLine', 'get').mockImplementation(() => online.value);

describe('a phone with no connection is told so at once', () => {
  const ctx = setup();

  it('on upload: the sentence is shown without probing the server or waiting', async () => {
    renderApp();
    await ctx.user.click(tab('Check a document'));
    goOffline();
    await ctx.user.upload(fileInput(), file());

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(OFFLINE);
    expect(ctx.server.count('/api/upload')).toBe(0);
    expect(ctx.server.count('/health')).toBe(1); // the one at page load, none to find out
    expect(screen.queryByText(/Checking whether the server/)).toBeNull();
    expect(screen.queryByText(/may be down/)).toBeNull();
  });

  it('on analysis: Try again while offline says so at once and sends nothing', async () => {
    ctx.server.sequence('/api/analyze', [() => json({ detail: 'The server hit an unexpected error.' }, 500)]);
    renderApp();
    await chooseFile(ctx);
    await screen.findByRole('alert');
    goOffline();
    await ctx.user.click(screen.getByRole('button', { name: 'Try again' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(OFFLINE);
    expect(ctx.server.count('/api/analyze')).toBe(1);
    expect(ctx.server.count('/health')).toBe(1);
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('when the connection drops during the analysis, says so instead of that the server may be down', async () => {
    const online = { value: true };
    goOffline(online);
    ctx.server.on('/api/analyze', () => {
      online.value = false;
      throw networkError();
    });
    renderApp();
    await chooseFile(ctx);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(OFFLINE);
    expect(ctx.server.count('/health')).toBe(1);
  });

  it('Try again works once the connection is back', async () => {
    const online = { value: true };
    goOffline(online);
    ctx.server.sequence('/api/analyze', [
      () => {
        online.value = false;
        throw networkError();
      },
      () => json(analysisBody({ citations: many(2) })),
    ]);
    renderApp();
    await chooseFile(ctx);
    await screen.findByRole('alert');
    online.value = true;
    await ctx.user.click(screen.getByRole('button', { name: 'Try again' }));
    await findResults();
  });
});

describe('while the page finds out why a request did not finish', () => {
  const ctx = setup({ fakeTimers: true });
  const downServer = () => {
    ctx.server.on('/health', () => {
      throw networkError();
    });
  };

  it('says it can take up to half a minute, offers Cancel, and gives up with an honest message', async () => {
    ctx.server.on('/api/analyze', () => {
      throw networkError();
    });
    renderApp();
    await advance(10); // the first /health, answered
    downServer();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(fileInput(), file());
    await advance(1000);

    expect(screen.getByText('Checking whether the server is still running...')).toBeTruthy();
    expect(screen.getByText('The request did not finish. This can take up to half a minute.')).toBeTruthy();
    expect(screen.queryByText(/few seconds/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();

    await advance(30000);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toBe(
      'Failed to analyze document: the server did not answer. It may be down. Wait a minute and try again.'
    );
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('Cancel stops the probing at once: no more requests are sent, and the document stays', async () => {
    ctx.server.on('/api/analyze', () => {
      throw networkError();
    });
    renderApp();
    await advance(10);
    downServer();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(fileInput(), file());
    await advance(1000);
    const probesBefore = ctx.server.count('/health');
    expect(probesBefore).toBeGreaterThan(1);

    await ctx.user.click(screen.getByRole('button', { name: 'Cancel' }));
    await advance(40000);
    expect(ctx.server.count('/health')).toBe(probesBefore);
    expect(screen.getByRole('alert').textContent).toBe(
      'Stopped before the analysis finished. Your document is still loaded. Try again when you are ready.'
    );
    expect(screen.queryByText('Checking whether the server is still running...')).toBeNull();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('the upload box says it is checking, not that it is uploading 0.0 MB, and has Cancel', async () => {
    ctx.server.on('/api/upload', () => {
      throw networkError();
    });
    renderApp();
    await advance(10);
    downServer();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(fileInput(), file());
    await advance(1000);

    expect(
      screen.getByText(
        'The upload did not finish. Checking whether the server is still running... This can take up to half a minute.'
      )
    ).toBeTruthy();
    expect(screen.queryByText(/Uploading/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
    expect(tab('Fix a citation').disabled).toBe(true);
  });

  it('Cancel during the upload check stops the probing and leaves a note', async () => {
    ctx.server.on('/api/upload', () => {
      throw networkError();
    });
    renderApp();
    await advance(10);
    downServer();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(fileInput(), file());
    await advance(1000);
    const probesBefore = ctx.server.count('/health');

    await ctx.user.click(screen.getByRole('button', { name: 'Cancel' }));
    await advance(40000);
    expect(ctx.server.count('/health')).toBe(probesBefore);
    expect(screen.getByTestId('upload-notice').textContent).toBe('Upload cancelled. Choose the file again to start over.');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(tab('Fix a citation').disabled).toBe(false);
  });

  it('an upload check that gets no answer ends with the honest message, after about half a minute', async () => {
    ctx.server.on('/api/upload', () => {
      throw networkError();
    });
    renderApp();
    await advance(10);
    downServer();
    await ctx.user.click(tab('Check a document'));
    await ctx.user.upload(fileInput(), file());
    await advance(5000);
    expect(screen.queryByRole('alert')).toBeNull();
    await advance(30000);
    expect(screen.getByRole('alert').textContent).toBe(
      'The upload failed: the server did not answer. It may be down. Wait a minute and try again.'
    );
    expect(results()).toBeNull();
  });
});
