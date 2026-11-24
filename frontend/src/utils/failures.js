// What to put on the page when a request fails: the message, whether sending the same request
// again can help, and how long the server asked to wait. Kept apart from the component so each
// status can be tested on its own.

const TRY_SHORTER =
  'Try a shorter document, or split it at a chapter or section boundary and check the parts one at a time.';
const SPLIT_ADVICE =
  'Use a shorter document, or split it at a chapter or section boundary and check the parts one ' +
  'at a time.';

/**
 * `err` is an ApiError. `prefix` ("Failed to analyze document") says what was being done; a phone
 * with no connection gets its own sentence without it.
 * Returns { message, hint, canRetry, retryAfter }.
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
    };
  }
  return {
    message,
    hint: null,
    canRetry: true,
    // The server's own "try again in N seconds", for the busy case.
    retryAfter: status === 503 && Number.isFinite(err?.retryAfter) ? err.retryAfter : null,
  };
}
