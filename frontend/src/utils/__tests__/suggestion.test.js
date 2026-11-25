import { describe, expect, it } from 'vitest';
import { missingLabels, suggestionFor } from '../suggestion';

const cite = (extra = {}) => ({ id: 'c1', type: 'case', status: 'incomplete', raw_text: 'District of Columbia v. Heller', ...extra });
const sug = (suggested_form, extra = {}) => ({ citation_id: 'c1', suggested_form, short_form_type: 'full', ...extra });

describe('suggestionFor: a box only when it says something, and only as much as is true', () => {
  it('shows no box when the suggestion is the input again (the real case: an incomplete case name)', () => {
    expect(suggestionFor(cite(), sug('*District of Columbia v. Heller*'))).toBeNull();
  });

  it.each([
    ['italics markers', 'Brown v. Board', '*Brown v. Board*'],
    ['extra spaces and line breaks', 'Brown   v.\n Board', 'Brown v. Board'],
    ['a final period', 'Brown v. Board', 'Brown v. Board.'],
    ['two final periods (a URL that already ended in one)', 'https://example.com/a.', 'https://example.com/a..'],
    ['all three at once', '  Brown  v. Board  ', '*Brown v. Board*.'],
    ['spaces around the whole', 'Brown v. Board', '  Brown v. Board  '],
  ])('does not count %s as a difference', (_label, raw, suggested) => {
    expect(suggestionFor(cite({ raw_text: raw }), sug(suggested))).toBeNull();
    expect(suggestionFor(cite({ raw_text: raw, status: 'complete' }), sug(suggested))).toBeNull();
  });

  it('does count a real difference', () => {
    expect(suggestionFor(cite({ raw_text: 'Brown v. Board of Education, 347 U.S. 483 (1954)', status: 'complete' }), sug('*Brown v. Bd. of Educ.*, 347 U.S. 483 (1954).'))).not.toBeNull();
    expect(suggestionFor(cite({ raw_text: 'Brown v. Board' }), sug('Brown v. Board of Education'))).not.toBeNull();
  });

  it('a complete citation keeps "Suggested (full)", or its short form’s own label', () => {
    const complete = cite({ status: 'complete', raw_text: 'Brown v. Board of Education, 347 U.S. 483 (1954)' });
    expect(suggestionFor(complete, sug('*Brown v. Bd. of Educ.*, 347 U.S. 483 (1954).'))).toMatchObject({ label: 'Suggested (full):', complete: true });
    expect(suggestionFor(complete, sug('*Brown*, 347 U.S. at 495', { short_form_type: 'short' }))).toMatchObject({ label: 'Suggested (short):' });
    expect(suggestionFor(complete, sug('Id. at 495', { short_form_type: 'id' }))).toMatchObject({ label: 'Suggested (id):' });
    expect(suggestionFor(complete, sug('x', { short_form_type: undefined }))).toMatchObject({ label: 'Suggested:' });
  });

  it.each([['incomplete'], ['needs_verification'], ['malformed'], ['something new']])(
    'a %s citation says "Formatted so far", never "Suggested (full)"',
    (status) => {
      const out = suggestionFor(cite({ status, raw_text: 'The Court said so in Smith v. Jones' }), sug('*Smith v. Jones*'));
      expect(out).toEqual({ text: '*Smith v. Jones*', label: 'Formatted so far:', complete: false });
    }
  );

  it.each([[undefined], [null], [{}], [{ suggested_form: '' }], [{ suggested_form: 5 }], [{ suggested_form: null }]])(
    'no suggestion, or an unusable one (%j), is no box',
    (suggestion) => {
      expect(suggestionFor(cite(), suggestion)).toBeNull();
    }
  );
});

describe('missingLabels: what an incomplete citation still lacks, in words', () => {
  it('is nothing for a complete citation, whatever it says is missing', () => {
    expect(missingLabels(cite({ status: 'complete', missing: ['year'] }))).toEqual([]);
  });

  it('uses the names the server sent, as the words the page uses for them', () => {
    expect(missingLabels(cite({ missing: ['volume', 'year'] }))).toEqual(['volume number', 'year']);
  });

  it('says a name it has no words for in its own, without underscores, and once', () => {
    expect(missingLabels(cite({ missing: ['report_number', 'report_number'] }))).toEqual(['report number']);
  });

  it('works it out for a case the server sent no list for (the older readers send none)', () => {
    expect(missingLabels(cite({ parties: ['District of Columbia', 'Heller'], missing: [] }))).toEqual([
      'volume number', 'reporter', 'first page', 'year',
    ]);
    expect(missingLabels(cite({ parties: ['A', 'B'], volume: '1', reporter: 'U.S.', page: '2', year: 2000, missing: [] }))).toEqual([]);
    expect(missingLabels(cite({ parties: ['A', 'B'], volume: '1', missing: undefined }))).toEqual(['reporter', 'first page', 'year']);
  });

  it('works it out for a U.S. Code citation too', () => {
    expect(missingLabels({ type: 'statute', status: 'incomplete', title_number: '47', section: null, code: 'U.S.C.' })).toEqual(['section']);
  });

  it('has nothing to say for a kind it cannot work out and the server did not list', () => {
    expect(missingLabels(cite({ type: 'website', missing: [] }))).toEqual([]);
    expect(missingLabels(cite({ type: 'book' }))).toEqual([]);
  });

  it('ignores entries that are not names', () => {
    expect(missingLabels(cite({ type: 'website', missing: [null, 3, '', 'title'] }))).toEqual(['title']);
  });
});
