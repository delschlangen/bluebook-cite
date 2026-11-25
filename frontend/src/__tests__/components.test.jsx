// @vitest-environment jsdom
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CitationList from '../components/CitationList';
import DocumentPreview from '../components/DocumentPreview';
import ErrorBoundary from '../components/ErrorBoundary';
import FileUpload from '../components/FileUpload';
import SourceSuggestions from '../components/SourceSuggestions';
import { citation, claim, many } from '../test/fixtures';
import * as citationText from '../utils/citationText';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const user = () => userEvent.setup();
const cardCount = () => window.document.querySelectorAll('[data-card-index]').length;
const claimCount = () => window.document.querySelectorAll('[data-claim-index]').length;

describe('CitationList pages through its citations', () => {
  const props = { shortFormSuggestions: [], onSelect: () => {} };

  it('Show more reveals the next page and says how many are left', async () => {
    render(<CitationList citations={many(250)} {...props} />);
    expect(cardCount()).toBe(100);
    await user().click(screen.getByRole('button', { name: 'Show 100 more (150 not shown)' }));
    expect(cardCount()).toBe(200);
    await user().click(screen.getByRole('button', { name: 'Show 50 more (50 not shown)' }));
    expect(cardCount()).toBe(250);
    expect(screen.queryByRole('button', { name: /Show/ })).toBeNull();
  });

  it('formats the numbers on the button with separators, not as the browser would', async () => {
    render(<CitationList citations={many(1500)} {...props} />);
    expect(screen.getByRole('button', { name: 'Show 100 more (1,400 not shown)' })).toBeTruthy();
  });

  it('can be told how many to show, and asks for more through the parent', async () => {
    const onShownChange = vi.fn();
    render(<CitationList citations={many(250)} shown={150} onShownChange={onShownChange} {...props} />);
    expect(cardCount()).toBe(150);
    await user().click(screen.getByRole('button', { name: 'Show 100 more (100 not shown)' }));
    expect(onShownChange).toHaveBeenCalledWith(250);
  });

  it('selecting a card does not render the cards that did not change again', async () => {
    const spy = vi.spyOn(citationText, 'renderCitation');
    const suggestions = many(100).map((c) => ({
      citation_id: c.id,
      suggested_form: `Id. at ${c.page}.`,
      short_form_type: 'id',
    }));
    const citations = many(100);
    const Harness = () => {
      const [selected, setSelected] = React.useState(null);
      const onSelect = React.useCallback((c) => setSelected(c.id), []);
      return <CitationList citations={citations} shortFormSuggestions={suggestions} onSelect={onSelect} selectedId={selected} />;
    };
    render(<Harness />);
    const afterFirstRender = spy.mock.calls.length;
    expect(afterFirstRender).toBeGreaterThanOrEqual(100); // every card drew its suggestion once

    await user().click(window.document.querySelector('[data-citation-id="c7"]'));
    // Only the card that became selected is drawn again, not the other 99.
    expect(spy.mock.calls.length - afterFirstRender).toBeLessThanOrEqual(2);

    const mid = spy.mock.calls.length;
    await user().click(window.document.querySelector('[data-citation-id="c9"]'));
    // The one that was selected and the one that is now: two cards.
    expect(spy.mock.calls.length - mid).toBeLessThanOrEqual(4);
  });

  it('numbers cards from one, and each card says which citation it is', () => {
    render(<CitationList citations={many(3)} {...props} />);
    const cards = window.document.querySelectorAll('[data-card-index]');
    expect([...cards].map((c) => c.getAttribute('data-citation-id'))).toEqual(['c1', 'c2', 'c3']);
    expect(within(cards[2]).getByText('#3')).toBeTruthy();
  });

  it('says so when there are none', () => {
    render(<CitationList citations={[]} {...props} />);
    expect(screen.getByText('No citations found in this document.')).toBeTruthy();
  });

  it('an edited citation shows its saved fields and what was found, an unedited one only what was found', () => {
    render(
      <CitationList
        citations={[citation(1, { edited: true, year: 1999 }), citation(2)]}
        {...props}
      />
    );
    const [first, second] = window.document.querySelectorAll('[data-card-index]');
    expect(within(first).getByText('Edited')).toBeTruthy();
    expect(within(first).getByTestId('edited-text').textContent).toContain('(1999)');
    expect(first.textContent).toContain('As found in the document: Brown v. Board of Education, 347 U.S. 1 (1954)');
    expect(within(second).queryByText('Edited')).toBeNull();
    expect(second.textContent).not.toContain('As found in the document');
  });
});

describe('CitationList: what is printed on a card', () => {
  const props = { shortFormSuggestions: [], onSelect: () => {} };
  const firstCard = () => window.document.querySelector('[data-card-index]');

  it('prints a footnote number, and nothing at all for footnote 0 (not a stray "0")', () => {
    render(<CitationList citations={[citation(1, { footnote_number: 3 }), citation(2, { footnote_number: 0 })]} {...props} />);
    const [first, second] = window.document.querySelectorAll('[data-card-index]');
    expect(within(first).getByText('Note 3')).toBeTruthy();
    expect(within(second).queryByText(/^Note/)).toBeNull();
    // `0 && <span>` would put the character 0 on the card, in the row of badges.
    const badges = second.querySelector('.flex.items-center.gap-2.mb-2');
    expect(badges.textContent).not.toMatch(/(^|\D)0($|\D)/);
    expect([...badges.childNodes].some((node) => node.nodeType === 3)).toBe(false);
  });

  it.each([[undefined], [null], [''], [-1]])('prints no note for a footnote number of %j', (value) => {
    render(<CitationList citations={[citation(1, { footnote_number: value })]} {...props} />);
    expect(within(firstCard()).queryByText(/^Note/)).toBeNull();
  });
});

describe('SourceSuggestions pages through its claims', () => {
  it('Show more reveals the next page and says how many are left', async () => {
    render(<SourceSuggestions claims={many(150, claim)} />);
    expect(claimCount()).toBe(100);
    await user().click(screen.getByRole('button', { name: 'Show 50 more (50 not shown)' }));
    expect(claimCount()).toBe(150);
    expect(screen.queryByRole('button', { name: /Show/ })).toBeNull();
  });

  it('announces how many are shown, and updates it when more are', async () => {
    render(<SourceSuggestions claims={many(150, claim)} />);
    expect(screen.getByText('Showing 100 of 150 statements').getAttribute('aria-live')).toBe('polite');
    await user().click(screen.getByRole('button', { name: /^Show 50 more/ }));
    expect(screen.getByText('Showing 150 of 150 statements')).toBeTruthy();
  });

  it('formats the numbers on the button with separators', () => {
    render(<SourceSuggestions claims={many(1200, claim)} />);
    expect(screen.getByRole('button', { name: 'Show 100 more (1,100 not shown)' })).toBeTruthy();
  });

  it('can be told how many to show, and asks for more through the parent', async () => {
    const onShownChange = vi.fn();
    render(<SourceSuggestions claims={many(300, claim)} shown={200} onShownChange={onShownChange} />);
    expect(claimCount()).toBe(200);
    await user().click(screen.getByRole('button', { name: 'Show 100 more (100 not shown)' }));
    expect(onShownChange).toHaveBeenCalledWith(300);
  });

  it('a search-term chip with a very long word may break, so it cannot widen the page', () => {
    const long = 'x'.repeat(408);
    render(<SourceSuggestions claims={[claim(1, { suggested_search_terms: [long] })]} />);
    const chip = screen.getByRole('link');
    expect(chip.className).toContain('wrap-anywhere');
    expect(chip.className).toContain('max-w-full');
  });

  describe('a claim with a missing or wrong decoration is drawn without it', () => {
    const drawn = (extra) => {
      const bare = { id: 'k1', text: 'Voters were undecided.', ...extra };
      render(<SourceSuggestions claims={[bare]} />);
      return window.document.querySelector('[data-claim-index]');
    };

    it('shows the percentage only when the confidence is a finite number', () => {
      expect(drawn({ confidence: 0.9 }).textContent).toContain('90% confidence');
    });

    it.each([['missing', undefined], ['null', null], ['NaN', NaN], ['text', 'high'], ['infinite', Infinity]])(
      'prints no percentage, and no "NaN", when the confidence is %s',
      (_label, value) => {
        const card = drawn({ claim_type: 'legal', confidence: value });
        expect(card.textContent).toContain('Voters were undecided.');
        expect(card.textContent).not.toMatch(/NaN|undefined|confidence/);
      }
    );

    it('prints no type label for a claim with no type, and never "undefined"', () => {
      const card = drawn({ confidence: 0.5 });
      expect(card.textContent).not.toContain('undefined');
      expect(card.querySelector('span.rounded.font-medium')).toBeNull();
    });

    it('draws a type the page has no colour for in the neutral colour', () => {
      const card = drawn({ claim_type: 'opinion', confidence: 0.5 });
      const pill = within(card).getByText('opinion');
      expect(pill.className).toContain('bg-gray-100');
      expect(pill.className).not.toContain('undefined');
    });

    it('does not look a type up on Object: "constructor" is just an unknown type', () => {
      const pill = within(drawn({ claim_type: 'constructor', confidence: 0.5 })).getByText('constructor');
      expect(pill.className).toContain('bg-gray-100');
      expect(pill.className).not.toContain('function');
    });

    it('draws search terms only when they are a list', () => {
      const card = drawn({ suggested_search_terms: 'a string, not a list', confidence: 0.5 });
      expect(card.textContent).not.toContain('Suggested search terms');
    });
  });

  it('the claim text may break too', () => {
    render(<SourceSuggestions claims={[claim(1, { text: 'y'.repeat(500) })]} />);
    expect(screen.getByText(/^"y+"$/).className).toContain('wrap-anywhere');
  });
});

describe('DocumentPreview', () => {
  const body = (n) => 'The court reasoned carefully about the statutory text. '.repeat(n); // 55 characters each
  const text = body(2200); // 121,000 characters
  const range = () => screen.getByText(/^Characters /).textContent;
  const next = () => screen.getByRole('button', { name: 'Next' });
  const previous = () => screen.getByRole('button', { name: 'Previous' });
  const paneText = () => screen.getByTestId('preview-pane').textContent;

  const renderPreview = (props = {}) =>
    render(<DocumentPreview text={text} citations={[]} unsourcedClaims={[]} {...props} />);

  // The text is one 55-character sentence repeated, so where each window ends can be worked out
  // by hand: 20,000 is just after a space (the window ends there), 40,000 is inside "reasoned"
  // (it ends at the space after the word, 40,003), and so on.
  it('writes the range with separators, exactly, whatever the browser locale', () => {
    renderPreview();
    expect(range()).toBe('Characters 0 to 20,000 of 121,000');
  });

  it('Next shows the text that follows, and nothing that was shown', async () => {
    renderPreview();
    expect(paneText()).toBe(text.slice(0, 20000));
    await user().click(next());
    expect(range()).toBe('Characters 20,000 to 40,003 of 121,000');
    expect(paneText()).toBe(text.slice(20000, 40003));
  });

  it('Previous goes back to exactly the window that was left', async () => {
    renderPreview();
    await user().click(next());
    await user().click(next());
    expect(range()).toBe('Characters 40,003 to 60,004 of 121,000');
    await user().click(previous());
    expect(range()).toBe('Characters 20,000 to 40,003 of 121,000');
    await user().click(previous());
    expect(range()).toBe('Characters 0 to 20,000 of 121,000');
    expect(paneText()).toBe(text.slice(0, 20000));
  });

  it('walking Next to the end shows the whole text once', async () => {
    renderPreview();
    let shown = paneText();
    for (let guard = 0; guard < 20 && !next().disabled; guard += 1) {
      await user().click(next());
      shown += paneText();
    }
    expect(shown).toBe(text);
  });

  it('Previous is disabled at the top and Next at the end', async () => {
    renderPreview();
    expect(previous().disabled).toBe(true);
    expect(next().disabled).toBe(false);
    for (let guard = 0; guard < 20 && !next().disabled; guard += 1) await user().click(next());
    expect(next().disabled).toBe(true);
    expect(previous().disabled).toBe(false);
    expect(range()).toBe('Characters 120,009 to 121,000 of 121,000');
  });

  it('shows each window from its top: the pane is scrolled back when the window changes', async () => {
    renderPreview();
    const pane = screen.getByTestId('preview-pane');
    pane.scrollTop = 4321; // the reader got to the end of the window
    await user().click(next());
    expect(pane.scrollTop).toBe(0);
    pane.scrollTop = 777;
    await user().click(previous());
    expect(pane.scrollTop).toBe(0);
  });

  it('does not scroll the pane when something else changes', async () => {
    const { rerender } = renderPreview();
    const pane = screen.getByTestId('preview-pane');
    pane.scrollTop = 321;
    rerender(<DocumentPreview text={text} citations={[]} unsourcedClaims={[]} />);
    expect(pane.scrollTop).toBe(321);
  });

  it('opens where the first citation is, and Previous walks back to the top with no gap or repeat', async () => {
    const start = 60000;
    const citations = [{ position_start: start, position_end: start + 40, status: 'complete' }];
    renderPreview({ citations });
    const from = Number(range().match(/Characters ([\d,]+)/)[1].replace(/,/g, ''));
    expect(from).toBeGreaterThan(start - 1000);
    expect(from).toBeLessThan(start);
    expect(paneText().startsWith(text.slice(from, from + 30))).toBe(true);

    const before = [];
    for (let guard = 0; guard < 20 && !previous().disabled; guard += 1) {
      await user().click(previous());
      before.unshift(paneText());
    }
    expect(before.join('')).toBe(text.slice(0, from));
  });

  it('shows an emoji whole at the seam', async () => {
    const emoji = `${'a'.repeat(19999)}${'\u{1F600}'.repeat(300)}`;
    render(<DocumentPreview text={emoji} citations={[]} unsourcedClaims={[]} />);
    const lone = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
    expect(lone.test(paneText())).toBe(false);
    await user().click(next());
    expect(lone.test(paneText())).toBe(false);
  });

  it('keeps its position in the parent when it has one, and reports each move', async () => {
    const onPositionChange = vi.fn();
    const { rerender } = render(
      <DocumentPreview text={text} citations={[]} unsourcedClaims={[]} position={null} onPositionChange={onPositionChange} />
    );
    await user().click(next());
    expect(onPositionChange).toHaveBeenCalledTimes(1);
    const moved = onPositionChange.mock.calls[0][0];
    expect([moved.start, moved.end]).toEqual([20000, 40003]);

    rerender(
      <DocumentPreview text={text} citations={[]} unsourcedClaims={[]} position={moved} onPositionChange={onPositionChange} />
    );
    expect(range()).toBe('Characters 20,000 to 40,003 of 121,000');
  });

  it('a position left over from a different, shorter text is not trusted', () => {
    const stale = { start: 50000, end: 70000, back: [] };
    render(<DocumentPreview text={body(100)} citations={[]} unsourcedClaims={[]} position={stale} onPositionChange={() => {}} />);
    expect(range()).toBe('Characters 0 to 5,500 of 5,500');
    expect(paneText()).toBe(body(100));
  });

  it('the range is announced politely', () => {
    renderPreview();
    expect(screen.getByText(/^Characters /).getAttribute('aria-live')).toBe('polite');
  });

  it('says so when there is no text', () => {
    render(<DocumentPreview text="" citations={[]} unsourcedClaims={[]} />);
    expect(screen.getByText('No document content to display.')).toBeTruthy();
  });

  it('marks the citation the server found, not a stretch shifted by the emoji before it', () => {
    // POST /api/analyze answered position_start 16 and position_end 88 for this text (code points).
    const withEmoji = 'Intro \u{1F600}\u{1F600}\u{1F600} here. The Court held so. Brown v. Board of Education, 347 U.S. 483, 495 (1954).';
    renderPreview({
      text: withEmoji,
      citations: [{ id: 'c1', status: 'complete', position_start: 16, position_end: 88 }],
    });
    const marked = window.document.querySelector('.citation-highlight');
    expect(marked.textContent).toBe('The Court held so. Brown v. Board of Education, 347 U.S. 483, 495 (1954)');
  });

  it('marks citations and claims inside the window', () => {
    render(
      <DocumentPreview
        text={text}
        citations={[{ position_start: 100, position_end: 140, status: 'complete' }]}
        unsourcedClaims={[{ position_start: 200, position_end: 230 }]}
      />
    );
    expect(window.document.querySelectorAll('.citation-highlight')).toHaveLength(1);
    expect(window.document.querySelector('.citation-highlight').textContent).toBe(text.slice(100, 140));
    expect(window.document.querySelectorAll('.unsourced-highlight')).toHaveLength(1);
  });

  it('does not repeat text for a highlight with no length or no end', () => {
    render(
      <DocumentPreview
        text="abcdefgh"
        citations={[
          { position_start: 3, position_end: 3, status: 'complete' },
          { position_start: 5, position_end: undefined, status: 'complete' },
        ]}
        unsourcedClaims={[]}
      />
    );
    expect(paneText()).toBe('abcdefgh');
  });
});

describe('FileUpload', () => {
  it('shows the limits, in text that can be read', () => {
    render(<FileUpload />);
    const limits = screen.getByTestId('upload-limits');
    expect(limits.textContent).toContain('Up to 10 MB.');
    expect(limits.className).toContain('text-gray-600');
  });

  it('hands every chosen file up, with the input cleared so the same file can be chosen again', async () => {
    const onFiles = vi.fn();
    render(<FileUpload onFiles={onFiles} />);
    const input = screen.getByLabelText('Choose a document to check');
    const a = new File(['a'], 'a.txt');
    await userEvent.setup({ applyAccept: false }).upload(input, a);
    expect(onFiles).toHaveBeenCalledWith([a]);
    expect(input.value).toBe('');
    await userEvent.setup({ applyAccept: false }).upload(input, a);
    expect(onFiles).toHaveBeenCalledTimes(2);
  });

  describe('when an upload starts, Cancel is brought into view', () => {
    const uploadingProps = { uploading: { file: new File(['x'], 'brief.txt'), phase: 'sending' } };

    it('scrolls Cancel into view, only as far as needed, when the upload starts', () => {
      const scroll = vi.fn();
      Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll });
      try {
        const { rerender } = render(<FileUpload onFiles={() => {}} onCancel={() => {}} />);
        expect(scroll).not.toHaveBeenCalled();
        rerender(<FileUpload onFiles={() => {}} onCancel={() => {}} {...uploadingProps} />);
        expect(scroll).toHaveBeenCalledTimes(1);
        expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
        expect(scroll.mock.contexts[0]).toBe(screen.getByRole('button', { name: 'Cancel' }));
        // Going on uploading (or checking why it stopped) does not scroll again.
        rerender(<FileUpload onFiles={() => {}} onCancel={() => {}} uploading={{ ...uploadingProps.uploading, phase: 'checking' }} />);
        expect(scroll).toHaveBeenCalledTimes(1);
      } finally {
        delete window.HTMLElement.prototype.scrollIntoView;
      }
    });

    it('does not fail where scrollIntoView does not exist', () => {
      expect(window.HTMLElement.prototype.scrollIntoView).toBeUndefined();
      expect(() => render(<FileUpload onFiles={() => {}} onCancel={() => {}} {...uploadingProps} />)).not.toThrow();
    });

    it('puts the line about switching after Cancel, so it cannot push Cancel down the screen', () => {
      render(<FileUpload onFiles={() => {}} onCancel={() => {}} {...uploadingProps} />);
      const cancel = screen.getByRole('button', { name: 'Cancel' });
      const line = screen.getByText('A file is uploading. Cancel the upload to switch.');
      expect(cancel.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(screen.getByTestId('dropzone').compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('the line is not there when nothing is uploading', () => {
      render(<FileUpload onFiles={() => {}} onCancel={() => {}} />);
      expect(screen.queryByText(/Cancel the upload to switch/)).toBeNull();
    });
  });

  it('hands up every file dropped, not only the first', () => {
    const onFiles = vi.fn();
    render(<FileUpload onFiles={onFiles} />);
    const [a, b] = [new File(['a'], 'a.txt'), new File(['b'], 'b.txt')];
    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [a, b] } });
    expect(onFiles).toHaveBeenCalledWith([a, b]);
  });

  it('ignores a drop that carries no files', () => {
    const onFiles = vi.fn();
    render(<FileUpload onFiles={onFiles} />);
    fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [] } });
    expect(onFiles).not.toHaveBeenCalled();
  });

  it('while uploading: shows the file, a Cancel that calls onCancel, and takes no more files', async () => {
    const onCancel = vi.fn();
    render(<FileUpload uploading={{ file: new File(['x'], 'a.txt'), phase: 'sending' }} onCancel={onCancel} />);
    expect(screen.getByText('Uploading 1 KB...')).toBeTruthy();
    expect(screen.getByLabelText('Choose a document to check').disabled).toBe(true);
    expect(screen.queryByTestId('upload-limits')).toBeNull();
    await user().click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('while finding out why an upload did not finish: says that, not that it is uploading', () => {
    render(<FileUpload uploading={{ file: new File(['x'], 'a.txt'), phase: 'checking' }} onCancel={() => {}} />);
    expect(screen.getByText(/Checking whether the server is still running/)).toBeTruthy();
    expect(screen.queryByText(/Uploading/)).toBeNull();
  });

  it('puts an error in an alert and a remark in a status', () => {
    render(<FileUpload error="The PDF is encrypted." notice="Upload cancelled." />);
    expect(screen.getByRole('alert').textContent).toBe('The PDF is encrypted.');
    expect(screen.getByTestId('upload-notice').getAttribute('role')).toBe('status');
  });

  it('keeps a long file name from widening the box', () => {
    const name = `${'a'.repeat(200)}.txt`;
    render(<FileUpload error={`Cannot read ${name}`} />);
    expect(screen.getByText(`Cannot read ${name}`).className).toContain('wrap-anywhere');
  });
});

describe('ErrorBoundary', () => {
  function Bomb({ explode }) {
    if (explode) throw new Error('boom');
    return <p>fine</p>;
  }

  it('shows the children while nothing is wrong', () => {
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    expect(screen.getByText('fine')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('replaces a page that threw with a message and two ways out, instead of a blank page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb explode /></ErrorBoundary>);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('This page stopped working');
    expect(alert.textContent).toContain('If you were checking a document, you will need to upload it again.');
    expect(screen.getByRole('button', { name: 'Reload the page' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Start over' })).toBeTruthy();
  });

  it('Reload the page reloads it', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    render(<ErrorBoundary><Bomb explode /></ErrorBoundary>);
    await user().click(screen.getByRole('button', { name: 'Reload the page' }));
    expect(reload).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it('Start over mounts the page again from nothing', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    let explode = true;
    const Flaky = () => <Bomb explode={explode} />;
    render(<ErrorBoundary><Flaky /></ErrorBoundary>);
    expect(screen.getByRole('alert')).toBeTruthy();
    explode = false;
    await user().click(screen.getByRole('button', { name: 'Start over' }));
    expect(screen.getByText('fine')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('writes what went wrong to the console, for whoever is looking', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb explode /></ErrorBoundary>);
    expect(spy.mock.calls.some((call) => call.some((arg) => arg instanceof Error && arg.message === 'boom'))).toBe(true);
  });
});
