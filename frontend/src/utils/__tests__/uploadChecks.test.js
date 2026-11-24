import { describe, expect, it } from 'vitest';
import {
  analysisNotices,
  checkFileBeforeUpload,
  claimsNotice,
  limitsSummary,
  unsupportedReason,
  uploadingMessage,
} from '../uploadChecks';

const LIMITS = {
  max_upload_mb: 10,
  max_text_chars: 1500000,
  max_pdf_pages: 400,
  approx_max_words: 250000,
  approx_max_pages: 348,
};
const MB = 1024 * 1024;
const file = (name, size) => ({ name, size });

describe('limitsSummary: what is said before anyone uploads', () => {
  it('states every limit that can refuse a file', () => {
    const text = limitsSummary(LIMITS);
    expect(text).toContain('10 MB');
    expect(text).toContain('250,000 words');
    expect(text).toContain('about 250,000 words (roughly 350 to 500 pages)');
    expect(text).not.toContain('348');
    expect(text).toContain('PDFs up to 400 pages');
  });

  it('follows the limits it is given, so the number shown is the number enforced', () => {
    const text = limitsSummary({ ...LIMITS, max_upload_mb: 25, max_pdf_pages: 150, approx_max_words: 100000, approx_max_pages: 140 });
    expect(text).toContain('25 MB');
    expect(text).toContain('PDFs up to 150 pages');
    expect(text).toContain('100,000 words');
    expect(text).not.toContain('400');
  });

  it('works out the words and pages itself if an older server did not send them', () => {
    const text = limitsSummary({ max_upload_mb: 10, max_text_chars: 600000, max_pdf_pages: 80 });
    expect(text).toContain('100,000 words');
    expect(text).toContain('PDFs up to 80 pages');
  });
});

describe('checkFileBeforeUpload', () => {
  it('lets an ordinary file through', () => {
    expect(checkFileBeforeUpload(file('brief.docx', 2 * MB), LIMITS)).toBeNull();
  });

  it('accepts a file of exactly the limit and refuses one byte over', () => {
    expect(checkFileBeforeUpload(file('a.pdf', 10 * MB), LIMITS)).toBeNull();
    expect(checkFileBeforeUpload(file('a.pdf', 10 * MB + 1), LIMITS)).toMatch(/limit is 10 MB/);
  });

  it('says how big the file is and what to do about it', () => {
    const message = checkFileBeforeUpload(file('big.pdf', 14.2 * MB), LIMITS);
    expect(message).toContain('14 MB');
    expect(message).toContain('Split the document');
  });

  it('uses the limit it is given', () => {
    expect(checkFileBeforeUpload(file('a.pdf', 12 * MB), { ...LIMITS, max_upload_mb: 20 })).toBeNull();
    expect(checkFileBeforeUpload(file('a.pdf', 12 * MB), { ...LIMITS, max_upload_mb: 5 })).toMatch(/limit is 5 MB/);
  });

  it('reports a file type that cannot work, before sending it', () => {
    expect(checkFileBeforeUpload(file('notes.pages', 1000), LIMITS)).toMatch(/Pages/);
    expect(checkFileBeforeUpload(file('brief.doc', 1000), LIMITS)).toMatch(/\.docx/);
  });

  it('does not judge a file by its type when the type is unknown to it', () => {
    expect(unsupportedReason(file('no-extension', 10))).toBeNull();
    expect(unsupportedReason(file('brief.pdf', 10))).toBeNull();
    expect(unsupportedReason(file('BRIEF.DOCX', 10))).toBeNull();
  });
});

describe('uploadingMessage', () => {
  it('warns that a PDF or a large file takes a while', () => {
    expect(uploadingMessage(file('long.pdf', 300 * 1024))).toMatch(/can take a minute/);
    expect(uploadingMessage(file('long.docx', 5 * MB))).toMatch(/can take a minute/);
  });

  it('is brief for a small file', () => {
    expect(uploadingMessage(file('note.txt', 20 * 1024))).toBe('Uploading 0.0 MB...');
  });

  it('copes with no file', () => {
    expect(uploadingMessage(null)).toBe('Uploading...');
  });
});

describe('analysisNotices: nothing is left out without saying so', () => {
  const stats = { total_citations: 100, citations_shown: 100, unsourced_claims: 0, claims_shown: 0 };

  it('says nothing when nothing was cut', () => {
    expect(analysisNotices({ stats, lookup: { eligible: 5, completed: 5, skipped: 0, budget_exhausted: false } })).toEqual([]);
  });

  it('says how many citations are shown when some are not', () => {
    const notices = analysisNotices({ stats: { ...stats, total_citations: 2450, citations_shown: 2000 } });
    expect(notices).toEqual(['Found 2,450 citations. Showing the first 2,000, in document order.']);
  });

  it('says how many lookups were done, and that the rest were left as found', () => {
    const [notice] = analysisNotices({ stats, lookup: { eligible: 218, completed: 66, skipped: 152, budget_exhausted: true } });
    expect(notice).toContain('Looked up 66 of 218 incomplete citations');
    expect(notice).toContain('the time limit was reached');
    expect(notice).toContain('152 were left as found');
    expect(notice).toContain('Check those by hand');
  });

  it('does not blame the time limit when the cap was the reason', () => {
    const [notice] = analysisNotices({ stats, lookup: { eligible: 300, completed: 200, skipped: 100, budget_exhausted: false } });
    expect(notice).not.toContain('time limit');
    expect(notice).toContain('100 were left as found');
  });

  it('copes with an older server that sends neither', () => {
    expect(analysisNotices({ stats: { total_citations: 5, complete: 5 } })).toEqual([]);
    expect(analysisNotices(null)).toEqual([]);
  });

  it('can say both things at once', () => {
    const notices = analysisNotices({
      stats: { ...stats, total_citations: 2450, citations_shown: 2000 },
      lookup: { eligible: 10, completed: 4, skipped: 6, budget_exhausted: true },
    });
    expect(notices).toHaveLength(2);
  });
});

describe('claimsNotice', () => {
  it('says how many of the claims are shown', () => {
    expect(claimsNotice({ unsourced_claims: 8003, claims_shown: 500 })).toBe(
      'Found 8,003 statements that may need a citation. Showing the 500 most likely.'
    );
  });

  it('is silent when all are shown, or the server did not say', () => {
    expect(claimsNotice({ unsourced_claims: 40, claims_shown: 40 })).toBeNull();
    expect(claimsNotice({ unsourced_claims: 40 })).toBeNull();
    expect(claimsNotice(undefined)).toBeNull();
  });
});
