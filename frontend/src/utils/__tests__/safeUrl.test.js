import { describe, expect, it } from 'vitest';
import { safeHttpUrl } from '../safeUrl';

describe('safeHttpUrl: only an absolute http or https address becomes a link', () => {
  it('accepts http and https, giving back the address as the browser reads it', () => {
    expect(safeHttpUrl('https://www.courtlistener.com/opinion/105221/brown-v-board/')).toBe(
      'https://www.courtlistener.com/opinion/105221/brown-v-board/'
    );
    expect(safeHttpUrl('http://example.com')).toBe('http://example.com/');
    expect(safeHttpUrl('https://example.com/a b?q=1&r=2#top')).toBe('https://example.com/a%20b?q=1&r=2#top');
  });

  it('accepts a scheme in any letter case', () => {
    expect(safeHttpUrl('HTTPS://Example.com/x')).toBe('https://example.com/x');
    expect(safeHttpUrl('HtTp://example.com/')).toBe('http://example.com/');
  });

  it.each([
    ['javascript:', 'javascript:alert(1)'],
    ['JavaScript: in mixed case', 'JaVaScRiPt:alert(1)'],
    ['javascript: after spaces', '   javascript:alert(1)'],
    ['javascript: after a control character', '\u0001javascript:alert(1)'],
    ['javascript: after several control characters and a space', '\u0000\u001f \u0008javascript:alert(1)'],
    ['javascript: with a tab inside the scheme', 'java\tscript:alert(1)'],
    ['javascript: with a line break inside the scheme', 'java\nscript:alert(1)'],
    ['javascript: with a carriage return inside the scheme', 'jav\rascript:alert(1)'],
    ['data:', 'data:text/html,<script>alert(1)</script>'],
    ['data: in mixed case', 'DaTa:text/html;base64,PHNjcmlwdD4='],
    ['vbscript:', 'vbscript:msgbox(1)'],
    ['VBScript: after whitespace', '\n\t vbscript:msgbox(1)'],
    ['file:', 'file:///etc/passwd'],
    ['ftp:', 'ftp://example.com/file'],
    ['blob:', 'blob:https://example.com/uuid'],
    ['a protocol-relative address', '//example.com/x'],
    ['a relative path', '/opinion/105221/'],
    ['a bare host', 'www.example.com/x'],
    ['an empty string', ''],
    ['only spaces', '   '],
    ['an address with no host', 'https://'],
  ])('rejects %s', (_label, value) => {
    expect(safeHttpUrl(value)).toBeNull();
  });

  it.each([[undefined], [null], [42], [{}], [['https://example.com']], [true]])(
    'rejects something that is not a string: %j',
    (value) => {
      expect(safeHttpUrl(value)).toBeNull();
    }
  );

  it('accepts an https address that is padded with whitespace, and hands back the clean one', () => {
    // The browser strips it too; what is returned is what the link will use.
    expect(safeHttpUrl('  \thttps://example.com/x  ')).toBe('https://example.com/x');
  });

  it('never returns anything that is not http or https', () => {
    const hostile = [
      'javascript:alert(1)', 'JAVASCRIPT:alert(1)', ' javascript:alert(1)', 'java\u0000script:alert(1)',
      ' javascript:alert(1)', 'jAvAsCrIpT\t:alert(1)', 'data:text/plain,hi', 'vbscript:x',
    ];
    for (const value of hostile) {
      const safe = safeHttpUrl(value);
      expect(safe === null || /^https?:\/\//.test(safe), value).toBe(true);
    }
  });
});
