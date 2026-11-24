// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, screen } from '@testing-library/react';

afterEach(() => {
  cleanup();
  vi.resetModules();
  vi.doUnmock('../App.jsx');
  window.document.body.innerHTML = '';
});

// main.jsx is what the browser runs. It has to put the error boundary around the page, or a
// render error anywhere in it leaves a blank screen.
describe('main.jsx', () => {
  it('shows the error message instead of a blank page when the page itself throws on render', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.doMock('../App.jsx', () => ({
      default: () => {
        throw new Error('render failed');
      },
    }));
    window.document.body.innerHTML = '<div id="root"></div>';
    await import('../main.jsx');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('This page stopped working');
    expect(screen.getByRole('button', { name: 'Reload the page' })).toBeTruthy();
  });

  it('renders the page when nothing is wrong', async () => {
    vi.doMock('../App.jsx', () => ({ default: () => <h1>The page</h1> }));
    window.document.body.innerHTML = '<div id="root"></div>';
    await import('../main.jsx');
    expect(await screen.findByRole('heading', { name: 'The page' })).toBeTruthy();
  });
});
