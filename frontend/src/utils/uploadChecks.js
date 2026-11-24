// What can be said about a file before it is sent, and how the limits are put to a person.
// Kept apart from the component so the wording and the arithmetic are testable on their own.

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

function formatMb(bytes) {
  const mb = bytes / (1024 * 1024);
  return mb >= 10 ? mb.toFixed(0) : mb.toFixed(1);
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
    `${words.toLocaleString('en-US')} words (roughly ${densePages.toLocaleString('en-US')} to ` +
    `${ordinaryPages.toLocaleString('en-US')} pages); PDFs up to ` +
    `${limits.max_pdf_pages.toLocaleString('en-US')} pages. Footnotes are read.`
  );
}

/** A reason this file cannot work, found without sending it; null if nothing is wrong. */
export function checkFileBeforeUpload(file, limits) {
  const problem = unsupportedReason(file);
  if (problem) return problem;

  const maxBytes = limits.max_upload_mb * 1024 * 1024;
  if (file.size > maxBytes) {
    return (
      `This file is ${formatMb(file.size)} MB. The limit is ${limits.max_upload_mb} MB. ` +
      'Split the document at a chapter or section boundary and check the parts one at a time, ' +
      'or export it again at a smaller size.'
    );
  }
  return null;
}

/** What the upload box says while a file is going up and being read. */
export function uploadingMessage(file) {
  if (!file) return 'Uploading...';
  const size = formatMb(file.size);
  const long = file.size > 2 * 1024 * 1024 || /\.pdf$/i.test(file.name || '');
  return long
    ? `Uploading and reading ${size} MB. A long document can take a minute.`
    : `Uploading ${size} MB...`;
}

/**
 * What to tell the person about the counts in an analysis, when something was left out or not
 * checked. Each entry is one sentence. Empty when nothing was cut.
 */
export function analysisNotices(analysis) {
  const notices = [];
  const stats = analysis?.stats;
  const lookup = analysis?.lookup;

  if (stats?.citations_shown != null && stats.citations_shown < stats.total_citations) {
    notices.push(
      `Found ${stats.total_citations.toLocaleString('en-US')} citations. Showing the first ` +
        `${stats.citations_shown.toLocaleString('en-US')}, in document order.`
    );
  }
  if (lookup && lookup.eligible > 0) {
    if (lookup.skipped > 0) {
      notices.push(
        `Looked up ${lookup.completed.toLocaleString('en-US')} of ` +
          `${lookup.eligible.toLocaleString('en-US')} incomplete citations in outside sources` +
          `${lookup.budget_exhausted ? '; the time limit was reached' : ''}, so ` +
          `${lookup.skipped.toLocaleString('en-US')} were left as found. Check those by hand.`
      );
    }
  }
  return notices;
}

/** The note above the unsourced-claims tab when only some claims are shown, or null. */
export function claimsNotice(stats) {
  if (stats?.claims_shown != null && stats.claims_shown < stats.unsourced_claims) {
    return (
      `Found ${stats.unsourced_claims.toLocaleString('en-US')} statements that may need a ` +
      `citation. Showing the ${stats.claims_shown.toLocaleString('en-US')} most likely.`
    );
  }
  return null;
}
