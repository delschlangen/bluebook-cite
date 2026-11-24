import { formatCitation } from './localCitation';

// Fields the editor can change. A card shows the saved values once any of them differ from what
// was found in the document, instead of going on showing the text as it was found.
export const EDIT_FIELDS = [
  'parties', 'volume', 'reporter', 'page', 'pincite', 'court', 'year', 'author', 'title',
  'journal', 'section', 'title_number', 'url',
];

const present = (value) => value !== null && value !== undefined && String(value).trim() !== '';

/** True when `after` differs from `before` in a field the editor can change. */
export function editedFieldsDiffer(before, after) {
  return EDIT_FIELDS.some((key) => JSON.stringify(before[key] ?? null) !== JSON.stringify(after[key] ?? null));
}

const join = (parts, separator = ', ') => parts.filter(present).join(separator);
const withYear = (text, year) => (present(year) ? join([text, `(${year})`], ' ') : text);

/**
 * The citation as its saved fields read. A case the local formatter can complete is given in
 * Bluebook form (with *italics*); anything else is the saved fields in order, which is what was
 * entered and not a claim about how Bluebook would set it.
 */
export function editedCitationText(citation) {
  if (citation.type === 'case') {
    const formatted = formatCitation({ ...citation, parties: citation.parties || [] });
    if (formatted) return formatted;
  }
  switch (citation.type) {
    case 'case': {
      const name = (citation.parties || []).join(' v. ');
      const reporter = join([citation.volume, citation.reporter, citation.page], ' ');
      const paren = join([citation.court, citation.year], ' ');
      const cite = join([name, join([reporter, citation.pincite])]);
      return (paren ? join([cite, `(${paren})`], ' ') : cite) || citation.raw_text;
    }
    case 'statute':
    case 'regulation': {
      const section = present(citation.section) ? `§ ${citation.section}` : '';
      const cite = join([citation.title_number, citation.code, section], ' ');
      return withYear(cite, citation.year) || citation.raw_text;
    }
    case 'law_review': {
      const where = join([citation.volume, citation.journal, citation.page], ' ');
      return withYear(join([citation.author, citation.title, where]), citation.year) || citation.raw_text;
    }
    case 'book':
      return withYear(join([citation.author, citation.title]), citation.year) || citation.raw_text;
    case 'website':
      return join([citation.author, citation.title, citation.url]) || citation.raw_text;
    default:
      return citation.raw_text;
  }
}
