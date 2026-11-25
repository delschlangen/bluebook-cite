import { describe, expect, it } from 'vitest';
import { ApiError } from '../../services/api';
import { describeFailure } from '../failures';

const failure = (message, props = {}) => Object.assign(new ApiError(message), props);

describe('describeFailure: what to say, and whether sending it again can help', () => {
  it('puts what was being done in front of what the server said', () => {
    const out = describeFailure(failure('The PDF is encrypted.', { status: 400 }), { prefix: 'Failed to analyze document' });
    expect(out.message).toBe('Failed to analyze document: The PDF is encrypted.');
    expect(out.canRetry).toBe(true);
    expect(out.hint).toBeNull();
  });

  it('gives a phone with no connection its own sentence, without the prefix', () => {
    const out = describeFailure(
      failure('You appear to be offline. Check your connection and try again.', { deviceOffline: true }),
      { prefix: 'Failed to analyze document' }
    );
    expect(out.message).toBe('You appear to be offline. Check your connection and try again.');
    expect(out.canRetry).toBe(true);
  });

  it('a 413 cannot be retried, and says what to change instead', () => {
    const out = describeFailure(failure('This is too large for the server to accept.', { status: 413 }), {
      prefix: 'Failed to analyze document',
    });
    expect(out.canRetry).toBe(false);
    expect(out.hint).toBe(
      'Sending it again would be refused the same way. Use a shorter document, or split it at a ' +
        'chapter or section boundary and check the parts one at a time.'
    );
  });

  it('does not repeat advice the server already gave with a 413', () => {
    const out = describeFailure(failure('This document is 1,700,000 characters. Split it into parts.', { status: 413 }));
    expect(out.canRetry).toBe(false);
    expect(out.hint).toBeNull();
  });

  it('a 504 cannot be retried and says to try a shorter document', () => {
    const out = describeFailure(failure('The server took longer than 90 seconds.', { status: 504 }));
    expect(out.canRetry).toBe(false);
    expect(out.hint).toBe(
      'Try a shorter document, or split it at a chapter or section boundary and check the parts one at a time.'
    );
  });

  it('does not repeat "shorter document" when the 504 text already says it', () => {
    const out = describeFailure(failure('Analyzing took too long. Try a shorter document, or split it.', { status: 504 }));
    expect(out.hint).toBeNull();
  });

  it.each([
    [422, 'The server could not use what this page sent. The page and the server may be out of step. Reload the page and try again.'],
    [401, 'The server refused this request. Reload the page and try again.'],
    [403, 'The server refused this request. Reload the page and try again.'],
  ])('a %i cannot be retried: the page has to be loaded again, and the document chosen again', (status, text) => {
    const out = describeFailure(failure(text, { status }), { prefix: 'Failed to analyze document' });
    expect(out.canRetry).toBe(false);
    expect(out.reload).toBe(true);
    expect(out.retryAfter).toBeNull();
    expect(out.message).toBe(`Failed to analyze document: ${text}`);
    expect(out.hint).toBe('Reloading the page clears the document that is loaded, so you will need to choose it again.');
    // "Upload New Document" would send the same kind of request to the same server.
    expect(out.hint).not.toMatch(/Upload New Document/);
  });

  it('a 415 cannot be retried either, but reloading would not help: a different file would', () => {
    const out = describeFailure(failure('The server cannot read this kind of file.', { status: 415 }));
    expect(out.canRetry).toBe(false);
    expect(out.reload).toBe(false);
  });

  it('a 400 is left as it was: it can be retried, and says to try a different file', () => {
    const out = describeFailure(failure('The server could not read that request. Try again, or try a different file.', { status: 400 }));
    expect(out.canRetry).toBe(true);
    expect(out.reload).toBe(false);
  });

  it('nothing else asks for a reload', () => {
    for (const status of [0, 400, 404, 408, 413, 429, 500, 502, 503, 504]) {
      expect(describeFailure(failure('x', { status })).reload, String(status)).toBe(false);
    }
  });

  it('a 503 can be retried, after the wait the server asked for', () => {
    const out = describeFailure(failure('busy', { status: 503, retryAfter: 30 }));
    expect(out.canRetry).toBe(true);
    expect(out.retryAfter).toBe(30);
  });

  it('a 503 that asked for no wait, or an unusable one, has no wait', () => {
    expect(describeFailure(failure('busy', { status: 503 })).retryAfter).toBeNull();
    expect(describeFailure(failure('busy', { status: 503, retryAfter: NaN })).retryAfter).toBeNull();
  });

  it('a wait on any other status is not used', () => {
    expect(describeFailure(failure('boom', { status: 500, retryAfter: 30 })).retryAfter).toBeNull();
  });

  it('copes with an error that has no message', () => {
    expect(describeFailure({}).message).toBe('The request failed.');
    expect(describeFailure(undefined).canRetry).toBe(true);
  });
});
