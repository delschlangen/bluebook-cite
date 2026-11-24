// One number format for everything the page prints. The browser's own locale would give
// "20.004" in German and "20 004" in French on one screen next to "2,450" from a notice,
// so every count goes through here.

/** 1234567 -> "1,234,567", whatever the visitor's locale. Anything that is not a number is "0". */
export function fmt(n) {
  const value = Number(n);
  return (Number.isFinite(value) ? value : 0).toLocaleString('en-US');
}
