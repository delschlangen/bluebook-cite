// @vitest-environment jsdom
// The page checks what /api/repair answers before it draws it (see api.js). This is the second
// line: if a reply with a list that is not a list ever got past that, drawing it must not throw
// (the error boundary would replace the whole page).
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import CitationRepair from '../CitationRepair';
import * as api from '../../services/api';
import { incompleteReply } from '../../test/repairReplies';

vi.mock('../../services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  repairCitation: vi.fn(),
  checkHealth: vi.fn(async () => null),
}));

beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function showWhatTheServerSaid(reply) {
  api.repairCitation.mockResolvedValue(reply);
  render(<CitationRepair />);
  fireEvent.change(screen.getByLabelText('Citation to repair'), { target: { value: 'Moody v. NetChoice' } });
  fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
  await screen.findByText('Missing information');
  await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Checking...' })).toBeNull());
}

describe('a reply with lists that are not lists does not take the page down', () => {
  it.each([
    ['missing_details that is text', { missing_details: 'year' }],
    ['missing_details that is an object', { missing_details: { label: 'year' } }],
    ['candidates that is text', { candidates: 'none' }],
    ['candidates that is a number', { candidates: 3 }],
    ['notes that is text', { notes: 'a note' }],
    ['notes that is an object', { notes: { a: 1 } }],
    ['all three at once', { missing_details: 'a', candidates: 'b', notes: 'c' }],
  ])('%s', async (_label, wrong) => {
    await showWhatTheServerSaid(incompleteReply(wrong));
    // Drawn without the part that was wrong, and the rest of the card is there.
    expect(screen.getByText('Missing information')).toBeTruthy();
    expect(screen.queryByText('This page stopped working')).toBeNull();
  });

  it('a citation_type that is not text does not throw while the label is made', async () => {
    await showWhatTheServerSaid(incompleteReply({ citation_type: 4 }));
    expect(screen.getByText('Missing information')).toBeTruthy();
  });

  it('a list that is fine is still drawn', async () => {
    await showWhatTheServerSaid(incompleteReply());
    expect(screen.getAllByText('volume number').length).toBeGreaterThan(0);
    expect(screen.getByText(/No matching record was found in CourtListener/)).toBeTruthy();
  });
});
