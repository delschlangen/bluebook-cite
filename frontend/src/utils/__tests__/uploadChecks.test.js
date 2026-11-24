import { describe, expect, it } from 'vitest';
import {
  CHECKING_SERVER_MESSAGE,
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

  // The size shown is rounded up to one decimal, so it is always above the limit it is
  // compared with. Each expectation is written out, not computed.
  it.each([
    [10 * MB + 1, 'This file is 10.1 MB. The limit is 10 MB.'],
    [10 * MB + 30000, 'This file is 10.1 MB. The limit is 10 MB.'],
    [Math.round(10.05 * MB), 'This file is 10.1 MB. The limit is 10 MB.'],
    [Math.round(10.1 * MB) + 1, 'This file is 10.2 MB. The limit is 10 MB.'],
    [Math.round(10.49 * MB), 'This file is 10.5 MB. The limit is 10 MB.'],
    [Math.round(10.51 * MB), 'This file is 10.6 MB. The limit is 10 MB.'],
    [Math.round(14.2 * MB) + 1, 'This file is 14.3 MB. The limit is 10 MB.'],
    [Math.round(99.9 * MB), 'This file is 99.9 MB. The limit is 10 MB.'],
    [100 * MB + 1, 'This file is 101 MB. The limit is 10 MB.'],
    [1500 * MB, 'This file is 1,500 MB. The limit is 10 MB.'],
  ])('says "%s bytes" is too big in a sentence that is not self-contradictory', (size, sentence) => {
    const message = checkFileBeforeUpload(file('big.pdf', size), LIMITS);
    expect(message.startsWith(sentence)).toBe(true);
  });

  it('never shows a size equal to the limit', () => {
    for (let size = 10 * MB + 1; size < 10 * MB + 2 * MB; size += 12345) {
      const shown = Number(checkFileBeforeUpload(file('a.pdf', size), LIMITS).match(/This file is ([\d.]+) MB/)[1]);
      expect(shown).toBeGreaterThan(10);
    }
  });

  it('says what to do about it', () => {
    const message = checkFileBeforeUpload(file('big.pdf', 14.2 * MB), LIMITS);
    expect(message).toContain('Split the document at a chapter or section boundary');
    expect(message).toContain('export it again at a smaller size');
  });

  it('uses the limit it is given', () => {
    expect(checkFileBeforeUpload(file('a.pdf', 12 * MB), { ...LIMITS, max_upload_mb: 20 })).toBeNull();
    expect(checkFileBeforeUpload(file('a.pdf', 12 * MB), { ...LIMITS, max_upload_mb: 5 })).toMatch(
      /^This file is 12\.0 MB\. The limit is 5 MB\./
    );
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

  it('is brief for a small file, and gives its size in KB, not as 0.0 MB', () => {
    expect(uploadingMessage(file('note.txt', 20 * 1024))).toBe('Uploading 20 KB...');
    expect(uploadingMessage(file('note.txt', 300))).toBe('Uploading 1 KB...');
    expect(uploadingMessage(file('note.txt', 900 * 1024))).toBe('Uploading 900 KB...');
    expect(uploadingMessage(file('note.txt', 1.5 * MB))).toBe('Uploading 1.5 MB...');
  });

  it('gives the size of a long document with one decimal', () => {
    expect(uploadingMessage(file('long.docx', 5.25 * MB))).toBe(
      'Uploading and reading 5.3 MB. A long document can take a minute.'
    );
    expect(uploadingMessage(file('long.pdf', 200 * 1024))).toBe(
      'Uploading and reading 200 KB. A long document can take a minute.'
    );
  });

  it('has its own words for the time spent finding out why an upload did not finish', () => {
    expect(CHECKING_SERVER_MESSAGE).toBe(
      'The upload did not finish. Checking whether the server is still running... ' +
        'This can take up to half a minute.'
    );
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

  it('puts the size and word counts in en-US form whatever the visitor locale', () => {
    const [notice] = analysisNotices({ stats: { ...stats, total_citations: 1234567, citations_shown: 1000000 } });
    expect(notice).toBe('Found 1,234,567 citations. Showing the first 1,000,000, in document order.');
  });

  it('can say both things at once', () => {
    const notices = analysisNotices({
      stats: { ...stats, total_citations: 2450, citations_shown: 2000 },
      lookup: { eligible: 10, completed: 4, skipped: 6, budget_exhausted: true },
    });
    expect(notices).toHaveLength(2);
  });
});

describe('analysisNotices: what the outside lookups did', () => {
  const stats = { total_citations: 300, citations_shown: 300, unsourced_claims: 0, claims_shown: 0 };
  const lookupOf = (lookup) => analysisNotices({ stats, lookup });

  it('when the server says how each lookup ended, never says "Looked up N of M" for failures', () => {
    const notices = lookupOf({ eligible: 218, completed: 200, skipped: 18, matched: 0, failed: 200, budget_exhausted: false });
    expect(notices).toEqual([
      'Checked 200 of 218 incomplete citations in outside sources: 0 matched, 200 could not be reached. ' +
        'The rest, and any that did not match, need checking by hand.',
    ]);
    expect(notices[0]).not.toContain('Looked up');
  });

  it('counts the matches and the failures separately', () => {
    const [notice] = lookupOf({ eligible: 300, completed: 250, skipped: 50, matched: 190, failed: 12, budget_exhausted: false });
    expect(notice).toBe(
      'Checked 250 of 300 incomplete citations in outside sources: 190 matched, 12 could not be reached. ' +
        'The rest, and any that did not match, need checking by hand.'
    );
  });

  it('leaves out "could not be reached" when none could not', () => {
    const [notice] = lookupOf({ eligible: 300, completed: 250, skipped: 50, matched: 240, failed: 0, budget_exhausted: false });
    expect(notice).toBe(
      'Checked 250 of 300 incomplete citations in outside sources: 240 matched. ' +
        'The rest, and any that did not match, need checking by hand.'
    );
  });

  it('still says the time limit was reached', () => {
    const [notice] = lookupOf({ eligible: 218, completed: 66, skipped: 152, matched: 60, failed: 2, budget_exhausted: true });
    expect(notice).toBe(
      'Checked 66 of 218 incomplete citations in outside sources; the time limit was reached: ' +
        '60 matched, 2 could not be reached. The rest, and any that did not match, need checking by hand.'
    );
  });

  it('speaks up when everything was tried but some did not match, since those still need a person', () => {
    const [notice] = lookupOf({ eligible: 10, completed: 10, skipped: 0, matched: 4, failed: 0, budget_exhausted: false });
    expect(notice).toContain('Checked 10 of 10 incomplete citations in outside sources: 4 matched.');
  });

  it('is silent when everything matched and nothing was skipped', () => {
    expect(lookupOf({ eligible: 10, completed: 10, skipped: 0, matched: 10, failed: 0, budget_exhausted: false })).toEqual([]);
  });

  it('with only the failure count, says what it knows and no more', () => {
    const [notice] = lookupOf({ eligible: 20, completed: 20, skipped: 0, failed: 20, budget_exhausted: false });
    expect(notice).toBe(
      'Checked 20 of 20 incomplete citations in outside sources: 20 could not be reached. ' +
        'The rest, and any that did not match, need checking by hand.'
    );
  });

  it('ignores a count that is not a usable number, and falls back to the older wording', () => {
    const [notice] = lookupOf({ eligible: 218, completed: 200, skipped: 18, matched: 'many', failed: -3, budget_exhausted: false });
    expect(notice).toBe(
      'Looked up 200 of 218 incomplete citations in outside sources, so 18 were left as found. Check those by hand.'
    );
  });

  it('keeps the older wording, exactly, for a server that sends neither count', () => {
    expect(lookupOf({ eligible: 218, completed: 66, skipped: 152, budget_exhausted: true })).toEqual([
      'Looked up 66 of 218 incomplete citations in outside sources; the time limit was reached, so ' +
        '152 were left as found. Check those by hand.',
    ]);
    expect(lookupOf({ eligible: 300, completed: 200, skipped: 100, budget_exhausted: false })).toEqual([
      'Looked up 200 of 300 incomplete citations in outside sources, so 100 were left as found. Check those by hand.',
    ]);
  });

  it('says nothing when no citation was eligible for a lookup, whatever else the counts say', () => {
    expect(lookupOf({ eligible: 0, completed: 0, skipped: 0, matched: 0, failed: 0, budget_exhausted: false })).toEqual([]);
    expect(lookupOf({ eligible: 0, completed: 0, skipped: 5, matched: 0, failed: 2, budget_exhausted: true })).toEqual([]);
    expect(lookupOf({ eligible: 0, completed: 0, skipped: 5, budget_exhausted: true })).toEqual([]);
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
