// What to tell the person after "Look Up in Database": one fixed, plain sentence for each way it
// can end. The reasons the server gives (its "error" text is whatever an outside source or an
// exception said, such as "403 Forbidden (agent proxy ...)") are never printed: a lawyer cannot
// act on them, and they read as the citation's fault.

import { DEVICE_OFFLINE_MESSAGE, UNEXPECTED_FORMAT_MESSAGE, plainStatusMessage } from '../services/api';

const UNCHANGED = 'Your citation was not changed.';

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

/** The name of the place that was searched, or a stand-in when the server did not say. */
function sourceName(results) {
  const source = typeof results?.source === 'string' ? results.source.trim() : '';
  return source || 'the database';
}

/**
 * The note for an answer that arrived: { kind, text }, or null when the lookup found a record
 * (the "Found" panel says so).
 *
 * - `found: false` with nothing else: the source answered and had no such record. Not a verdict
 *   on the citation.
 * - an `error` key at all (even an empty string, which is what a timeout leaves), or `blocked`
 *   or `unavailable`: the source was not reached, so nothing was checked.
 * - an answer that is not an object: this page cannot read it.
 */
export function noteForLookup(results) {
  if (!isObject(results)) {
    return { kind: 'failed', text: `${UNEXPECTED_FORMAT_MESSAGE} ${UNCHANGED}` };
  }
  if (results.found) return null;
  const source = sourceName(results);
  if ('error' in results || results.blocked === true || results.unavailable === true) {
    return {
      kind: 'unreachable',
      text: `${source} could not be reached, so this citation was not checked. ${UNCHANGED}`,
    };
  }
  return {
    kind: 'none',
    text:
      `No matching record was found in ${source}. ${UNCHANGED} ` +
      'That does not mean the citation is wrong.',
  };
}

/**
 * The note for a lookup that failed before any answer: the same plain wording the rest of the
 * page uses for no connection, a busy server and a timeout, and one fixed sentence for anything
 * else. `err` is an ApiError; its message is only used for the kinds whose message the page wrote.
 */
export function noteForLookupFailure(err) {
  let text;
  if (err?.deviceOffline) {
    text = DEVICE_OFFLINE_MESSAGE;
  } else if (err?.offline) {
    text = err.message;
  } else if (err?.timeout) {
    text = err.message;
  } else if (err?.status === 503) {
    const wait = Number.isFinite(err.retryAfter) && err.retryAfter > 0 ? Math.ceil(err.retryAfter) : 0;
    text = wait
      ? `The server is busy. Try again in ${wait} second${wait === 1 ? '' : 's'}.`
      : plainStatusMessage(503);
  } else if (err?.badFormat) {
    text = UNEXPECTED_FORMAT_MESSAGE;
  } else {
    text = 'The look-up could not be completed. Try again in a minute.';
  }
  return { kind: 'failed', text: `${text} ${UNCHANGED}` };
}
