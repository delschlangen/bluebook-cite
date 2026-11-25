// What to put on the page when a request fails: the message, whether sending the same request
// again can help, and how long the server asked to wait. Kept apart from the component so each
// status can be tested on its own.

const TRY_SHORTER =
  'Try a shorter document, or split it at a chapter or section boundary and check the parts one at a time.';
const SPLIT_ADVICE =
  'Use a shorter document, or split it at a chapter or section boundary and check the parts one ' +
  'at a time.';
// Said with the "Reload page" button. Reloading starts from nothing, and "Upload New Document"
// does not help here: it would send the same kind of request to the same server.
const RELOAD_HINT =
  'Reloading the page clears the document that is loaded, so you will need to choose it again.';

/**
 * `err` is an ApiError. `prefix` ("Failed to analyze document") says what was being done; a phone
 * with no connection gets its own sentence without it.
 * Returns { message, hint, canRetry, retryAfter, reload }. `reload` says the remedy is to load
 * the page again (it and the server are out of step), and the caller offers that, not a retry.
 */
export function describeFailure(err, { prefix } = {}) {
  const text = err?.message || 'The request failed.';
  const message = prefix && !err?.deviceOffline ? `${prefix}: ${text}` : text;
  const status = err?.status || 0;

  // The same document would be refused again, and again sends megabytes. Say what to change.
  if (status === 413) {
    return {
      message,
      hint: /split|shorter/i.test(text) ? null : `Sending it again would be refused the same way. ${SPLIT_ADVICE}`,
      canRetry: false,
      retryAfter: null,
      reload: false,
    };
  }
  // The analysis ran out of time. A retry of the same document usually does too, and the old
  // run may still be holding the server.
  if (status === 504) {
    return {
      message,
      hint: /shorter document/i.test(text) ? null : TRY_SHORTER,
      canRetry: false,
      retryAfter: null,
      reload: false,
    };
  }
  // The server said it cannot use what this page sent (422), or refused it (401, 403): the same
  // request would get the same answer, and the page that sent it is probably out of date.
  if (status === 422 || status === 401 || status === 403) {
    return { message, hint: RELOAD_HINT, canRetry: false, retryAfter: null, reload: true };
  }
  // A kind of file it cannot read (415): the same file would be refused again. A different file,
  // through Upload New Document, is the remedy, and nothing here is out of date.
  if (status === 415) {
    return { message, hint: null, canRetry: false, retryAfter: null, reload: false };
  }
  return {
    message,
    hint: null,
    canRetry: true,
    // The server's own "try again in N seconds", for the busy case.
    retryAfter: status === 503 && Number.isFinite(err?.retryAfter) ? err.retryAfter : null,
    reload: false,
  };
}
