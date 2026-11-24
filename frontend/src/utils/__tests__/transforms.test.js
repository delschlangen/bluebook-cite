import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { TRANSFORMS } from '../citationEngine';
import { titlecase } from '../transforms';

/**
 * The expected answers live in shared/engine_conformance.json under transform_cases
 * and are ALSO run by the Python suite against the Python implementation. If the two
 * ever disagree, one of the suites fails.
 */
const { transform_cases: cases } = JSON.parse(
  readFileSync(new URL('../../../../shared/engine_conformance.json', import.meta.url), 'utf8')
);

describe('shared transform cases', () => {
  it.each(cases.map((c) => [`${c.transform}: ${c.input.slice(0, 32)}`, c]))('%s', (_n, c) => {
    expect(TRANSFORMS[c.transform](c.input, 'law_review')).toBe(c.expected);
  });

  it('registers every transform the shared corpus uses', () => {
    cases.forEach((c) => expect(TRANSFORMS[c.transform]).toBeTypeOf('function'));
  });
});

describe('Rule 8 title capitalisation', () => {
  it('fixes the pasted GAO title', () => {
    expect(
      titlecase('Firearms Data: ATF Did Not Always Comply With The Appropriations Act Restrictions')
    ).toBe('Firearms Data: ATF Did Not Always Comply with the Appropriations Act Restrictions');
  });

  it('always capitalises the first word and the word after a colon', () => {
    expect(titlecase('the law')).toMatch(/^The/);
    expect(titlecase('history: a study of the law')).toContain('A Study');
  });

  it('leaves acronyms and names exactly as typed', () => {
    expect(titlecase('the ATF and NetChoice')).toBe('The ATF and NetChoice');
  });

  it('returns an all-capitals title unchanged', () => {
    expect(titlecase('FIREARMS DATA: ATF DID NOT')).toBe('FIREARMS DATA: ATF DID NOT');
  });

  it('is idempotent', () => {
    const once = titlecase('the rise and fall of the roman empire');
    expect(titlecase(once)).toBe(once);
  });

  it('is not defeated by punctuation around a word', () => {
    expect(titlecase('the "rule of law" and order')).toBe('The "Rule of Law" and Order');
  });
});
