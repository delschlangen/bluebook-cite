// The page and the server deploy separately, so what comes back may be from a different version
// or may not come from the server at all (a proxy's JSON page, a half-finished deploy). Check
// the parts the page reads before it renders them; otherwise one missing field is a blank page.

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isCount = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const isIdLike = (value) => typeof value === 'string' || typeof value === 'number';

// The kinds of claim the page has a colour for. 'factual' is the neutral one.
const CLAIM_TYPES = ['legal', 'statistical', 'factual', 'quotation'];
const NEUTRAL_CLAIM_TYPE = 'factual';

/**
 * A claim the page can draw. Only its text is essential; the rest only decorates the card, so a
 * claim that arrives without it (a different version of the server) is repaired, not refused:
 * a confidence that is not a finite number is dropped, a type that is not known becomes the
 * neutral one, and search terms that are not a list of strings are an empty list.
 */
function repairedClaim(claim) {
  return {
    ...claim,
    confidence: Number.isFinite(claim.confidence) ? claim.confidence : undefined,
    claim_type: CLAIM_TYPES.includes(claim.claim_type) ? claim.claim_type : NEUTRAL_CLAIM_TYPE,
    suggested_search_terms: Array.isArray(claim.suggested_search_terms)
      ? claim.suggested_search_terms.filter((term) => typeof term === 'string')
      : [],
  };
}

const STAT_KEYS = ['total_citations', 'complete', 'incomplete', 'needs_verification', 'unsourced_claims'];

function validCitation(c) {
  return (
    isObject(c) &&
    isIdLike(c.id) &&
    typeof c.status === 'string' &&
    typeof c.raw_text === 'string' &&
    (c.parties == null || Array.isArray(c.parties)) &&
    (c.missing == null || Array.isArray(c.missing))
  );
}

/** The analysis response if the page can render it, or null. Optional parts that are wrong are dropped. */
export function normalizeAnalysis(raw) {
  if (!isObject(raw) || !isObject(raw.stats) || !isObject(raw.analysis)) return null;
  if (!STAT_KEYS.every((key) => isCount(raw.stats[key]))) return null;
  const { citations, unsourced_claims: claims } = raw.analysis;
  if (!Array.isArray(citations) || !citations.every(validCitation)) return null;
  if (!Array.isArray(claims) || !claims.every((c) => isObject(c) && typeof c.text === 'string')) return null;
  if (!Array.isArray(raw.short_form_suggestions)) return null;

  const stats = { ...raw.stats };
  ['citations_shown', 'claims_shown'].forEach((key) => {
    if (!isCount(stats[key])) delete stats[key];
  });
  return {
    ...raw,
    stats,
    analysis: { ...raw.analysis, unsourced_claims: claims.map(repairedClaim) },
    lookup: isObject(raw.lookup) ? raw.lookup : undefined,
  };
}

/** The upload response if the page can use it, or null. */
export function normalizeUpload(raw) {
  if (!isObject(raw) || typeof raw.full_text !== 'string' || !isIdLike(raw.document_id)) return null;
  return {
    ...raw,
    filename: typeof raw.filename === 'string' ? raw.filename : 'document',
    warnings: Array.isArray(raw.warnings) ? raw.warnings.filter((w) => typeof w === 'string') : [],
  };
}
