/**
 * Transforms used by citation templates. A line-for-line twin of
 * backend/app/services/transforms.py. shared/engine_conformance.json holds the
 * expected answers that both implementations must produce.
 */

import { PARTY_ABBREVIATIONS, STATE_ABBREVIATIONS } from './bluebookTables';
import { registerTransform } from './citationEngine';

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// --- Roman numerals (Rule 11: articles and amendments) ---------------------

const ROMAN = [
  [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
  [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
];

export function roman(value) {
  const v = value.trim();
  if (/^\d+$/.test(v)) {
    let n = parseInt(v, 10);
    if (n < 1 || n > 3999) return v;
    let out = '';
    ROMAN.forEach(([size, letters]) => {
      while (n >= size) {
        out += letters;
        n -= size;
      }
    });
    return out;
  }
  return v.toUpperCase();
}

// --- Numbers (Rule 6.2) -----------------------------------------------------

export function thousands(value) {
  // String-based on purpose: a Number cannot hold a very long run of digits exactly.
  return value.replace(/\d{5,}/g, (run) => run.replace(/\B(?=(\d{3})+(?!\d))/g, ','));
}

export function ordinal(value) {
  const m = /^\s*(\d+)(?:st|nd|rd|th|d)?\s*$/i.exec(value);
  if (!m) return value;
  const n = parseInt(m[1], 10);
  let suffix;
  if (n % 100 >= 11 && n % 100 <= 13) suffix = 'th';
  else if (n % 10 === 1) suffix = 'st';
  else if (n % 10 === 2 || n % 10 === 3) suffix = 'd';
  else suffix = 'th';
  return `${n}${suffix}`;
}

// --- Dates (Table T12) ------------------------------------------------------

const MONTHS = {
  jan: 'Jan.', january: 'Jan.',
  feb: 'Feb.', february: 'Feb.',
  mar: 'Mar.', march: 'Mar.',
  apr: 'Apr.', april: 'Apr.',
  may: 'May',
  jun: 'June', june: 'June',
  jul: 'July', july: 'July',
  aug: 'Aug.', august: 'Aug.',
  sep: 'Sept.', sept: 'Sept.', september: 'Sept.',
  oct: 'Oct.', october: 'Oct.',
  nov: 'Nov.', november: 'Nov.',
  dec: 'Dec.', december: 'Dec.',
};
const MONTH_BY_NUMBER = [
  null, 'Jan.', 'Feb.', 'Mar.', 'Apr.', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.',
];
const MONTH_PATTERN = Object.keys(MONTHS)
  .sort((a, b) => b.length - a.length)
  .join('|');

export function bbdate(value) {
  const text = value.trim();

  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (m) {
    const month = parseInt(m[2], 10);
    const day = parseInt(m[3], 10);
    if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      return `${MONTH_BY_NUMBER[month]} ${day}, ${parseInt(m[1], 10)}`;
    }
    return value;
  }

  m = new RegExp(`^(${MONTH_PATTERN})\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?,?\\s+(\\d{4})$`, 'i').exec(text);
  if (m) return `${MONTHS[m[1].toLowerCase()]} ${parseInt(m[2], 10)}, ${m[3]}`;

  m = new RegExp(`^(\\d{1,2})\\s+(${MONTH_PATTERN})\\.?,?\\s+(\\d{4})$`, 'i').exec(text);
  if (m) return `${MONTHS[m[2].toLowerCase()]} ${parseInt(m[1], 10)}, ${m[3]}`;

  m = new RegExp(`^(${MONTH_PATTERN})\\.?,?\\s+(\\d{4})$`, 'i').exec(text);
  if (m) return `${MONTHS[m[1].toLowerCase()]} ${m[2]}`;

  return value;
}

// --- Congress (Rule 13) -----------------------------------------------------

export function chamber(value) {
  const key = value.replace(/[\s.]/g, '').toUpperCase();
  return { HR: 'H.R.', S: 'S.' }[key] || value;
}

// --- Authors and sources ----------------------------------------------------

export function abbreviateParty(name) {
  let result = (name || '').trim();
  if (!result) return result;

  if (/^the\s+/i.test(result)) result = result.replace(/^the\s+/i, '');

  // Longest first: "Virginia" is itself a state, so protecting it before
  // "West Virginia" would leave a bare "West" for Table 6 to turn into "W.".
  const protectedNames = [];
  Object.keys(STATE_ABBREVIATIONS)
    .sort((a, b) => b.length - a.length)
    .forEach((state) => {
      if (result.includes(state)) {
        const token = `\u0000${protectedNames.length}\u0000`;
        result = result.split(state).join(token);
        protectedNames.push(state);
      }
    });

  Object.entries(PARTY_ABBREVIATIONS).forEach(([full, abbrev]) => {
    result = result.replace(new RegExp(`\\b${escapeRegExp(full)}\\b`, 'gi'), abbrev);
  });

  protectedNames.forEach((state, i) => {
    result = result.split(`\u0000${i}\u0000`).join(state);
  });

  return result.trim();
}

const INSTITUTION_EXTRAS = { Office: 'Off.', Congressional: 'Cong.' };

export function institution(value) {
  let out = abbreviateParty(value);
  Object.entries(INSTITUTION_EXTRAS).forEach(([full, abbrev]) => {
    out = out.replace(new RegExp(`\\b${full}\\b`, 'gi'), abbrev);
  });
  return out;
}

const PAPERS = {
  nytimes: 'N.Y. Times', newyorktimes: 'N.Y. Times', thenewyorktimes: 'N.Y. Times',
  washingtonpost: 'Wash. Post', thewashingtonpost: 'Wash. Post', washpost: 'Wash. Post',
  wallstreetjournal: 'Wall St. J.', thewallstreetjournal: 'Wall St. J.', wallstj: 'Wall St. J.',
  latimes: 'L.A. Times', losangelestimes: 'L.A. Times', thelosangelestimes: 'L.A. Times',
  usatoday: 'USA Today',
  bostonglobe: 'Bos. Globe', thebostonglobe: 'Bos. Globe', bosglobe: 'Bos. Globe',
  chicagotribune: 'Chi. Trib.', thechicagotribune: 'Chi. Trib.', chitrib: 'Chi. Trib.',
};

export function paper(value) {
  return PAPERS[value.toLowerCase().replace(/[^a-z]/g, '')] || value;
}

const STATES_BY_NAME = Object.fromEntries(
  Object.entries(STATE_ABBREVIATIONS).map(([name, abbr]) => [name.toLowerCase(), abbr])
);

export function stateAbbr(value) {
  return STATES_BY_NAME[value.trim().toLowerCase()] || value;
}

// --- Title capitalisation (Rule 8) ------------------------------------------
// See the Python twin for the rule, its sources and its stated limits.

const SMALL_WORDS = new Set([
  'a', 'an', 'the',
  'and', 'but', 'or', 'nor', 'for', 'as', 'if', 'than',
  'at', 'by', 'in', 'of', 'on', 'to', 'per', 'via', 'from', 'into', 'onto',
  'upon', 'with', 'amid', 'atop', 'unto',
]);

function casePiece(word, forceCapital) {
  // A capital anywhere after the first letter marks an acronym or a name.
  if ([...word.slice(1)].some((c) => c !== c.toLowerCase() && c === c.toUpperCase())) return word;
  if (!forceCapital && SMALL_WORDS.has(word.toLowerCase())) return word.toLowerCase();
  return word.slice(0, 1).toUpperCase() + word.slice(1);
}

function caseWord(token, forceCapital) {
  const m = /^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$/s.exec(token);
  const [, lead, core, trail] = m;
  if (!core) return token;

  if (core.includes('-')) {
    const cased = core
      .split('-')
      .map((p, i) => casePiece(p, i === 0 ? forceCapital : true));
    return lead + cased.join('-') + trail;
  }
  return lead + casePiece(core, forceCapital) + trail;
}

function titlecaseWith(value, firstForced) {
  if (!value || !/[a-z]/.test(value)) return value; // empty, or typed entirely in capitals

  const parts = value.split(/(\s+)/);
  let capitaliseNext = firstForced;
  return parts
    .map((part) => {
      if (!part || /^\s+$/.test(part)) return part;
      const cased = caseWord(part, capitaliseNext);
      capitaliseNext = part.endsWith(':');
      return cased;
    })
    .join('');
}

export function titlecase(value) {
  return titlecaseWith(value, true);
}

// Rule 8 for a title that does not begin the citation: the first word is not forced
// to a capital, so "of the Law Governing Lawyers" keeps its "the".
export function titlecaseMid(value) {
  return titlecaseWith(value, false);
}

// Acronyms that stay in capitals when text typed entirely in capitals is brought back
// to ordinary case. See the Python twin for why this is a short curated list.
const ACRONYMS = new Set([
  'GAO', 'CRS', 'CBO', 'OMB', 'EPA', 'FDA', 'FTC', 'SEC', 'DOJ', 'DOD', 'HHS', 'IRS',
  'NLRB', 'FCC', 'FERC', 'NASA', 'RAND', 'OECD', 'UN', 'US', 'ACLU', 'ABA', 'AALL',
  'NAACP', 'ATF', 'FBI', 'CIA', 'NSA', 'DHS', 'USDA', 'HUD', 'VA', 'TSA', 'ICE', 'CDC',
  'NIH', 'NSF', 'OSHA', 'EEOC', 'FEMA', 'FAA', 'FHA', 'SBA', 'USPS', 'DEA', 'ATM',
  'NATO', 'WHO', 'IMF', 'EU', 'UK', 'NCAA', 'AARP', 'AFL-CIO',
]);

export function decaps(value) {
  if (!value || /[a-z]/.test(value)) return value;

  const lowerToken = (token) => {
    const core = token.replace(/^[.,;:()"']+|[.,;:()"']+$/g, '');
    if (/\.[A-Za-z]/.test(token) || ACRONYMS.has(core.toUpperCase())) return token;
    return token.toLowerCase();
  };

  const lowered = value
    .split(/(\s+)/)
    .map((part) => (/^\s+$/.test(part) ? part : lowerToken(part)))
    .join('');
  return titlecaseWith(lowered, true);
}

export function registerAll() {
  registerTransform('roman', roman);
  registerTransform('thousands', thousands);
  registerTransform('ordinal', ordinal);
  registerTransform('bbdate', bbdate);
  registerTransform('chamber', chamber);
  registerTransform('institution', institution);
  registerTransform('paper', paper);
  registerTransform('state_abbr', stateAbbr);
  registerTransform('titlecase', titlecase);
  registerTransform('titlecase_mid', titlecaseMid);
  registerTransform('decaps', decaps);
}

registerAll();
