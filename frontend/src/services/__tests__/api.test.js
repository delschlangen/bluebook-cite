import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  DEFAULT_LIMITS,
  DEVICE_OFFLINE_MESSAGE,
  UNEXPECTED_FORMAT_MESSAGE,
  TIMEOUTS,
  analyzeDocument,
  analyzeTimeoutMs,
  checkHealth,
  explainNetworkFailure,
  formatCitation,
  getLimits,
  plainStatusMessage,
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

const jsonResponse = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

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

  it('a validation error with a list for a detail is put in plain words, not "[object Object]"', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: [{ msg: 'field required' }] }, 422));
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.message).toBe(
      'The server could not use what this page sent. The page and the server may be out of step. ' +
        'Reload the page and try again.'
    );
    expect(err.status).toBe(422);
  });

  it('a response that is not JSON still gets a message in plain words', async () => {
    vi.stubGlobal('fetch', async () => ({ ok: false, status: 502, json: async () => { throw new Error('html'); } }));
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.message).toBe(
      'The server could not be reached through its host. It may be restarting. Try again in a minute.'
    );
  });

  it('a response with no usable detail says, in words, what to do', async () => {
    const expected = {
      400: 'The server could not read that request. Try again, or try a different file.',
      401: 'The server refused this request. Reload the page and try again.',
      403: 'The server refused this request. Reload the page and try again.',
      404: 'The server does not have what this page asked for. It may be in the middle of an update. Try again in a minute.',
      408: 'The server gave up waiting for the request. Try again.',
      413: 'This is too large for the server to accept. Use a smaller file or a shorter document.',
      415: 'The server cannot read this kind of file. Upload a PDF, a Word (.docx) file or a text file.',
      422: 'The server could not use what this page sent. The page and the server may be out of step. Reload the page and try again.',
      429: 'The server is getting too many requests. Wait a minute and try again.',
      500: 'The server hit an error. Try again in a minute.',
      502: 'The server could not be reached through its host. It may be restarting. Try again in a minute.',
      503: 'The server is busy or starting up. Try again in a minute.',
      504: 'The server took too long to answer. Try a shorter document, or split it at a chapter or section boundary.',
      499: 'The server could not complete this request (code 499).',
      599: 'The server hit an error (code 599). Try again in a minute.',
    };
    for (const [status, words] of Object.entries(expected)) {
      for (const body of [{}, { detail: '' }, { detail: '   ' }, { detail: null }, { detail: {} }, { detail: [{ msg: 'x' }] }, null]) {
        vi.stubGlobal('fetch', async () => jsonResponse(body, Number(status)));
        const err = await uploadDocument({ name: 'a.txt', size: 1 }).catch((e) => e);
        expect(err.message, `${status} ${JSON.stringify(body)}`).toBe(words);
        expect(err.message).not.toContain('Server returned');
      }
    }
    expect(plainStatusMessage(504)).toBe(expected[504]);
  });

  it('a string detail is passed on as written, even for a status that has plain words of its own', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'This PDF is encrypted.' }, 400));
    const err = await uploadDocument({ name: 'a.pdf', size: 1 }).catch((e) => e);
    expect(err.message).toBe('This PDF is encrypted.');
  });

  it('a 200 whose body is not JSON is an answer this page cannot use, not a network failure', async () => {
    vi.stubGlobal('fetch', async () => new Response('<html>proxy page</html>', { status: 200 }));
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.badFormat).toBe(true);
    expect(err.offline).toBe(false);
    expect(err.message).toBe(UNEXPECTED_FORMAT_MESSAGE);
  });

  it('a body cut off mid-stream is still a network failure', async () => {
    vi.stubGlobal('fetch', async () => ({ ok: true, status: 200, json: async () => { throw new TypeError('terminated'); } }));
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.offline).toBe(true);
    expect(err.badFormat).toBe(false);
  });

  it('carries how long the server asked to wait, from seconds or from a date', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'busy' }, 503, { 'Retry-After': '30' }));
    expect((await analyzeDocument('d', 't', 'x').catch((e) => e)).retryAfter).toBe(30);

    vi.useFakeTimers({ now: new Date('2030-01-01T00:00:00Z') });
    vi.stubGlobal('fetch', async () =>
      jsonResponse({ detail: 'busy' }, 503, { 'Retry-After': 'Tue, 01 Jan 2030 00:00:45 GMT' })
    );
    expect((await analyzeDocument('d', 't', 'x').catch((e) => e)).retryAfter).toBe(45);
    vi.useRealTimers();

    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'busy' }, 503, { 'Retry-After': 'soon' }));
    expect((await analyzeDocument('d', 't', 'x').catch((e) => e)).retryAfter).toBeNull();
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'busy' }, 503));
    expect((await analyzeDocument('d', 't', 'x').catch((e) => e)).retryAfter).toBeNull();
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'busy' }, 503, { 'Retry-After': '99999' }));
    expect((await analyzeDocument('d', 't', 'x').catch((e) => e)).retryAfter).toBe(300);
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

  it('a different process id means the server restarted, and the message does not blame the document', async () => {
    await seen('boot-A');
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    const message = await explainNetworkFailure('Failed to analyze document', quick);
    expect(message).toBe(
      'Failed to analyze document: the server restarted while working on your document. That can ' +
        'happen when the document is very large, or when the server was updated at that moment. ' +
        'Try again; if it happens again with this document, split it.'
    );
  });

  it('the same process id means the server is up and the request itself did not finish', async () => {
    await seen('boot-A');
    const message = await explainNetworkFailure('The upload failed', quick);
    expect(message).toBe(
      'The upload failed: the server is running, but this request did not complete. It may have ' +
        'taken too long on a slow connection, or the connection dropped. Try again, and if it keeps ' +
        'happening try a smaller file.'
    );
  });

  it('no answer at all means it may be down', async () => {
    await seen('boot-A');
    vi.stubGlobal('fetch', async () => { throw new TypeError('down'); });
    const message = await explainNetworkFailure('The upload failed', quick);
    expect(message).toBe('The upload failed: the server did not answer. It may be down. Wait a minute and try again.');
  });

  it('with no earlier id to compare with, it does not claim a restart, whichever id it sees', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    const message = await explainNetworkFailure('The upload failed', quick);
    expect(message).not.toContain('restarted');
    expect(message).toContain('the server is running, but this request did not complete');
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

describe('the id the page compares with is the one seen just before the request that failed', () => {
  const quick = { waitMs: 0, stepMs: 1 };
  const withHeader = (bootId, body = {}) =>
    jsonResponse(body, 200, bootId ? { 'X-Boot-Id': bootId } : {});

  it('is taken from every response, so a restart long ago is not blamed for a failure now', async () => {
    // The page loaded on boot-A. The server was redeployed (boot-B) while the tab sat idle. A
    // later upload succeeded on boot-B and said so in its header. Then one request dropped.
    vi.stubGlobal('fetch', async () => withHeader('boot-A', { boot_id: 'boot-A' }));
    await checkHealth();
    vi.stubGlobal('fetch', async () => withHeader('boot-B', { document_id: 'd' }));
    await uploadDocument({ name: 'a.txt', size: 1 });

    vi.stubGlobal('fetch', async () => withHeader('boot-B', { boot_id: 'boot-B' }));
    const message = await explainNetworkFailure('Failed to analyze document', quick);
    expect(message).not.toContain('restarted');
    expect(message).toContain('the server is running');
  });

  it('is taken from a refusal too, not only from successes', async () => {
    vi.stubGlobal('fetch', async () => withHeader('boot-A', { boot_id: 'boot-A' }));
    await checkHealth();
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'busy' }, 503, { 'X-Boot-Id': 'boot-B' }));
    await analyzeDocument('d', 't', 'x').catch(() => {});

    vi.stubGlobal('fetch', async () => withHeader('boot-B', { boot_id: 'boot-B' }));
    expect(await explainNetworkFailure('x', quick)).not.toContain('restarted');
  });

  it('still catches a restart that happened after the last response', async () => {
    vi.stubGlobal('fetch', async () => withHeader('boot-A', { document_id: 'd' }));
    await uploadDocument({ name: 'a.txt', size: 1 });
    vi.stubGlobal('fetch', async () => withHeader('boot-B', { boot_id: 'boot-B' }));
    expect(await explainNetworkFailure('x', quick)).toContain('restarted while working on your document');
  });

  it('is refreshed by every successful /health, the latest id winning', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-A' }));
    await checkHealth();
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    await checkHealth();
    // /health now says boot-B, and so does the probe: nothing changed since the last look.
    expect(await explainNetworkFailure('x', quick)).not.toContain('restarted');
    // A server that went back to boot-A is a different process from the last one seen.
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-A' }));
    expect(await explainNetworkFailure('x', quick)).toContain('restarted');
  });

  it('works with a server that sends no header at all, from /health alone', async () => {
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-A' }));
    await checkHealth();
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'boot-B' }));
    expect(await explainNetworkFailure('x', quick)).toContain('restarted');
  });
});

describe('a phone with no connection is told so at once, and the server is not probed', () => {
  const offline = () => vi.stubGlobal('navigator', { onLine: false });

  it('request() marks it deviceOffline, not offline, with its own sentence', async () => {
    offline();
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.deviceOffline).toBe(true);
    expect(err.offline).toBe(false);
    expect(err.message).toBe('You appear to be offline. Check your connection and try again.');
    expect(DEVICE_OFFLINE_MESSAGE).toBe(err.message);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('explainNetworkFailure returns that sentence without a single probe or wait', async () => {
    offline();
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const started = Date.now();
    const message = await explainNetworkFailure('Failed to analyze document');
    expect(message).toBe('You appear to be offline. Check your connection and try again.');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(Date.now() - started).toBeLessThan(500);
  });

  it('and so does a probe that finds the phone has gone offline part-way through', async () => {
    vi.useFakeTimers();
    let online = true;
    vi.stubGlobal('navigator', { get onLine() { return online; } });
    let probes = 0;
    vi.stubGlobal('fetch', async () => {
      probes += 1;
      online = false;
      throw new TypeError('Failed to fetch');
    });
    const outcome = explainNetworkFailure('Failed to analyze document');
    await vi.advanceTimersByTimeAsync(2600);
    expect(await outcome).toBe('You appear to be offline. Check your connection and try again.');
    expect(probes).toBe(1);
  });

  it('and so does the last probe, when the phone went offline during it and there is no time for another', async () => {
    let online = true;
    vi.stubGlobal('navigator', { get onLine() { return online; } });
    vi.stubGlobal('fetch', async () => {
      online = false;
      throw new TypeError('Failed to fetch');
    });
    const message = await explainNetworkFailure('Failed to analyze document', { waitMs: 0, stepMs: 1 });
    expect(message).toBe('You appear to be offline. Check your connection and try again.');
  });

  it('a network failure with the phone online is still marked offline, for the probe', async () => {
    vi.stubGlobal('fetch', async () => { throw new TypeError('Failed to fetch'); });
    const err = await analyzeDocument('d', 't', 'x').catch((e) => e);
    expect(err.offline).toBe(true);
    expect(err.deviceOffline).toBe(false);
  });
});

describe('probing can be cancelled', () => {
  it('rejects as cancelled at once, and sends nothing more', async () => {
    vi.useFakeTimers();
    let probes = 0;
    vi.stubGlobal('fetch', async () => { probes += 1; throw new TypeError('down'); });
    const controller = new AbortController();
    const outcome = explainNetworkFailure('x', { signal: controller.signal }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(100);
    expect(probes).toBe(1);
    controller.abort();
    const err = await outcome;
    expect(err.cancelled).toBe(true);
    await vi.advanceTimersByTimeAsync(30000);
    expect(probes).toBe(1);
  });

  it('cancels a probe that is already waiting on the network, without waiting for it to time out', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', hangingFetch);
    const controller = new AbortController();
    let settled = null;
    explainNetworkFailure('x', { signal: controller.signal }).catch((e) => { settled = e; });
    controller.abort();
    // Only microtasks run: the probe's own 6 s limit has not run out, and it has still stopped.
    await vi.advanceTimersByTimeAsync(0);
    expect(settled?.cancelled).toBe(true);
  });

  it('is cancelled, not "the server did not answer", when the last probe is the one that was running', async () => {
    vi.stubGlobal('fetch', hangingFetch);
    const controller = new AbortController();
    const outcome = explainNetworkFailure('x', { waitMs: 0, stepMs: 1, signal: controller.signal }).catch((e) => e);
    controller.abort();
    const err = await outcome;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.cancelled).toBe(true);
  });

  it('an upload can be cancelled through the signal it is given', async () => {
    vi.stubGlobal('fetch', hangingFetch);
    const controller = new AbortController();
    const outcome = uploadDocument({ name: 'a.pdf', size: 1000 }, { signal: controller.signal }).catch((e) => e);
    controller.abort();
    expect((await outcome).cancelled).toBe(true);
  });
});

describe('request() does not leave a listener on a signal that outlives it', () => {
  it('removes its abort listener when the request finishes', async () => {
    const controller = new AbortController();
    const add = vi.spyOn(controller.signal, 'addEventListener');
    const remove = vi.spyOn(controller.signal, 'removeEventListener');
    vi.stubGlobal('fetch', async () => jsonResponse({ ok: true }));
    for (let i = 0; i < 25; i += 1) {
      await analyzeDocument('d', 't', 'x', { signal: controller.signal });
    }
    expect(add).toHaveBeenCalledTimes(25);
    expect(remove).toHaveBeenCalledTimes(25);
    // The listener that was added is the one that was removed.
    add.mock.calls.forEach((call, i) => expect(remove.mock.calls[i][1]).toBe(call[1]));
  });

  it('also when the request fails', async () => {
    const controller = new AbortController();
    const remove = vi.spyOn(controller.signal, 'removeEventListener');
    vi.stubGlobal('fetch', async () => jsonResponse({ detail: 'no' }, 500));
    await analyzeDocument('d', 't', 'x', { signal: controller.signal }).catch(() => {});
    expect(remove).toHaveBeenCalledTimes(1);
  });
});

describe('the analysis timeout grows with what has to be sent', () => {
  it('is 120 s for a small body', () => {
    expect(analyzeTimeoutMs(0)).toBe(120000);
    expect(analyzeTimeoutMs(1000)).toBe(120000);
    expect(analyzeTimeoutMs(0.5 * MB)).toBe(120000); // 100 s + 12.5 s is still under 120 s
  });

  it('is 100 s plus 25 s per MB of body once that is more than 120 s', () => {
    expect(analyzeTimeoutMs(1 * MB)).toBe(125000);
    expect(analyzeTimeoutMs(1.5 * MB)).toBe(137500);
    expect(analyzeTimeoutMs(4.5 * MB)).toBe(212500);
    expect(analyzeTimeoutMs(6 * MB)).toBe(250000);
  });

  it('uses the encoded size of the request body, which is larger than the text for non-ASCII text', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', hangingFetch);
    // 1.2 million CJK characters are 3.6 MB of UTF-8, though only 1.2 million characters long.
    const text = '\u5B57'.repeat(1_200_000);
    const outcome = analyzeDocument('d', text, 'x.txt').catch((e) => e);
    const bytes = 3_600_000 + 60;
    const expectedMs = 100000 + Math.ceil((bytes / MB) * 25000);
    await vi.advanceTimersByTimeAsync(expectedMs - 2000);
    expect(await Promise.race([outcome, Promise.resolve('still waiting')])).toBe('still waiting');
    await vi.advanceTimersByTimeAsync(4000);
    const err = await outcome;
    expect(err.timeout).toBe(true);
    expect(err.message).toContain(`took longer than ${Math.round(expectedMs / 1000)} seconds`);
  });
});

describe('limits that /health reports are used only if they are usable numbers', () => {
  it('ignores null, negative, zero, NaN, text, and keeps the default for each', async () => {
    const bad = { max_upload_mb: -1, max_pdf_pages: null, max_text_chars: 0, approx_max_words: 'abc', approx_max_pages: NaN };
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'a', limits: bad }));
    await checkHealth();
    expect(getLimits()).toEqual(DEFAULT_LIMITS);
  });

  it('takes the usable ones and leaves the rest', async () => {
    vi.stubGlobal('fetch', async () =>
      jsonResponse({ boot_id: 'a', limits: { max_upload_mb: 25, max_pdf_pages: null, approx_max_words: '100000', unknown_key: 5 } })
    );
    await checkHealth();
    expect(getLimits().max_upload_mb).toBe(25);
    expect(getLimits().max_pdf_pages).toBe(DEFAULT_LIMITS.max_pdf_pages);
    expect(getLimits().approx_max_words).toBe(DEFAULT_LIMITS.approx_max_words);
    expect(getLimits()).not.toHaveProperty('unknown_key');
  });

  it('does not tell listeners about limits that were all unusable', async () => {
    const heard = [];
    const stop = subscribeLimits((limits) => heard.push(limits));
    vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'a', limits: { max_upload_mb: 'big' } }));
    await checkHealth();
    stop();
    expect(heard).toEqual([]);
  });

  it('ignores limits that are an array or a string', async () => {
    for (const limits of [[1, 2], 'lots', 42]) {
      vi.stubGlobal('fetch', async () => jsonResponse({ boot_id: 'a', limits }));
      await checkHealth();
      expect(getLimits()).toEqual(DEFAULT_LIMITS);
    }
  });
});
