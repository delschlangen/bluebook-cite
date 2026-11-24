/**
 * Local Bluebook formatting.
 *
 * Parsing a citation, working out which fields it is missing, and formatting a
 * complete one are all pure computation. Only *finding* missing pieces needs a
 * database. Doing the local half in the browser means the tool still works when the
 * backend is asleep, down or unreachable, and it answers instantly.
 *
 * Two readers cooperate here. The data-driven engine (citationEngine.js, fed by
 * citationSpec.json, which is generated from the Python source of truth) understands
 * most kinds of citation. The older case and U.S. Code readers below remain because
 * case names need judgement that a template cannot express. Whichever accounts for
 * more of the pasted text wins, and the engine wins ties.
 */

import {
  CITATION_TEMPLATES,
  FIELD_GUIDANCE,
  UNICODE_NORMALIZATION,
} from './bluebookTables';
import spec from './citationSpec.json';
import { createEngine } from './citationEngine';
import { abbreviateParty } from './transforms';

export { abbreviateParty };

export const ENGINE = createEngine(spec);

const NORMALIZE_PATTERN = new RegExp(`[${Object.keys(UNICODE_NORMALIZATION).join('')}]`, 'g');

/**
 * Replace typographic punctuation with the plain characters the patterns expect.
 * An iPhone keyboard turns apostrophes and hyphens into curly quotes and en dashes,
 * which defeated every pattern. One character for one character, so offsets are
 * unchanged. The table is generated from the Python source.
 */
export function normalizeText(text) {
  return (text || '').replace(NORMALIZE_PATTERN, (ch) => UNICODE_NORMALIZATION[ch]);
}

// Entity suffixes that legitimately follow a comma inside a party name. Without
// these, "NetChoice, LLC v. Paxton" parses as "LLC v. Paxton".
const ENTITY_SUFFIX = String.raw`(?:Inc|LLC|L\.L\.C|Corp|Co|Ltd|L\.P|LP|LLP|PLLC|P\.C|N\.A|S\.A|PLC|Ass'n|Assn|Found|Univ)\.?`;
// Must contain a letter. A purely numeric token is never part of a party name, and
// allowing one let "Brandenburg v Ohio 395 US 444" absorb the volume, reporter and
// page into the defendant, then report all three as missing.
// A standalone "Id." is the short form for the authority just cited and is never a word in a
// party name (the Python side has the same rule; "Idaho" and "Ida." are unaffected).
const NOT_ID = String.raw`(?!Id\.(?![A-Za-z0-9]))`;
const PARTY_WORD = String.raw`(?:${NOT_ID}[A-Za-z][A-Za-z0-9.'&\-]*|[0-9]+[A-Za-z][A-Za-z0-9.'&\-]*)`;
// The first token may also begin with digits followed by a letter ("3M"), but not
// with digits alone, so "395 US" cannot start a party name.
const PARTY_FIRST = String.raw`(?:${NOT_ID}[A-Z][A-Za-z0-9.'&\-]*|[0-9]+[A-Z][A-Za-z0-9.'&\-]*)`;
const PARTY = String.raw`${PARTY_FIRST}(?:\s+${PARTY_WORD}){0,7}(?:,\s*${ENTITY_SUFFIX})?`;

const CASE_COMPLETE = new RegExp(
  `(${PARTY})\\s+v\\.?\\s+(${PARTY}),\\s*` +
    String.raw`(\d+)\s+([A-Z][a-zA-Z.\s\d]*?[a-zA-Z.\d])\s+(\d+)` +
    String.raw`(?:,\s*(\d+(?:-\d+)?))?\s*` +
    String.raw`\(([^)]+)\)`
);

const CASE_NO_YEAR = new RegExp(
  `(${PARTY})\\s+v\\.?\\s+(${PARTY}),?\\s+` +
    String.raw`(\d+)\s+([A-Z][a-zA-Z.\s\d]*?[a-zA-Z.\d])\s+(\d+)` +
    String.raw`(?!\s*[\d,]*\s*\()`
);

const CASE_INCOMPLETE = new RegExp(`(${PARTY})\\s+v\\.?\\s+(${PARTY})`);

// "47 USC 230", "47 U.S.C. § 230", "47 U.S.C. §230(c)(1)". The Code of Federal
// Regulations is handled by the engine, where its year requirement is encoded.
const STATUTE = /(\d+)\s+U\.?\s?S\.?\s?C\.?\s*(?:§+\s*)?(\d+[a-z]?)(?:\(([^)]+)\))?/i;

const SIGNAL_WORDS = new Set([
  'the', 'see', 'in', 'but', 'cf.', 'also', 'that', 'compare', 'accord',
]);
const BOUNDARY_WORDS = new Set([
  'in', 'see', 'but', 'cf.', 'compare', 'e.g.', 'accord',
  'held', 'ruled', 'found', 'stated', 'noted', 'concluded',
]);
const LEGAL_NAME_PREFIXES = [
  'in re ', 'ex parte ', 'ex rel. ', 'in the matter of ', 'matter of ',
  'estate of ',
];

const FIELD_LABELS = {
  parties: 'party names',
  volume: 'volume number',
  reporter: 'reporter',
  page: 'first page',
  year: 'year',
  title_number: 'title number',
  code: 'code',
  section: 'section',
};

/** Trim prose the greedy party pattern swallowed before " v. ". */
export function cleanPartyName(name) {
  const trimmed = (name || '').trim();
  if (!trimmed) return trimmed;

  const lowered = trimmed.toLowerCase();
  // "In re Grand Jury" is the party name, not prose plus a party name.
  if (LEGAL_NAME_PREFIXES.some((p) => lowered.startsWith(p))) return trimmed;

  let words = trimmed.split(/\s+/);
  let start = 0;

  for (let i = words.length - 1; i >= 0; i -= 1) {
    const word = words[i];
    const bare = word.toLowerCase().replace(/[.,;:]+$/, '');

    const isAbbrev = word.length <= 4 && word.endsWith('.');
    if (i < words.length - 1 && word.endsWith('.') && !isAbbrev) {
      start = i + 1;
      break;
    }
    if (BOUNDARY_WORDS.has(bare)) {
      start = i + 1;
      break;
    }
    if (words.length - i > 6) {
      start = i + 1;
      break;
    }
  }

  words = words.slice(start);
  // "The" goes per Rule 10.2.1(d). "A" and "An" do not.
  while (words.length && SIGNAL_WORDS.has(words[0].toLowerCase()) && words[0] !== 'A') {
    words = words.slice(1);
  }
  return words.join(' ').trim() || trimmed;
}

function parseParenthetical(text) {
  const yearMatch = /(\d{4})/.exec(text || '');
  if (!yearMatch) return { court: null, year: null };
  const court = text.replace(yearMatch[1], '').trim();
  return { court: court || null, year: Number(yearMatch[1]) };
}

/**
 * Read a case or a U.S. Code citation, and say how much of the input it accounts for.
 * Returns null when nothing recognisable is present.
 */
export function parseCitationWithSpan(input) {
  const text = (input || '').trim();
  if (!text) return null;

  const complete = CASE_COMPLETE.exec(text);
  if (complete) {
    const { court, year } = parseParenthetical(complete[7]);
    return {
      length: complete[0].length,
      parsed: {
        type: 'case',
        parties: [cleanPartyName(complete[1]), cleanPartyName(complete[2])],
        volume: complete[3],
        reporter: complete[4].trim(),
        page: complete[5],
        pincite: complete[6] || null,
        court,
        year,
      },
    };
  }

  const statute = STATUTE.exec(text);
  if (statute) {
    return {
      length: statute[0].length,
      parsed: {
        type: 'statute',
        title_number: statute[1],
        code: 'U.S.C.',
        section: statute[2],
        subsection: statute[3] || null,
      },
    };
  }

  const noYear = CASE_NO_YEAR.exec(text);
  if (noYear) {
    return {
      length: noYear[0].length,
      parsed: {
        type: 'case',
        parties: [cleanPartyName(noYear[1]), cleanPartyName(noYear[2])],
        volume: noYear[3],
        reporter: noYear[4].trim(),
        page: noYear[5],
        pincite: null,
        court: null,
        year: null,
      },
    };
  }

  const partial = CASE_INCOMPLETE.exec(text);
  if (partial) {
    return {
      length: partial[0].length,
      parsed: {
        type: 'case',
        parties: [cleanPartyName(partial[1]), cleanPartyName(partial[2])],
        volume: null,
        reporter: null,
        page: null,
        pincite: null,
        court: null,
        year: null,
      },
    };
  }

  return null;
}

export function parseCitation(input) {
  const read = parseCitationWithSpan(input);
  return read ? read.parsed : null;
}

const REQUIRED = {
  case: ['parties', 'volume', 'reporter', 'page', 'year'],
  statute: ['title_number', 'code', 'section'],
};

export function missingFields(parsed) {
  if (!parsed) return [];
  return (REQUIRED[parsed.type] || []).filter((field) => {
    const value = parsed[field];
    if (field === 'parties') return !(Array.isArray(value) && value.length >= 2);
    return value === null || value === undefined || value === '';
  });
}

// Reporters that carry U.S. Supreme Court decisions, normalised.
const SCOTUS_REPORTERS = new Set(['US', 'SCT', 'LED', 'LED2D']);

/** True when this reporter publishes U.S. Supreme Court decisions. */
export function isScotusReporter(reporter) {
  if (!reporter) return false;
  return SCOTUS_REPORTERS.has(reporter.replace(/[^a-z0-9]/gi, '').toUpperCase());
}

/**
 * Label, governing Bluebook rule and explanation for one field. `display_rule` is the
 * rule that is safe to SHOW: the nearest verified one, never an unconfirmed number.
 */
export function guidanceFor(fieldName) {
  const entry = FIELD_GUIDANCE[fieldName];
  if (!entry) {
    return { field: fieldName, label: fieldName, rule: '', display_rule: null, why: '' };
  }
  return { field: fieldName, ...entry, display_rule: ENGINE.displayRule(entry.rule) };
}

/**
 * Render the citation in its finished shape with the gaps marked.
 *
 * Naming the missing fields says what is wrong. Showing the whole citation with
 * holes in it shows what the reader is actually trying to produce.
 */
export function buildTemplate(parsed, missing) {
  if (!parsed) return null;
  const template = CITATION_TEMPLATES[parsed.type];
  if (!template) return null;

  const gaps = new Set(missing || []);
  const slot = (name) => {
    const value = parsed[name];
    if (gaps.has(name) || value === null || value === undefined || value === '') {
      return `[${guidanceFor(name).label}]`;
    }
    return String(value);
  };

  if (parsed.type === 'case') {
    const parties =
      parsed.parties && parsed.parties.length >= 2
        ? `${abbreviateParty(parsed.parties[0])} v. ${abbreviateParty(parsed.parties[1])}`
        : '[party names]';

    // Rule 10.4: the U.S. Supreme Court takes no court identifier, so the slot is
    // dropped rather than shown as a gap the reader has to fill.
    let court;
    if (isScotusReporter(parsed.reporter)) court = '';
    else if (parsed.court) court = `${parsed.court} `;
    else court = '[court] ';

    return template
      .replace('{parties}', parties)
      .replace('{volume}', slot('volume'))
      .replace('{reporter}', slot('reporter'))
      .replace('{page}', slot('page'))
      .replace('{court}', court)
      .replace('{year}', slot('year'));
  }

  return template.replace(/\{(\w+)\}/g, (_, name) => slot(name));
}

/** Format per Rule 10 (cases) and Rule 12 (the U.S. Code). */
export function formatCitation(parsed) {
  if (!parsed) return null;

  if (parsed.type === 'case') {
    if (!parsed.parties || parsed.parties.length < 2) return null;
    const name = `${abbreviateParty(parsed.parties[0])} v. ${abbreviateParty(parsed.parties[1])}`;
    if (!parsed.volume || !parsed.reporter || !parsed.page) return null;

    let reporterCite = `${parsed.volume} ${parsed.reporter} ${parsed.page}`;
    if (parsed.pincite) reporterCite += `, ${parsed.pincite}`;

    // Rule 10.4: no court identifier for the U.S. Supreme Court.
    let parenthetical = '';
    if (parsed.year) {
      const suppressCourt = !parsed.court || isScotusReporter(parsed.reporter);
      parenthetical = suppressCourt ? String(parsed.year) : `${parsed.court} ${parsed.year}`;
    }
    return `*${name}*, ${reporterCite}${parenthetical ? ` (${parenthetical})` : ''}.`;
  }

  if (parsed.type === 'statute') {
    if (!parsed.title_number || !parsed.section) return null;
    let base = `${parsed.title_number} ${parsed.code} § ${parsed.section}`;
    if (parsed.subsection) base += `(${parsed.subsection})`;
    return `${base}.`;
  }

  return null;
}

const CAUTION =
  'This format is less thoroughly checked than the others. Confirm it in your Bluebook ' +
  'before relying on it.';

function baseResult(text, style) {
  return {
    input: text,
    status: 'unparseable',
    citation_type: null,
    kind: null,
    kind_label: null,
    format_confidence: null,
    style,
    parsed: {},
    missing: [],
    missing_labels: [],
    missing_details: [],
    template: null,
    formatted: null,
    confidence: null,
    source: null,
    verify_url: null,
    candidates: [],
    notes: [],
    needsLookup: false,
    offline: true,
  };
}

/** A citation the data-driven engine understood. */
function fromEngine(text, match, style) {
  const typeSpec = ENGINE.typeSpec(match.typeId);
  const missing = ENGINE.missing(match.typeId, match.fields);
  const formatted = ENGINE.render(match.typeId, match.fields, style);
  const byName = Object.fromEntries(typeSpec.fields.map((f) => [f.name, f]));

  const notes = [
    formatted
      ? 'This citation was already complete. Formatting applied.'
      : 'The fields above are what this citation still needs.',
    ...(typeSpec.notes || []),
  ];
  if (typeSpec.confidence !== 'high') notes.push(CAUTION);

  return {
    ...baseResult(text, style),
    status: formatted ? 'resolved' : 'incomplete',
    citation_type: typeSpec.citation_type,
    kind: typeSpec.id,
    kind_label: typeSpec.label,
    format_confidence: typeSpec.confidence,
    parsed: match.fields,
    missing,
    missing_labels: missing.map((n) => byName[n].label),
    missing_details: missing.map((n) => ({
      field: n,
      label: byName[n].label,
      rule: byName[n].rule || '',
      display_rule: ENGINE.displayRule(byName[n].rule),
      why: byName[n].why || '',
    })),
    template: ENGINE.render(match.typeId, match.fields, style, true),
    formatted,
    confidence: formatted ? 1 : null,
    source: formatted ? 'your input' : null,
    notes,
    // No free source can verify a record for these kinds, so a server round trip
    // could add nothing. The answer here is final.
    needsLookup: false,
  };
}

/** A case or U.S. Code citation, read by the older readers. */
function fromLegacy(text, parsed, style) {
  const missing = missingFields(parsed);
  const formatted = missing.length === 0 ? formatCitation(parsed) : null;
  return {
    ...baseResult(text, style),
    status: formatted ? 'resolved' : 'incomplete',
    citation_type: parsed.type,
    parsed,
    missing,
    missing_labels: missing.map((f) => FIELD_LABELS[f] || f),
    missing_details: missing.map(guidanceFor),
    template: buildTemplate(parsed, missing),
    formatted,
    confidence: formatted ? 1 : null,
    source: formatted ? 'your input' : null,
    notes: formatted
      ? ['This citation was already complete. Formatting applied.']
      : ['The fields above are what this citation still needs.'],
    // Only a lookup can fill these gaps, and only the server can do a lookup.
    needsLookup: missing.length > 0,
  };
}

/**
 * The local half of /api/repair. Same response shape, so the UI renders either
 * without branching.
 *
 * `needsLookup` tells the caller whether a server round trip could add anything.
 * When it is false, the answer here is final and complete.
 */
export function repairLocally(input, style = 'law_review') {
  const text = normalizeText(input).trim();
  if (!text) {
    return { ...baseResult(text, style), notes: ['Nothing to repair. Paste a citation or part of one.'] };
  }

  const engineMatch = ENGINE.bestMatch(text);
  const legacy = parseCitationWithSpan(text);
  const engineLength = engineMatch ? engineMatch.end - engineMatch.start : -1;
  const legacyLength = legacy ? legacy.length : -1;

  // Whichever reading accounts for more of what was pasted wins. The engine wins ties.
  if (engineMatch && engineLength >= legacyLength) return fromEngine(text, engineMatch, style);
  if (legacy) return fromLegacy(text, legacy.parsed, style);

  return {
    ...baseResult(text, style),
    notes: [
      'This does not look like a kind of citation this tool recognises yet. ' +
        'Choose the kind of source below to see what its citation needs.',
    ],
    // The browser cannot read books, articles or websites, but the server can, so a
    // paste it does not recognise is worth a second opinion.
    needsLookup: true,
  };
}

/** Every kind the tool knows, grouped for the browse view, each with a worked example. */
export function browseTypes(style = 'law_review') {
  return spec.families
    .map((family) => ({
      ...family,
      types: spec.types
        .filter((t) => t.family === family.id)
        .map((t) => ({
          id: t.id,
          label: t.label,
          confidence: t.confidence,
          recognises: t.patterns.length > 0,
          example: ENGINE.renderExample(t.id, style),
          template: ENGINE.render(t.id, {}, style, true),
          fields: t.fields.map((f) => ({
            ...f,
            display_rule: ENGINE.displayRule(f.rule),
          })),
          notes: t.notes || [],
        })),
    }))
    .filter((family) => family.types.length > 0);
}

export const EDITION_NOTE = spec.edition_note || '';
