// One number format for everything the page prints. The browser's own locale would give
// "20.004" in German and "20 004" in French on one screen next to "2,450" from a notice,
// so every count goes through here.

/** 1234567 -> "1,234,567", whatever the visitor's locale. Anything that is not a number is "0". */
export function fmt(n) {
  const value = Number(n);
  return (Number.isFinite(value) ? value : 0).toLocaleString('en-US');
}

/**
 * How many characters the server will count in `text`: Unicode code points, as Python counts a
 * string, not the UTF-16 units `text.length` counts (an emoji is 2 of those and 1 of these).
 */
export function countCharacters(text) {
  const value = text || '';
  let count = 0;
  // eslint-disable-next-line no-unused-vars
  for (const _ of value) count += 1;
  return count;
}
