const API_URL = import.meta.env.VITE_API_URL || '';

// How long each kind of request may take before the page gives up on it. One number for all of
// them was wrong in both directions: too long for a health probe, far too short for uploading a
// large file on a phone and having a long document analysed (45 s cut off real, working requests
// and then blamed the server).
export const TIMEOUTS = {
  default: 45000,
  health: 8000,
  repair: 30000,
  analyze: 120000,
};

const MB = 1024 * 1024;
// 25 s per MB is about 320 kbps, a poor phone connection. Uploads and analysis requests share it.
const SEND_MS_PER_MB = 25000;

/** Upload time allowed for a file: 30 s plus 25 s per MB (about 320 kbps), capped at 5 minutes. */
export function uploadTimeoutMs(bytes) {
  const megabytes = Math.ceil((bytes || 0) / MB);
  return Math.min(300000, 30000 + megabytes * SEND_MS_PER_MB);
}

/**
 * Time allowed for an analysis. The request carries the whole text again, so on a slow link
 * just sending it can take a minute; the server then has up to 90 s of its own, plus a margin.
 * 120 s for a small body, 100 s plus the sending time at the upload rate for a large one.
 */
export function analyzeTimeoutMs(bodyBytes) {
  const sendMs = Math.ceil(((bodyBytes || 0) / MB) * SEND_MS_PER_MB);
  return Math.max(TIMEOUTS.analyze, 100000 + sendMs);
}

// What the server enforces, until it says otherwise. /health publishes the real values, and
// they replace these as soon as the page has seen them, so a limit changed on the server is
// the number shown without a new build of the page.
export const DEFAULT_LIMITS = {
  max_upload_mb: 10,
  max_text_chars: 1500000,
  max_pdf_pages: 400,
  approx_max_words: 250000,
  approx_max_pages: 348,
  // What "Fix a citation" takes (the server refuses more with a 413). /health does not publish
  // it yet; if a later server does, that number replaces this one.
  max_repair_chars: 2000,
};

let serverLimits = null;
const limitListeners = new Set();

export function getLimits() {
  return { ...DEFAULT_LIMITS, ...(serverLimits || {}) };
}

/** Call `listener(limits)` whenever the server's limits become known. Returns an unsubscribe. */
export function subscribeLimits(listener) {
  limitListeners.add(listener);
  return () => limitListeners.delete(listener);
}

const isPositiveNumber = (value) => typeof value === 'number' && Number.isFinite(value) && value > 0;

// /health is another deploy's output. A limit that is null, negative, NaN or text would blank
// the upload box or make every file look too big, so only usable numbers are kept.
function learnLimits(health) {
  const reported = health?.limits;
  if (!reported || typeof reported !== 'object' || Array.isArray(reported)) return;
  const usable = {};
  Object.keys(DEFAULT_LIMITS).forEach((key) => {
    if (isPositiveNumber(reported[key])) usable[key] = reported[key];
  });
  if (Object.keys(usable).length === 0) return;
  serverLimits = usable;
  limitListeners.forEach((listener) => listener(getLimits()));
}

export const DEVICE_OFFLINE_MESSAGE = 'You appear to be offline. Check your connection and try again.';

export const UNEXPECTED_FORMAT_MESSAGE =
  'The server answered in a format this page does not understand. It may be in the middle of ' +
  'an update. Wait a minute and try again.';

class ApiError extends Error {
  constructor(
    message,
    {
      status = 0,
      timeout = false,
      offline = false,
      deviceOffline = false,
      cancelled = false,
      badFormat = false,
      retryAfter = null,
      sent = null,
    } = {}
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.timeout = timeout;
    // No response at all: the caller should find out why before saying anything about the server.
    this.offline = offline;
    // The phone itself reports no connection. Nothing was sent and nothing needs probing.
    this.deviceOffline = deviceOffline;
    this.cancelled = cancelled;
    // The server answered 200 with something that is not what this page expects.
    this.badFormat = badFormat;
    // Seconds the server asked to wait before trying again, when it said.
    this.retryAfter = retryAfter;
    // For a request that got no response: when it was sent and when it failed (ms since the
    // epoch), and the process id the page knew at the moment it was sent, and when it learned it.
    // explainNetworkFailure uses these to claim only what they support.
    this.sent = sent;
  }
}

const cancelledError = () => new ApiError('The request was cancelled.', { cancelled: true });

/** True when the browser says the device has no connection. */
export function isDeviceOffline() {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}

/**
 * Plain words for a response that came without a usable explanation (no body, an HTML error page
 * from a proxy, or FastAPI's list of validation errors), so nobody reads "Server returned 422".
 */
export function plainStatusMessage(status) {
  switch (status) {
    case 400:
      return 'The server could not read that request. Try again, or try a different file.';
    case 401:
    case 403:
      return 'The server refused this request. Reload the page and try again.';
    case 404:
      return (
        'The server does not have what this page asked for. It may be in the middle of an ' +
        'update. Try again in a minute.'
      );
    case 408:
      return 'The server gave up waiting for the request. Try again.';
    case 413:
      return 'This is too large for the server to accept. Use a smaller file or a shorter document.';
    case 415:
      return 'The server cannot read this kind of file. Upload a PDF, a Word (.docx) file or a text file.';
    case 422:
      return (
        'The server could not use what this page sent. The page and the server may be out of ' +
        'step. Reload the page and try again.'
      );
    case 429:
      return 'The server is getting too many requests. Wait a minute and try again.';
    case 500:
      return 'The server hit an error. Try again in a minute.';
    case 502:
      return 'The server could not be reached through its host. It may be restarting. Try again in a minute.';
    case 503:
      return 'The server is busy or starting up. Try again in a minute.';
    case 504:
      return (
        'The server took too long to answer. Try a shorter document, or split it at a chapter ' +
        'or section boundary.'
      );
    default:
      return status >= 500
        ? `The server hit an error (code ${status}). Try again in a minute.`
        : `The server could not complete this request (code ${status}).`;
  }
}

/** Seconds from a Retry-After header (a number of seconds or a date), or null. */
function parseRetryAfter(value) {
  if (value == null || value === '') return null;
  const seconds = /^\d+$/.test(String(value).trim())
    ? Number(value)
    : (Date.parse(value) - Date.now()) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return Math.min(300, Math.ceil(seconds));
}

async function handleResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new ApiError(
      typeof detail === 'string' && detail.trim() ? detail : plainStatusMessage(response.status),
      {
        status: response.status,
        retryAfter: parseRetryAfter(response.headers?.get?.('Retry-After')),
      }
    );
  }
  try {
    return await response.json();
  } catch (err) {
    // A body that is not JSON (a proxy's page, a half-deployed server) is an answer, just not
    // one this page can use. A body cut off mid-stream is a TypeError and is a network failure.
    if (err instanceof SyntaxError) {
      throw new ApiError(UNEXPECTED_FORMAT_MESSAGE, { status: response.status, badFormat: true });
    }
    throw err;
  }
}

// What a request timing out means depends on what the request was. "The server may be waking
// up" was said for every one of them, including an upload that was simply still going.
function timeoutMessage(phase, seconds) {
  if (phase === 'upload') {
    return (
      `Sending and reading your file took longer than ${seconds} seconds. A large file on a ` +
      'slow connection can do that. Try again on a better connection, or upload a smaller file.'
    );
  }
  if (phase === 'analyze') {
    return (
      `Analyzing this document took longer than ${seconds} seconds. Try a shorter document, ` +
      'or split it at a chapter or section boundary and check the parts one at a time.'
    );
  }
  return (
    `The server did not respond within ${seconds} seconds. It may be waking up from idle. ` +
    'Please try again.'
  );
}

/**
 * fetch with an enforced timeout and error messages that say what went wrong.
 * Every call in this module goes through here.
 *
 * `signal` lets the caller cancel (the person reset the page); `phase` says what the request
 * is, so a timeout can be described accurately.
 */
async function request(
  path,
  { timeoutMs = TIMEOUTS.default, phase = 'request', signal: external, ...options } = {}
) {
  // Nothing to send over and nothing to find out: the phone has no connection. This is its own
  // kind of error (not `offline`), so it is shown at once and never sent to the server probe.
  if (isDeviceOffline()) {
    throw new ApiError(DEVICE_OFFLINE_MESSAGE, { deviceOffline: true });
  }

  // What the page knew about the server when this was sent, and when. If no answer comes back,
  // that is what a restart can honestly be measured against.
  const sentAt = Date.now();
  const bootIdAtSend = seenBootId;
  const bootIdSeenAt = seenAt;

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onExternalAbort = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', onExternalAbort, { once: true });
  }

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      signal: controller.signal,
    });
    // Every answer, a refusal included, says which process gave it.
    noteBootId(response);
    return await handleResponse(response);
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') {
      if (!timedOut) {
        // Cancelled by the caller, not slow. Nothing to explain.
        throw cancelledError();
      }
      throw new ApiError(timeoutMessage(phase, Math.round(timeoutMs / 1000)), { timeout: true });
    }
    // TypeError from fetch means the request never completed: DNS, CORS,
    // TLS, a dropped connection, a killed process, or a gateway error. A browser reports all
    // of them identically, so the caller probes /health to tell them apart.
    throw new ApiError(
      'Could not reach the citation server. It may be starting up or temporarily down.',
      {
        offline: true,
        sent: { at: sentAt, failedAt: Date.now(), bootId: bootIdAtSend, bootIdSeenAt },
      }
    );
  } finally {
    clearTimeout(timer);
    // One signal can outlive many requests; do not leave a listener behind for each.
    external?.removeEventListener('abort', onExternalAbort);
  }
}

function postJson(path, body, options = {}) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...options,
  });
}

// The process id the page last saw, from any response. A different id after a failed request
// means the server restarted in between, which is what an out-of-memory kill looks like from
// outside. The server sends it as a header on every response; /health also carries it, which
// covers a server that does not send the header.
let seenBootId = null;
// When it was last refreshed. An id from ten minutes ago says little about what happened to a
// request sent a moment ago, so a restart is only claimed against a recent one.
let seenAt = 0;

function rememberBootId(id) {
  if (!id) return;
  seenBootId = id;
  seenAt = Date.now();
}

function noteBootId(response) {
  rememberBootId(response?.headers?.get?.('X-Boot-Id'));
}

/** Wake a sleeping backend and learn its limits. Short timeout; failure is not fatal. */
export async function checkHealth(timeoutMs = TIMEOUTS.health) {
  try {
    const health = await request('/health', { timeoutMs });
    rememberBootId(health?.boot_id);
    learnLimits(health);
    return health;
  } catch {
    return null;
  }
}

/** Forget what the page has learned about the server. For tests. */
export function resetServerKnowledge() {
  seenBootId = null;
  seenAt = 0;
  serverLimits = null;
}

/** Wait, but stop at once if `signal` aborts. */
function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(cancelledError());
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(cancelledError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

// What a request that got no answer can be told apart by (see explainNetworkFailure).
// A restart is only said to have happened during this request when the process id had been
// learned just before the request was sent, and the request then ran for a while before it died.
export const FRESH_ID_MS = 5000;
export const LONG_REQUEST_MS = 3000;
// /health reports uptime in whole seconds, and a request can start while the process is still
// coming up; a server older than this when the request was sent was already running.
const UPTIME_SLACK_MS = 2000;

/**
 * Turn "fetch rejected with a TypeError" into advice that fits what happened, by probing /health.
 * Only call this for ApiError.offline: errors the server did answer already carry their own
 * message, and a phone with no connection (ApiError.deviceOffline) needs no probe.
 *
 * - No connection on the phone (the first probe finds that out without sending anything): say so
 *   at once.
 * - It does not answer: it is down or still restarting.
 * - It answers with the same process id as before, or the page never saw one: it is up, and this
 *   request did not complete. Nothing is claimed about a restart without an earlier id to
 *   compare with.
 * - It answers with a DIFFERENT id: it has restarted since the page last heard from it. How much
 *   more than that can be said depends on what the page knows about the request, which the caller
 *   hands over as `sent` (the failed ApiError's `sent`: when it was sent and when it failed, and
 *   the id known at that moment and when it was learned):
 *     - the id was learned within 5 s of the send, and the request ran for at least 3 s before it
 *       died: the server restarted while working on it. This is the only case that blames the
 *       document ("very large, split it").
 *     - the request was refused at once: the server was not running when it was sent, so it
 *       never saw the document.
 *     - anything else (an old id, or no timing at all): only that the server was restarted since
 *       the page last heard from it, and that the document was not changed.
 *   If /health says the process that answers had already been running when the request was sent,
 *   none of the first two can be true, so only the last is said.
 *
 * `signal` stops the probing; the call then rejects with a cancelled error.
 */
export async function explainNetworkFailure(
  what,
  { waitMs = 25000, stepMs = 2500, signal, sent = null } = {}
) {
  // The probe's own response refreshes the id, so what to compare with is taken first.
  const before = sent ? sent.bootId : seenBootId;
  const learnedAt = sent ? sent.bootIdSeenAt : seenAt;
  // A restarting container takes a while to come back, so keep probing for a bit before giving up.
  const deadline = Date.now() + waitMs;
  let health = null;
  for (;;) {
    try {
      health = await request('/health', { timeoutMs: 6000, signal });
      break;
    } catch (err) {
      if (err?.cancelled) throw err;
      if (err?.deviceOffline) return DEVICE_OFFLINE_MESSAGE;
      health = null;
    }
    if (Date.now() + stepMs > deadline) break;
    await pause(stepMs, signal);
  }
  if (!health) {
    if (isDeviceOffline()) return DEVICE_OFFLINE_MESSAGE;
    return `${what}: the server did not answer. It may be down. Wait a minute and try again.`;
  }
  learnLimits(health);
  const answeredAt = Date.now();
  const changed = Boolean(before && health.boot_id && health.boot_id !== before);
  rememberBootId(health.boot_id);

  if (changed) {
    const timed = Boolean(sent) && Number.isFinite(sent.at) && Number.isFinite(sent.failedAt);
    const ranFor = timed ? sent.failedAt - sent.at : null;
    const idAge = timed && learnedAt > 0 ? Math.max(0, sent.at - learnedAt) : Infinity;
    const startedAt = Number.isFinite(health.uptime_s) ? answeredAt - health.uptime_s * 1000 : null;
    const alreadyRunning = timed && startedAt !== null && startedAt < sent.at - UPTIME_SLACK_MS;

    if (!alreadyRunning && timed && idAge <= FRESH_ID_MS && ranFor >= LONG_REQUEST_MS) {
      return (
        `${what}: the server restarted while working on your document. That can happen when the ` +
        'document is very large, or when the server was updated at that moment. Try again; if it ' +
        'happens again with this document, split it.'
      );
    }
    if (!alreadyRunning && timed && ranFor < LONG_REQUEST_MS) {
      return (
        `${what}. The server was not running when this was sent, so it never received your ` +
        'document. It is back now. Try again.'
      );
    }
    return (
      `${what}. The server was restarted (or woke from sleep) since this page last heard from ` +
      'it. Your document was not changed. Try again.'
    );
  }
  return (
    `${what}: the server is running, but this request did not complete. It may have taken ` +
    'too long on a slow connection, or the connection dropped. Try again, and if it keeps ' +
    'happening try a smaller file.'
  );
}

/**
 * Work out WHY a request failed, rather than reporting every failure as an
 * unreachable server. Returns { message, detail, retryAfter, ... } in words for the person who
 * pasted the citation: no mention of origins, CORS or HTTP codes.
 *
 * The frontend and backend deploy independently, so a frontend calling an
 * endpoint that an older backend does not have looks identical to the backend
 * being down. Probing /health separates the two, and /health lists its own
 * routes so a stale backend can be named as such.
 */
export async function diagnose(err, endpoint) {
  // The phone says it has no connection: nothing was sent, and nothing about the server is known.
  // This comes first, before any probe, so it is never blamed on the server.
  if (err?.deviceOffline || isDeviceOffline()) {
    return { message: DEVICE_OFFLINE_MESSAGE, detail: '', offline: true, retryAfter: null };
  }

  if (err?.timeout) {
    return {
      message: err.message,
      detail: 'The backend may be waking from idle. Trying again usually works.',
      retryAfter: null,
    };
  }

  const health = await checkHealth(10000);

  if (!health) {
    if (isDeviceOffline()) {
      return { message: DEVICE_OFFLINE_MESSAGE, detail: '', offline: true, retryAfter: null };
    }
    // A browser reports a blocked cross-origin response and an unreachable host identically, so
    // this can also be a server that is up but does not list this page's address. That is for
    // whoever runs the page, not for the person using it: it goes to the console.
    const origin = typeof window !== 'undefined' ? window.location.origin : 'this page';
    console.error(
      `The citation server did not answer. If it is running, its allowed-origins list may not include ${origin}.`,
      err
    );
    return {
      message: 'The citation server is not answering.',
      detail: 'It may be asleep or starting up. Wait a minute and try again.',
      unreachable: true,
      retryAfter: null,
    };
  }

  if (endpoint && Array.isArray(health.endpoints) && !health.endpoints.includes(endpoint)) {
    return {
      message: 'This page is newer than the server it is talking to.',
      detail:
        `The server is running build ${health.commit || 'unknown'}, which does ` +
        `not have ${endpoint} yet. The backend needs to redeploy.`,
      staleBackend: true,
      retryAfter: null,
    };
  }

  // The server's own "try again in N seconds", for a busy answer.
  const retryAfter = err?.status === 503 && Number.isFinite(err.retryAfter) ? err.retryAfter : null;

  if (err?.offline) {
    // The request got no answer but the server answers now: not "temporarily down".
    return {
      message: 'The request did not go through.',
      detail: 'The server is running, so the connection probably dropped. Try again.',
      retryAfter,
    };
  }
  if (err?.badFormat) {
    return { message: err.message, detail: '', retryAfter };
  }
  return {
    message: err?.message || 'The request failed.',
    detail: 'The server is up, so this is likely a transient error.',
    retryAfter,
  };
}

export async function uploadDocument(file, options = {}) {
  const formData = new FormData();
  formData.append('file', file);
  return request('/api/upload', {
    method: 'POST',
    body: formData,
    timeoutMs: uploadTimeoutMs(file?.size),
    phase: 'upload',
    ...options,
  });
}

function byteLength(string) {
  return typeof TextEncoder !== 'undefined' ? new TextEncoder().encode(string).length : string.length * 3;
}

export function analyzeDocument(documentId, text, filename, options = {}) {
  const body = JSON.stringify({ document_id: documentId, text, filename });
  return request('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    // The request re-sends the whole text, so the time allowed grows with it.
    timeoutMs: analyzeTimeoutMs(byteLength(body)),
    phase: 'analyze',
    ...options,
  });
}

export function formatCitation(citation) {
  return postJson('/api/format', citation);
}

export function lookupCitation(citation, options = {}) {
  return postJson('/api/lookup', citation, options);
}

export function lookupCase(parties, citation) {
  return postJson('/api/lookup/case', { parties, citation });
}

export function completeFromText(text) {
  return postJson('/api/complete-from-text', { text });
}

export function findSources(text, maxSuggestions = 3) {
  return postJson('/api/find-sources', { text, max_suggestions: maxSuggestions });
}

export function analyzeComprehensive(documentId, text, filename, findSources = true) {
  return postJson('/api/analyze-comprehensive', {
    document_id: documentId,
    text,
    filename,
    find_sources: findSources,
  });
}

export function searchCitations(query, searchType = 'case') {
  return postJson('/api/search', { query, search_type: searchType });
}

const isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const nullOrString = (value) => value === null || value === undefined || typeof value === 'string';
const REPAIR_STATUSES = ['resolved', 'ambiguous', 'incomplete', 'unparseable'];

/**
 * Whether `reply` is a /api/repair answer the page can draw. The server always sends every list
 * and every field below; one that is missing or the wrong kind of thing is a different version
 * of the server, or not the server at all (a proxy's JSON page), and would otherwise replace a
 * correct result with an empty card or crash the page while it is drawn. Checked: what is read
 * without a guard, and what is used as a React key or printed.
 */
export function isUsableRepairReply(reply) {
  if (!isPlainObject(reply)) return false;
  if (!REPAIR_STATUSES.includes(reply.status)) return false;
  if (!Array.isArray(reply.missing_details) || !Array.isArray(reply.candidates) || !Array.isArray(reply.notes)) {
    return false;
  }
  const texts = ['formatted', 'template', 'verify_url', 'kind_label', 'citation_type', 'source', 'format_confidence'];
  if (!texts.every((key) => nullOrString(reply[key]))) return false;
  if (!reply.notes.every((note) => typeof note === 'string')) return false;
  const detailOk = (detail) =>
    isPlainObject(detail) &&
    typeof detail.label === 'string' &&
    nullOrString(detail.why) &&
    nullOrString(detail.field) &&
    (detail.display_rule == null ||
      (isPlainObject(detail.display_rule) &&
        typeof detail.display_rule.number === 'string' &&
        typeof detail.display_rule.title === 'string'));
  if (!reply.missing_details.every(detailOk)) return false;
  return reply.candidates.every(
    (candidate) =>
      isPlainObject(candidate) &&
      typeof candidate.verify_url === 'string' &&
      nullOrString(candidate.label) &&
      nullOrString(candidate.court) &&
      nullOrString(candidate.date)
  );
}

/**
 * Repair a single pasted citation. Returns a diagnosis: what was parsed,
 * what is missing, and any verifiable candidates. An answer the page cannot draw is thrown as a
 * badFormat ApiError, so the caller keeps the result it already has and says why.
 *
 * `options.signal` cancels the request (the person cleared the box or asked again).
 */
export async function repairCitation(text, style = 'law_review', options = {}) {
  const reply = await postJson('/api/repair', { text, style }, { timeoutMs: TIMEOUTS.repair, ...options });
  if (!isUsableRepairReply(reply)) {
    throw new ApiError(UNEXPECTED_FORMAT_MESSAGE, { status: 200, badFormat: true });
  }
  return reply;
}

export { ApiError };
