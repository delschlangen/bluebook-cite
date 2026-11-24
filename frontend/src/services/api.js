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

/** Upload time allowed for a file: 30 s plus 25 s per MB (about 320 kbps), capped at 5 minutes. */
export function uploadTimeoutMs(bytes) {
  const megabytes = Math.ceil((bytes || 0) / (1024 * 1024));
  return Math.min(300000, 30000 + megabytes * 25000);
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

function learnLimits(health) {
  if (!health?.limits || typeof health.limits !== 'object') return;
  serverLimits = health.limits;
  limitListeners.forEach((listener) => listener(getLimits()));
}

class ApiError extends Error {
  constructor(message, { status = 0, timeout = false, offline = false } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.timeout = timeout;
    this.offline = offline;
  }
}

async function handleResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof body.detail === 'string' ? body.detail : `Server returned ${response.status}`,
      { status: response.status }
    );
  }
  return response.json();
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
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    throw new ApiError('You appear to be offline. Check your connection and try again.', {
      offline: true,
    });
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', () => controller.abort(), { once: true });
  }

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      signal: controller.signal,
    });
    return await handleResponse(response);
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') {
      if (!timedOut) {
        // Cancelled by the caller, not slow. Nothing to explain.
        const cancelled = new ApiError('The request was cancelled.');
        cancelled.cancelled = true;
        throw cancelled;
      }
      throw new ApiError(timeoutMessage(phase, Math.round(timeoutMs / 1000)), { timeout: true });
    }
    // TypeError from fetch means the request never completed: DNS, CORS,
    // TLS, a dropped connection, a killed process, or a gateway error. A browser reports all
    // of them identically, so the caller probes /health to tell them apart.
    throw new ApiError(
      'Could not reach the citation server. It may be starting up or temporarily down.',
      { offline: true }
    );
  } finally {
    clearTimeout(timer);
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

// The process id the page last saw. A different id after a failed request means the server
// restarted in between, which is what an out-of-memory kill looks like from outside.
let seenBootId = null;

/** Wake a sleeping backend and learn its limits. Short timeout; failure is not fatal. */
export async function checkHealth(timeoutMs = TIMEOUTS.health) {
  try {
    const health = await request('/health', { timeoutMs });
    if (health?.boot_id && !seenBootId) seenBootId = health.boot_id;
    learnLimits(health);
    return health;
  } catch {
    return null;
  }
}

/** Forget what the page has learned about the server. For tests. */
export function resetServerKnowledge() {
  seenBootId = null;
  serverLimits = null;
}

/**
 * Turn "fetch rejected with a TypeError" into advice that fits what happened, by probing /health.
 * Only call this for ApiError.offline: errors the server did answer already carry their own message.
 *
 * - The server answers with a different process id: it restarted while working on the document,
 *   which is what running out of memory or crashing looks like from outside.
 * - It answers with the same id: it is up, so the request itself did not complete.
 * - It does not answer: it is down or still restarting.
 */
export async function explainNetworkFailure(what, { waitMs = 25000, stepMs = 2500 } = {}) {
  const before = seenBootId;
  // A restarting container takes a while to come back, so keep probing for a bit before giving up.
  const deadline = Date.now() + waitMs;
  let health = null;
  for (;;) {
    try {
      health = await request('/health', { timeoutMs: 6000 });
      break;
    } catch {
      health = null;
    }
    if (Date.now() + stepMs > deadline) break;
    await new Promise((resolve) => setTimeout(resolve, stepMs));
  }
  if (!health) {
    return `${what}: the server did not answer. It may be down. Wait a minute and try again.`;
  }
  learnLimits(health);
  const restarted = before && health.boot_id && health.boot_id !== before;
  if (health.boot_id) seenBootId = health.boot_id;
  if (restarted) {
    return (
      `${what}: the server restarted while working on your document, which usually means the ` +
      'document was too large or complex for it. Try a shorter document, or split it.'
    );
  }
  return (
    `${what}: the server is running, but this request did not complete. It may have taken ` +
    'too long on a slow connection or hit an error on this document. Try again, or try a smaller file.'
  );
}

/**
 * Work out WHY a request failed, rather than reporting every failure as an
 * unreachable server.
 *
 * The frontend and backend deploy independently, so a frontend calling an
 * endpoint that an older backend does not have looks identical to the backend
 * being down. Probing /health separates the two, and /health lists its own
 * routes so a stale backend can be named as such.
 */
export async function diagnose(err, endpoint) {
  if (err?.timeout) {
    return {
      message: err.message,
      detail: 'The backend may be waking from idle. Trying again usually works.',
    };
  }

  const health = await checkHealth(10000);

  if (!health) {
    // A browser reports a blocked cross-origin response and an unreachable
    // host identically: both reject with a TypeError and no detail. The health
    // probe fails the same way, so it cannot separate them either. Name both
    // rather than asserting an outage that may not be happening.
    return {
      message: 'No response from the citation server.',
      detail:
        `Either it is asleep or down, or it is running but not accepting ` +
        `requests from ${window.location.origin}. Its allowed-origins list ` +
        `has to contain that exact value.`,
      unreachable: true,
    };
  }

  if (endpoint && Array.isArray(health.endpoints) && !health.endpoints.includes(endpoint)) {
    return {
      message: 'This page is newer than the server it is talking to.',
      detail:
        `The server is running build ${health.commit || 'unknown'}, which does ` +
        `not have ${endpoint} yet. The backend needs to redeploy.`,
      staleBackend: true,
    };
  }

  return {
    message: err?.message || 'The request failed.',
    detail: 'The server is up, so this is likely a transient error.',
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

export function analyzeDocument(documentId, text, filename, options = {}) {
  return postJson('/api/analyze', { document_id: documentId, text, filename }, {
    timeoutMs: TIMEOUTS.analyze,
    phase: 'analyze',
    ...options,
  });
}

export function formatCitation(citation) {
  return postJson('/api/format', citation);
}

export function lookupCitation(citation) {
  return postJson('/api/lookup', citation);
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

/**
 * Repair a single pasted citation. Returns a diagnosis: what was parsed,
 * what is missing, and any verifiable candidates.
 */
export function repairCitation(text, style = 'law_review') {
  return postJson('/api/repair', { text, style }, { timeoutMs: TIMEOUTS.repair });
}

export { ApiError };
