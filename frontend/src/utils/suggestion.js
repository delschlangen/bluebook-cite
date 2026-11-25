import { guidanceFor, missingFields } from './localCitation';

// Compared as text a person would call "the same": no italics markers, one space between words,
// no full stop at the end.
const plain = (value) =>
  String(value ?? '')
    .replace(/\*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\.+$/, '')
    .trim();

/**
 * What the box under a citation says, or null for no box.
 *
 * A suggestion that only repeats what was typed ("District of Columbia v. Heller" suggested for
 * "District of Columbia v. Heller") is not a suggestion, and set in a green box labelled "Suggested
 * (full)" beside an incomplete citation it reads as "this is the full, correct citation". So:
 * - nothing is shown when the suggestion is the input again;
 * - a complete citation keeps "Suggested (full)", or the short form's own label;
 * - any other citation says "Formatted so far", which is all it is.
 */
export function suggestionFor(citation, suggestion) {
  const text = suggestion?.suggested_form;
  if (typeof text !== 'string' || !text) return null;
  if (plain(text) === plain(citation?.raw_text)) return null;
  if (citation?.status === 'complete') {
    const kind = suggestion.short_form_type;
    return { text, label: kind ? `Suggested (${kind}):` : 'Suggested:', complete: true };
  }
  return { text, label: 'Formatted so far:', complete: false };
}

/**
 * The names of what an incomplete citation still lacks, in words: from the `missing` the server
 * sends, or, when it sent none for a case or a U.S. Code citation (the older readers do not fill it
 * in), from the fields the citation lacks. A complete citation lacks nothing.
 */
export function missingLabels(citation) {
  if (!citation || citation.status === 'complete') return [];
  const sent = Array.isArray(citation.missing) ? citation.missing.filter((name) => typeof name === 'string' && name) : [];
  const names =
    sent.length > 0
      ? sent
      : citation.type === 'case' || citation.type === 'statute'
        ? missingFields(citation)
        : [];
  return [...new Set(names.map((name) => guidanceFor(name).label.replace(/_/g, ' ')))];
}
