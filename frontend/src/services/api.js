const API_URL = import.meta.env.VITE_API_URL || '';

// The backend can be cold-starting on a free tier, so allow a generous but
// bounded window. Without an explicit abort the browser kills the connection
// on its own schedule and surfaces an opaque "Load failed".
const DEFAULT_TIMEOUT_MS = 45000;

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
      body.detail || `Server returned ${response.status}`,
      { status: response.status }
    );
  }
  return response.json();
}

/**
 * fetch with an enforced timeout and error messages that say what went wrong.
 * Every call in this module goes through here.
 */
async function request(path, { timeoutMs = DEFAULT_TIMEOUT_MS, ...options } = {}) {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    throw new ApiError('You appear to be offline. Check your connection and try again.', {
      offline: true,
    });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      signal: controller.signal,
    });
    return await handleResponse(response);
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') {
      throw new ApiError(
        `The server did not respond within ${Math.round(timeoutMs / 1000)} seconds. ` +
          'It may be waking up from idle. Please try again.',
        { timeout: true }
      );
    }
    // TypeError from fetch means the request never completed: DNS, CORS,
    // TLS, or a dropped connection. This is the real "Load failed".
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

/** Wake a sleeping backend. Short timeout; failure is not fatal. */
export async function checkHealth(timeoutMs = 8000) {
  try {
    return await request('/health', { timeoutMs });
  } catch {
    return null;
  }
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

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);
  return request('/api/upload', { method: 'POST', body: formData });
}

export function analyzeDocument(documentId, text, filename) {
  return postJson('/api/analyze', { document_id: documentId, text, filename });
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
export function repairCitation(text) {
  return postJson('/api/repair', { text }, { timeoutMs: 30000 });
}

export { ApiError };
