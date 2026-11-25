// Links come from the server: the address of a court record, of a source it found. A server
// that is out of date, misconfigured or fed hostile data could send anything in that field, and
// `href="javascript:..."` runs the script when it is tapped. Only an absolute http or https
// address is ever turned into a link.

/**
 * `value` as the browser will read it, when it is an absolute http or https address; otherwise
 * null. The result is the parsed form (what `new URL` makes of it), not the text that came in,
 * so what was checked is exactly what the link will use. The URL parser is the browser's own:
 * it ignores leading spaces and control characters, tabs and line breaks inside the scheme and
 * letter case, so "  JaVa\tScRiPt:..." is read as javascript: here, as it would be there.
 */
export function safeHttpUrl(value) {
  if (typeof value !== 'string') return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    // Not absolute ("/path", "//host", "www.example.com") or not an address at all.
    return null;
  }
  return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
}
