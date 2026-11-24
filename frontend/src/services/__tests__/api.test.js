import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  DEFAULT_LIMITS,
  TIMEOUTS,
  analyzeDocument,
  checkHealth,
  explainNetworkFailure,
  formatCitation,
  getLimits,
  repairCitation,
  resetServerKnowledge,
  subscribeLimits,
  uploadDocument,
  uploadTimeoutMs,
} from '../api';

const MB = 1024 * 1024;

/**
 * A fetch that never answers, and rejects the way a real one does when it is aborted: at once if
 * the signal is already aborted, otherwise when it aborts.
 */
const hangingFetch = (_url, { signal }) =>
  new Promise((_resolve, reject) => {
    const abort = () =>
      reject(Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' }));
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort);
  });

const jsonResponse = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

beforeEach(() => resetServerKnowledge());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('uploadTimeoutMs: a big file on a slow phone is given time', () => {
  it('is 30 s plus 25 s per MB', () => {
    expect(uploadTimeoutMs(0)).toBe(30000);
    expect(uploadTimeoutMs(1)).toBe(55000);
    expect(uploadTimeoutMs(MB)).toBe(55000);
    expect(uploadTimeoutMs(MB + 1)).toBe(80000);
    expect(uploadTimeoutMs(10 * MB)).toBe(280000);
  });

  it('is capped at five minutes', () => {
    expect(uploadTimeoutMs(11 * MB)).toBe(300000);
    expect(uploadTimeoutMs(500 * MB)).toBe(300000);
  });

  it('allows far more than the 45 s that used to cut working uploads off', () => {
    expect(uploadTimeoutMs(4 * MB)).toBeGreaterThan(45000 * 2);
  });
});

describe('each kind of request has its own timeout and says what timed out', () => {
  async function timeoutOf(start, ms) {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', hangingFetch);
    const outcome = start().then(
      () => 'resolved',
      (err) => err
    );
    await vi.advanceTimersByTimeAsync(ms - 1);
    expect(await Promise.race([outcome, Promise.resolve('still waiting')])).toBe('still waiting');
    await vi.advanceTimersByTimeAsync(1);
    return outcome;
  }

  it('analysis: 120 s, and the message is about the document, not about waking up', async () => {
    const err = await timeoutOf(() => analyzeDocument('d', 'text', 'x.txt'), TIMEOUTS.analyze);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.timeout).toBe(true);
    expect(err.message).toContain('Analyzing this document took longer than 120 seconds');
    expect(err.message).toContain('split it');
    expect(err.message).not.toContain('waking up');
  });

  it('upload: scaled to the file, and the message is about the file and the connection', async () => {
    const file = { name: 'big.pdf', size: 5 * MB };
    const err = await timeoutOf(() => uploadDocument(file), uploadTimeoutMs(file.size));
    expect(err.timeout).toBe(true);
    expect(err.message).toContain('Sending and reading your file took longer than 155 seconds');
    expect(err.message).toContain('slow connection');
    expect(err.message).not.toContain('waking up');
  });

  it('a single citation: 30 s', async () => {
    const err = await timeoutOf(() => repairCitation('Moody v. NetChoice'), TIMEOUTS.repair);
    expect(err.message).toContain('30 seconds');
  });

  it('anything else keeps the default and the "waking up" explanation, which fits it', async () => {
    const err = await timeoutOf(() => formatCitation({}), TIMEOUTS.default);
    expect(err.message).toContain('45 seconds');
    expect(err.message).toContain('waking up');
  });
});

describe('cancelling is not a failure', () => {
  it('a request the caller cancelled is marked cancelled, not timed out', async () => {
    vi.stubGlobal('fetch', hangingFetch);
    const controller = new AbortController();
    const outcome = analyzeDocument('d', 't', 'x.txt', { signal: controller.signal }).catch((e) => e);
    controller.abort();
    const err = await outcome;
    expect(err.cancelled).toBe(true);
    expect(err.timeout).toBe(false);
  });

  it('a signal that is already aborted cancels at once', async () => {
    vi.stubGlobal('fetch', hangingFetch);
    const controller = new AbortController();
    controller.abort();
    const err = await analyzeDocument('d', 't', 'x.txt', { signal: controller.signal }).catch((e) => e);
    expect(err.cancelled).toBe(true);
  });
});

describe('what the server said is passed on as it said it', () => {
  it('a refusal carries its own explanation and status', async () => {
    const detail = 'This PDF has 500 pages, which is over the 400-page limit. Split it into parts.';
    vi.stubGlobal('fetch', async () => jsonResponse({ detail }, 413));
    const err = await uploadDocument({ name: 'a.pdf', size: 1000 }).catch((e) => e);
    expect(err.message).toBe(detail);
    expect(err.status).toBe(413);
    expect(err.offline).toBe(false);
  });

  it('a validation error with a list for a detail does not become "[object Object]"', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: [{ msg: 'field required' }] }, 422));
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.message).toBe('Server returned 422');
  });

  it('a response that is not JSON still gets a message', async () => {
    vi.stubGlobal('fetch', async () => ({ ok: false, status: 502, json: async () => { throw new Error('html'); } }));
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.message).toBe('Server returned 502');
  });

  it('no response at all is marked offline, so the page knows to find out why', async () => {
    vi.stubGlobal('fetch', async () => { throw new TypeError('Failed to fetch'); });
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.offline).toBe(true);
    expect(err.timeout).toBe(false);
  });
});

describe('limits: the page shows the numbers the server enforces', () => {
  it('starts with the defaults', () => {
    expect(getLimits()).toEqual(DEFAULT_LIMITS);
  });

  it('adopts what /health says and tells anyone listening', async () => {
    const heard = [];
    const stop = subscribeLimits((limits) => heard.push(limits));
    vi.stubGlobal('fetch', async () =>
      jsonResponse({ status: 'healthy', boot_id: 'aaa', limits: { max_upload_mb: 25, max_pdf_pages: 150 } })
    );

    await checkHealth();

    expect(getLimits().max_upload_mb).toBe(25);
    expect(getLimits().max_pdf_pages).toBe(150);
    expect(getLimits().max_text_chars).toBe(DEFAULT_LIMITS.max_text_chars); // not sent: default kept
    expect(heard).toHaveLength(1);
    stop();
  });

  it('stops telling a listener that unsubscribed', async () => {
    const heard = [];
    const stop = subscribeLimits((limits) => heard.push(limits));
    stop();
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'a', limits: { max_upload_mb: 3 } }));
    await checkHealth();
    expect(heard).toEqual([]);
  });

  it('keeps the defaults when an older server sends no limits', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ status: 'healthy' }));
    await checkHealth();
    expect(getLimits()).toEqual(DEFAULT_LIMITS);
  });

  it('a failed health check changes nothing and does not throw', async () => {
    vi.stubGlobal('fetch', async () => { throw new TypeError('down'); });
    await expect(checkHealth()).resolves.toBeNull();
    expect(getLimits()).toEqual(DEFAULT_LIMITS);
  });
});

describe('explainNetworkFailure: a crash, a dropped request and an outage are not the same', () => {
  const quick = { waitMs: 0, stepMs: 1 };

  async function seen(bootId) {
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: bootId }));
    await checkHealth();
  }

  it('a different process id means the server restarted while working on the document', async () => {
    await seen('boot-A');
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    const message = await explainNetworkFailure('Failed to analyze document', quick);
    expect(message).toContain('Failed to analyze document');
    expect(message).toContain('restarted while working on your document');
    expect(message).toContain('too large');
  });

  it('the same process id means the server is up and the request itself did not finish', async () => {
    await seen('boot-A');
    const message = await explainNetworkFailure('The upload failed', quick);
    expect(message).toContain('the server is running');
    expect(message).not.toContain('restarted');
  });

  it('no answer at all means it may be down', async () => {
    await seen('boot-A');
    vi.stubGlobal('fetch', async () => { throw new TypeError('down'); });
    const message = await explainNetworkFailure('The upload failed', quick);
    expect(message).toContain('did not answer');
    expect(message).toContain('may be down');
  });

  it('cannot claim a restart if it never saw the server before', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    const message = await explainNetworkFailure('The upload failed', quick);
    expect(message).not.toContain('restarted');
  });

  it('remembers the new id, so a second failure on the restarted server is not blamed on a restart', async () => {
    await seen('boot-A');
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    expect(await explainNetworkFailure('x', quick)).toContain('restarted');
    expect(await explainNetworkFailure('x', quick)).not.toContain('restarted');
  });

  it('keeps asking for a while, because a restarting server takes time to come back', async () => {
    await seen('boot-A');
    let calls = 0;
    vi.stubGlobal('fetch', async () => {
      calls += 1;
      if (calls < 3) throw new TypeError('still starting');
      return jsonResponse({ boot_id: 'boot-B' });
    });
    const message = await explainNetworkFailure('Failed', { waitMs: 500, stepMs: 5 });
    expect(calls).toBe(3);
    expect(message).toContain('restarted');
  });
});
