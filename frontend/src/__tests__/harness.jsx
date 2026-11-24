// @vitest-environment jsdom
// Shared setup for the tests that render the whole page against a fake backend.
import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, vi } from 'vitest';
import App from '../App';
import { resetServerKnowledge } from '../services/api';
import { createFakeServer, json } from '../test/fakeServer';
import { analysisBody, uploadBody } from '../test/fixtures';

export const MB = 1024 * 1024;

/** A file with the given name, and a size to claim (the content stays tiny). */
export function file(name = 'brief.txt', size) {
  const f = new File(['Brown v. Board of Education'], name, { type: 'text/plain' });
  if (size !== undefined) Object.defineProperty(f, 'size', { value: size });
  return f;
}

export function setup({ fakeTimers = false } = {}) {
  const ctx = { server: null, user: null, bootId: 'boot-A' };

  beforeEach(() => {
    resetServerKnowledge();
    if (fakeTimers) {
      vi.useFakeTimers();
      // Testing Library only drives fake timers it can recognise as Jest's; tell it these are.
      globalThis.jest = { advanceTimersByTime: (ms) => vi.advanceTimersByTime(ms) };
    }
    ctx.bootId = 'boot-A';
    ctx.server = createFakeServer()
      .on('/health', () => json({ status: 'healthy', boot_id: ctx.bootId }))
      .on('/api/upload', () => json(uploadBody()))
      .on('/api/analyze', () => json(analysisBody()));
    vi.stubGlobal('fetch', ctx.server.fetch);
    ctx.user = userEvent.setup({
      applyAccept: false,
      ...(fakeTimers ? { advanceTimers: (ms) => vi.advanceTimersByTime(ms) } : {}),
    });
    // The page reports failures with console.error; the tests look at the page instead.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.document.body.style.overflow = '';
    delete globalThis.jest;
  });

  return ctx;
}

export const renderApp = () => render(<App />);

// A results tab's name includes its count ("Unsourced Claims 8003"), so match from the start.
export const tab = (name) => screen.getByRole('tab', { name: new RegExp(`^${name}`) });
export const fileInput = () => screen.getByLabelText('Choose a document to check');
export const results = () => screen.queryByText('Analysis Summary');

/** Open the "Check a document" panel and choose a file. */
export async function chooseFile(ctx, f = file(), { open = true } = {}) {
  if (open) await ctx.user.click(tab('Check a document'));
  await ctx.user.upload(fileInput(), f);
}

/** Wait for the page to settle on its results. */
export const findResults = () => screen.findByText('Analysis Summary');

/** Let pending promises and zero-delay timers settle, inside act. */
export const tick = (ms = 20) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

/** The same, for tests that run on fake timers. */
export const advance = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

export const visible = (element) => Boolean(element) && !element.closest('[hidden]');
