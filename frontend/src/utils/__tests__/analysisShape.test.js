import { describe, expect, it } from 'vitest';
import { normalizeAnalysis, normalizeUpload } from '../analysisShape';
import { analysisBody, citation, claim, uploadBody } from '../../test/fixtures';

describe('normalizeAnalysis: only what the page can render gets through', () => {
  it('passes a well-formed response', () => {
    const body = analysisBody({ citations: [citation(1), citation(2)], claims: [claim(1)] });
    const out = normalizeAnalysis(body);
    expect(out.analysis.citations).toHaveLength(2);
    expect(out.stats.total_citations).toBe(2);
  });

  it.each([
    ['null', null],
    ['an empty object', {}],
    ['a string', 'ok'],
    ['an array', []],
    ['no stats', { ...analysisBody(), stats: undefined }],
    ['stats that is not an object', { ...analysisBody(), stats: 5 }],
    ['no analysis', { ...analysisBody(), analysis: undefined }],
    ['no short_form_suggestions', { ...analysisBody(), short_form_suggestions: undefined }],
    ['citations that is not a list', { ...analysisBody(), analysis: { citations: 'x', unsourced_claims: [] } }],
    ['unsourced_claims missing', { ...analysisBody(), analysis: { citations: [] } }],
  ])('refuses %s', (_name, body) => {
    expect(normalizeAnalysis(body)).toBeNull();
  });

  it.each(['total_citations', 'complete', 'incomplete', 'needs_verification', 'unsourced_claims'])(
    'refuses stats with %s missing, text or negative',
    (key) => {
      for (const bad of [undefined, null, 'ten', -1, NaN]) {
        const body = analysisBody();
        body.stats[key] = bad;
        expect(normalizeAnalysis(body), `${key}=${bad}`).toBeNull();
      }
    }
  );

  it('refuses a citation the cards could not draw', () => {
    for (const bad of [{ ...citation(1), status: undefined }, { ...citation(1), raw_text: 5 }, { ...citation(1), id: undefined }, { ...citation(1), parties: 'A v. B' }, { ...citation(1), missing: 'year' }, null]) {
      expect(normalizeAnalysis(analysisBody({ citations: [bad] }))).toBeNull();
    }
  });

  it('refuses a claim with no text', () => {
    expect(normalizeAnalysis(analysisBody({ claims: [{ id: 'k', claim_type: 'legal' }] }))).toBeNull();
  });

  // A claim only needs its text to be drawn. The rest decorates the card, so a claim that comes
  // without it (another version of the server) is repaired, and the analysis is not refused.
  describe('a claim that lacks, or has a wrong, decoration is repaired, not refused', () => {
    const claimOut = (extra) => {
      const body = analysisBody({ claims: [claim(1)] });
      body.analysis.unsourced_claims = [{ ...claim(1), ...extra }];
      const out = normalizeAnalysis(body);
      expect(out).not.toBeNull();
      return out.analysis.unsourced_claims[0];
    };

    it('keeps a finite confidence', () => {
      expect(claimOut({ confidence: 0.42 }).confidence).toBe(0.42);
      expect(claimOut({ confidence: 0 }).confidence).toBe(0);
    });

    it.each([
      ['missing', undefined],
      ['null', null],
      ['text', '0.9'],
      ['NaN', NaN],
      ['infinite', Infinity],
      ['an object', {}],
    ])('drops a confidence that is %s', (_label, value) => {
      const out = claimOut({ confidence: value });
      expect(out.confidence).toBeUndefined();
      expect(out.text).toBe(claim(1).text);
    });

    it('a claim with no confidence key at all is repaired too', () => {
      const body = analysisBody();
      const bare = { id: 'k1', text: 'Voters were undecided.' };
      body.analysis.unsourced_claims = [bare];
      const out = normalizeAnalysis(body).analysis.unsourced_claims[0];
      expect(out.confidence).toBeUndefined();
      expect(out.claim_type).toBe('factual');
      expect(out.suggested_search_terms).toEqual([]);
    });

    it('keeps each of the four known claim types', () => {
      for (const type of ['legal', 'statistical', 'factual', 'quotation']) {
        expect(claimOut({ claim_type: type }).claim_type).toBe(type);
      }
    });

    it.each([['missing', undefined], ['unknown', 'opinion'], ['a number', 7], ['null', null], ['a prototype name', 'constructor']])(
      'gives a claim type that is %s the neutral type',
      (_label, value) => {
        expect(claimOut({ claim_type: value }).claim_type).toBe('factual');
      }
    );

    it('keeps search terms that are strings and drops what is not', () => {
      expect(claimOut({ suggested_search_terms: ['a', 3, null, 'b', {}] }).suggested_search_terms).toEqual(['a', 'b']);
    });

    it.each([['missing', undefined], ['a string', 'terms'], ['an object', { a: 1 }], ['null', null]])(
      'makes search terms that are %s an empty list',
      (_label, value) => {
        expect(claimOut({ suggested_search_terms: value }).suggested_search_terms).toEqual([]);
      }
    );

    it('leaves the rest of the claim, and the other claims, as they were', () => {
      const body = analysisBody();
      body.analysis.unsourced_claims = [claim(1), { ...claim(2), confidence: 'x' }];
      const out = normalizeAnalysis(body).analysis.unsourced_claims;
      expect(out[0]).toEqual(claim(1));
      expect(out[1].id).toBe('k2');
      expect(out[1].position_start).toBe(claim(2).position_start);
    });
  });

  it('drops the optional counts and lookup summary when they are not usable, and keeps the rest', () => {
    const body = analysisBody({ lookup: 'none', stats: { citations_shown: 'all', claims_shown: -2 } });
    const out = normalizeAnalysis(body);
    expect(out.lookup).toBeUndefined();
    expect(out.stats).not.toHaveProperty('citations_shown');
    expect(out.stats).not.toHaveProperty('claims_shown');
  });

  it('keeps a lookup summary that is an object, with whatever fields it has', () => {
    const lookup = { eligible: 4, completed: 4, skipped: 0, matched: 1, failed: 3 };
    expect(normalizeAnalysis(analysisBody({ lookup })).lookup).toEqual(lookup);
  });
});

describe('normalizeUpload', () => {
  it('passes a well-formed response', () => {
    const out = normalizeUpload(uploadBody({ warnings: ['2 pages could not be read'] }));
    expect(out.full_text).toContain('Brown');
    expect(out.warnings).toEqual(['2 pages could not be read']);
  });

  it('refuses a body with no text or no document id', () => {
    expect(normalizeUpload({})).toBeNull();
    expect(normalizeUpload(null)).toBeNull();
    expect(normalizeUpload({ document_id: 'd' })).toBeNull();
    expect(normalizeUpload({ full_text: 'x' })).toBeNull();
    expect(normalizeUpload({ document_id: 'd', full_text: 5 })).toBeNull();
  });

  it('fills in a file name and warnings that are missing or wrong', () => {
    const out = normalizeUpload({ document_id: 'd', full_text: 'x', filename: 7, warnings: 'oops' });
    expect(out.filename).toBe('document');
    expect(out.warnings).toEqual([]);
    expect(normalizeUpload({ document_id: 'd', full_text: 'x', warnings: ['a', 3, 'b'] }).warnings).toEqual(['a', 'b']);
  });
});
