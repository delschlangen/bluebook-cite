import { describe, expect, it } from 'vitest';
import { parseCitation } from '../localCitation';

// The server reads "Id." as its own short form and never as part of a party name. The browser
// keeps a twin of the party pattern, so the rule is asserted here as well; if the two drift,
// the same pasted text would be read differently depending on which one answered.
describe('a standalone Id. is never part of a party name', () => {
  it('does not become the first word of the plaintiff', () => {
    const parsed = parseCitation('Id. Smith v. Jones, 1 U.S. 1 (1990)');
    expect(parsed.parties).toEqual(['Smith', 'Jones']);
  });

  it('does not become the start of the defendant when it follows a case', () => {
    const parsed = parseCitation('Marbury v. Madison. Id. at 177.');
    expect(parsed.parties[0]).toBe('Marbury');
    expect(parsed.parties[1]).not.toMatch(/\bId\b/);
  });

  it.each(['Idaho', 'Ida. Mining', 'Idle Hour', 'IDEC'])(
    'leaves a name that merely begins with Id alone: %s',
    (name) => {
      const parsed = parseCitation(`${name} v. Jones, 1 U.S. 1 (1990)`);
      expect(parsed.parties[0]).toBe(name);
    },
  );
});
