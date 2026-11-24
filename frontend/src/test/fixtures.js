// Response bodies shaped like the backend's.

export function uploadBody(overrides = {}) {
  return {
    document_id: 'doc-1',
    filename: 'brief.txt',
    full_text: 'See Brown v. Board of Education, 347 U.S. 483 (1954).',
    footnote_count: 0,
    endnote_count: 0,
    warnings: [],
    ...overrides,
  };
}

export function citation(n, extra = {}) {
  return {
    id: `c${n}`,
    type: 'case',
    status: 'complete',
    raw_text: `Brown v. Board of Education, 347 U.S. ${n} (1954)`,
    position_start: n * 100,
    position_end: n * 100 + 50,
    parties: ['Brown', 'Board of Education'],
    volume: '347',
    reporter: 'U.S.',
    page: String(n),
    year: 1954,
    confidence_score: 0,
    ...extra,
  };
}

export function claim(n, extra = {}) {
  return {
    id: `k${n}`,
    text: `Studies show that ${n}% of voters were undecided.`,
    claim_type: 'statistical',
    confidence: 0.9,
    position_start: n * 100 + 60,
    position_end: n * 100 + 90,
    suggested_search_terms: [],
    ...extra,
  };
}

export function analysisBody({ citations = [citation(1)], claims = [], stats = {}, lookup, suggestions = [] } = {}) {
  return {
    analysis: { document_id: 'doc-1', filename: 'brief.txt', total_footnotes: 0, citations, unsourced_claims: claims },
    short_form_suggestions: suggestions,
    stats: {
      total_citations: citations.length,
      complete: citations.length,
      incomplete: 0,
      needs_verification: 0,
      unsourced_claims: claims.length,
      ...stats,
    },
    ...(lookup ? { lookup } : {}),
  };
}

export const many = (n, make = citation) => Array.from({ length: n }, (_, i) => make(i + 1));
