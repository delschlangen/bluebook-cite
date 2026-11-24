import React from 'react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import CitationList from '../CitationList';
import DocumentPreview from '../DocumentPreview';
import FileUpload from '../FileUpload';
import SourceSuggestions from '../SourceSuggestions';
import { DEFAULT_LIMITS } from '../../services/api';

// renderToString puts <!-- --> between adjacent text nodes, which hides text from a substring check.
const html = (node) => renderToString(node).replace(/<!-- -->/g, '');

const citation = (n, extra = {}) => ({
  id: `c${n}`,
  raw_text: `Brown v. Board of Education, 347 U.S. ${n} (1954)`,
  status: 'complete',
  type: 'case',
  position_start: n * 100,
  position_end: n * 100 + 50,
  confidence_score: 0,
  ...extra,
});
const many = (n) => Array.from({ length: n }, (_, i) => citation(i + 1));
const render = (citations, props = {}) =>
  html(<CitationList citations={citations} shortFormSuggestions={[]} onSelect={() => {}} {...props} />);

describe('CitationList shows a page at a time', () => {
  it('renders 100 of 250 and says how many more there are', () => {
    const out = render(many(250));
    expect(out).toContain('#100');
    expect(out).not.toContain('#101');
    expect(out).toContain('Show 100 more (150 not shown)');
    expect((out.match(/Brown v\. Board/g) || []).length).toBe(100);
  });

  it('has no button when everything fits on the first page', () => {
    expect(render(many(100))).not.toContain('not shown');
    expect(render(many(3))).not.toContain('Show ');
  });

  it('offers exactly the one that is left', () => {
    expect(render(many(101))).toContain('Show 1 more (1 not shown)');
  });

  it('says so when there are none', () => {
    expect(render([])).toContain('No citations found in this document.');
  });

  it('puts a short-form suggestion on the right card', () => {
    const suggestions = [
      { citation_id: 'c2', suggested_form: 'Id. at 5.', short_form_type: 'id', explanation: 'Same source as above' },
    ];
    const out = render(many(3), { shortFormSuggestions: suggestions });
    expect(out.match(/Suggested \(id\)/g)).toHaveLength(1);
    expect(out).toContain('Same source as above');
  });

  it('marks the selected card', () => {
    const out = render(many(3), { selectedId: 'c2' });
    expect(out.match(/ring-2 ring-blue-200/g)).toHaveLength(1);
  });

  it('numbers cards from one in document order', () => {
    const out = render(many(3));
    expect(out.indexOf('#1')).toBeLessThan(out.indexOf('#2'));
    expect(out.indexOf('#2')).toBeLessThan(out.indexOf('#3'));
  });
});

describe('the upload box tells people the limits before they choose a file', () => {
  it('states the size, words, pages and PDF pages that are enforced', () => {
    const out = html(<FileUpload onUpload={() => {}} />);
    expect(out).toContain('data-testid="upload-limits"');
    expect(out).toContain(`${DEFAULT_LIMITS.max_upload_mb} MB`);
    expect(out).toContain('250,000 words');
    expect(out).toContain(`PDFs up to ${DEFAULT_LIMITS.max_pdf_pages} pages`);
  });

  it('no longer claims a limit that the server does not enforce', () => {
    const out = html(<FileUpload onUpload={() => {}} />);
    expect(out).not.toContain('150 pages');
  });
});

describe('the claims tab', () => {
  const claims = Array.from({ length: 150 }, (_, i) => ({
    id: `k${i}`,
    text: `Studies show that ${i}% of voters were undecided.`,
    claim_type: 'statistical',
    confidence: 0.9,
    position_start: i * 100,
    position_end: i * 100 + 40,
  }));

  it('shows a page of claims and says how many are not shown', () => {
    const out = html(<SourceSuggestions claims={claims} />);
    expect(out).toContain('Show 50 more (50 not shown)');
    expect((out.match(/Studies show that/g) || []).length).toBe(100);
  });

  it('carries the note about how many of all the claims it is showing', () => {
    const out = html(<SourceSuggestions claims={claims.slice(0, 5)} notice="Found 8,003 statements that may need a citation. Showing the 500 most likely." />);
    expect(out).toContain('Showing the 500 most likely.');
  });

  it('has no note when none is given', () => {
    expect(html(<SourceSuggestions claims={claims.slice(0, 5)} />)).not.toContain('claims-notice');
  });

  it('says so when there are no claims', () => {
    expect(html(<SourceSuggestions claims={[]} />)).toContain('All statements appear to have citations');
  });
});

describe('the document preview', () => {
  const filler = (n) => 'The court reasoned carefully about the statutory text. '.repeat(n);

  it('opens where the first citation is, not at the top, so a footnoted document shows something', () => {
    const body = filler(2000); // about 110,000 characters of plain body text
    const text = `${body}[^1] See Brown v. Board of Education, 347 U.S. 483 (1954).`;
    const start = text.indexOf('Brown v. Board');
    const out = html(
      <DocumentPreview
        text={text}
        citations={[{ position_start: start, position_end: start + 50, status: 'complete' }]}
        unsourcedClaims={[]}
      />
    );
    expect(out).toContain('citation-highlight');
    expect(out).toContain('Brown v. Board of Education, 347 U.S. 483 (1954)');
  });

  it('never puts more than a window of a long text in the page', () => {
    const text = filler(20000); // over a million characters
    const out = html(<DocumentPreview text={text} citations={[]} unsourcedClaims={[]} />);
    expect(out.length).toBeLessThan(40000);
    expect(out).toContain(`of ${text.length.toLocaleString()}`);
  });

  it('has Previous disabled at the top and Next available', () => {
    const out = html(<DocumentPreview text={filler(2000)} citations={[]} unsourcedClaims={[]} />);
    expect(out).toMatch(/disabled=""[^>]*>Previous/);
    expect(out).not.toMatch(/disabled=""[^>]*>Next/);
  });

  it('says so when there is no text', () => {
    expect(html(<DocumentPreview text="" citations={[]} unsourcedClaims={[]} />)).toContain('No document content');
  });
});
