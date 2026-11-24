// What can be said about a file before it is sent, and how the limits are put to a person.
// Kept apart from the component so the wording and the arithmetic are testable on their own.
import { fmt } from './format';

// File types we can say, with certainty and before uploading, will not work.
// Anything not listed is sent, and the server decides from the file's bytes.
export const KNOWN_UNSUPPORTED = {
  doc: 'Old-format Word (.doc) files are not supported. In Word, choose Save As and pick .docx, or export a PDF.',
  rtf: 'Rich Text Format (.rtf) is not supported. Save it as .docx or PDF.',
  odt: 'OpenDocument (.odt) files are not supported. Save it as .docx or PDF.',
  pages: 'Apple Pages files are not supported. Export to Word (.docx) or PDF first.',
  key: 'Keynote files are not supported. Upload a Word document, PDF or text file.',
  numbers: 'Numbers files are not supported. Upload a Word document, PDF or text file.',
  pptx: 'PowerPoint files are not supported. Upload a Word document, PDF or text file.',
  xlsx: 'Excel files are not supported. Upload a Word document, PDF or text file.',
  jpg: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
  jpeg: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
  png: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
  heic: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
};

export function unsupportedReason(file) {
  const name = (file?.name || '').toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop() : '';
  return KNOWN_UNSUPPORTED[ext] || null;
}

const WORDS_PER_ORDINARY_PAGE = 500;

/** Round an estimate to the nearest ten once it is large enough for that to be honest. */
function roundEstimate(n) {
  return n >= 100 ? Math.round(n / 10) * 10 : n;
}

const MB = 1024 * 1024;

/**
 * A size for the message that refuses a file: one decimal below 100 MB, rounded UP, so the size
 * shown is always above the limit it is being compared with ("10.1 MB" against a 10 MB limit,
 * never "10 MB" against 10 MB).
 */
function formatMbRoundedUp(bytes) {
  if (bytes < 100 * MB) return (Math.ceil((bytes * 10) / MB) / 10).toFixed(1);
  return fmt(Math.ceil(bytes / MB));
}

/** A size for the message while a file is going up: KB for a small file, never "0.0 MB". */
function formatSize(bytes) {
  if (bytes < MB) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(Math.round((bytes * 10) / MB) / 10).toFixed(1)} MB`;
}

/**
 * The limits as shown above the upload box, before anyone picks a file.
 * Built from what the server enforces, so the number shown is the number applied.
 */
export function limitsSummary(limits) {
  const words = limits.approx_max_words || Math.round(limits.max_text_chars / 6);
  // Page counts are estimates, so they are rounded: "348" claims a precision nobody has.
  const densePages = roundEstimate(limits.approx_max_pages || Math.round(limits.max_text_chars / 4300));
  const ordinaryPages = roundEstimate(Math.round(words / WORDS_PER_ORDINARY_PAGE));
  return (
    `Up to ${limits.max_upload_mb} MB. Word and text files up to about ` +
    `${fmt(words)} words (roughly ${fmt(densePages)} to ` +
    `${fmt(ordinaryPages)} pages); PDFs up to ` +
    `${fmt(limits.max_pdf_pages)} pages. Footnotes are read.`
  );
}

/** A reason this file cannot work, found without sending it; null if nothing is wrong. */
export function checkFileBeforeUpload(file, limits) {
  const problem = unsupportedReason(file);
  if (problem) return problem;

  const maxBytes = limits.max_upload_mb * 1024 * 1024;
  if (file.size > maxBytes) {
    return (
      `This file is ${formatMbRoundedUp(file.size)} MB. The limit is ${limits.max_upload_mb} MB. ` +
      'Split the document at a chapter or section boundary and check the parts one at a time, ' +
      'or export it again at a smaller size.'
    );
  }
  return null;
}

/** What the upload box says while a file is going up and being read. */
export function uploadingMessage(file) {
  if (!file) return 'Uploading...';
  const size = formatSize(file.size);
  const long = file.size > 2 * MB || /\.pdf$/i.test(file.name || '');
  return long
    ? `Uploading and reading ${size}. A long document can take a minute.`
    : `Uploading ${size}...`;
}

/** What the upload box says while it is finding out why the upload did not finish. */
export const CHECKING_SERVER_MESSAGE =
  'The upload did not finish. Checking whether the server is still running... ' +
  'This can take up to half a minute.';

/** A count the server sent, or null when it is missing or not a usable number. */
function count(value) {
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** The sentence about outside lookups, or null when there is nothing to say. */
function lookupNotice(lookup) {
  if (!lookup || !(lookup.eligible > 0)) return null;
  const skipped = count(lookup.skipped) ?? 0;
  const matched = count(lookup.matched);
  const failed = count(lookup.failed);
  const limit = lookup.budget_exhausted ? '; the time limit was reached' : '';

  // A server that reports how each lookup ended. "Looked up 200 of 218" would read as 200
  // successes when an outside source being unreachable ends a lookup too, so say what happened.
  if (matched !== null || failed !== null) {
    const completed = count(lookup.completed) ?? 0;
    const unmatched = matched !== null && matched < completed;
    if (skipped === 0 && !failed && !unmatched) return null;
    const outcomes = [];
    if (matched !== null) outcomes.push(`${fmt(matched)} matched`);
    if (failed) outcomes.push(`${fmt(failed)} could not be reached`);
    return (
      `Checked ${fmt(completed)} of ${fmt(lookup.eligible)} incomplete citations in outside ` +
      `sources${limit}: ${outcomes.join(', ')}. ` +
      'The rest, and any that did not match, need checking by hand.'
    );
  }

  // An older server that only says how many lookups finished.
  if (skipped > 0) {
    return (
      `Looked up ${fmt(lookup.completed)} of ${fmt(lookup.eligible)} incomplete citations in ` +
      `outside sources${limit}, so ${fmt(skipped)} were left as found. Check those by hand.`
    );
  }
  return null;
}

/**
 * What to tell the person about the counts in an analysis, when something was left out or not
 * checked. Each entry is one sentence. Empty when nothing was cut.
 */
export function analysisNotices(analysis) {
  const notices = [];
  const stats = analysis?.stats;

  if (stats?.citations_shown != null && stats.citations_shown < stats.total_citations) {
    notices.push(
      `Found ${fmt(stats.total_citations)} citations. Showing the first ` +
        `${fmt(stats.citations_shown)}, in document order.`
    );
  }
  const lookup = lookupNotice(analysis?.lookup);
  if (lookup) notices.push(lookup);
  return notices;
}

/** The note above the unsourced-claims tab when only some claims are shown, or null. */
export function claimsNotice(stats) {
  if (stats?.claims_shown != null && stats.claims_shown < stats.unsourced_claims) {
    return (
      `Found ${fmt(stats.unsourced_claims)} statements that may need a ` +
      `citation. Showing the ${fmt(stats.claims_shown)} most likely.`
    );
  }
  return null;
}
