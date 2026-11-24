import { describe, expect, it } from 'vitest';
import { fmt } from '../format';

describe('fmt: one number format for the whole page', () => {
  it('groups thousands with commas', () => {
    expect(fmt(0)).toBe('0');
    expect(fmt(999)).toBe('999');
    expect(fmt(1000)).toBe('1,000');
    expect(fmt(20004)).toBe('20,004');
    expect(fmt(1500000)).toBe('1,500,000');
  });

  it('does not take the visitor locale into it', () => {
    const original = Number.prototype.toLocaleString;
    // A German browser calls toLocaleString() with no locale and gets "1.500.000".
    Number.prototype.toLocaleString = function toLocaleString(locale, options) {
      return original.call(this, locale ?? 'de-DE', options);
    };
    try {
      expect(fmt(1500000)).toBe('1,500,000');
    } finally {
      Number.prototype.toLocaleString = original;
    }
  });

  it('shows something sensible for a value that is not a number', () => {
    expect(fmt(undefined)).toBe('0');
    expect(fmt(NaN)).toBe('0');
    expect(fmt('2450')).toBe('2,450');
  });
});
