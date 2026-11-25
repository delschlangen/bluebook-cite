import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { otherCitations, parseCitationWithSpan, partialMessage, repairLocally } from '../localCitation';

const BROWN = 'Brown v. Board of Education, 347 U.S. 483 (1954)';
const MARBURY = 'Marbury v. Madison, 5 U.S. 137 (1803)';
const ZERAN = 'Zeran v. Am. Online, Inc., 129 F.3d 327 (4th Cir. 1997)';
const ROE = 'Roe v. Wade, 410 U.S. 113 (1973)';

describe('a paste with more than one citation says which was formatted and which were not', () => {
  it('names the formatted one and the one left out, for two cases', () => {
    const r = repairLocally(`${BROWN}; ${MARBURY}.`);
    expect(r.status).toBe('resolved');
    expect(r.partial).toEqual({ used: BROWN, others: [MARBURY], more: 0 });
  });

  it('names the one that was used even when it is the second, as the winner is the longest and not the first', () => {
    const r = repairLocally(`47 U.S.C. § 230(c)(1); ${ZERAN}.`);
    expect(r.partial.used).toBe(ZERAN);
    expect(r.partial.others).toEqual(['47 U.S.C. § 230(c)(1)']);
  });

  it('finds a citation on the other side of the one that was used', () => {
    const r = repairLocally(`${MARBURY}; ${BROWN}; ${ROE}.`);
    expect(r.partial.used).toBe(MARBURY);
    expect(r.partial.others).toEqual([BROWN, ROE]);
  });

  it('finds citations on both sides of the one that was used', () => {
    // The statute is the shortest, so it is the one left; the cases around it are the others.
    const r = repairLocally(`${BROWN}; ${ZERAN}; ${ROE}.`);
    expect(r.partial).not.toBeNull();
    const all = [r.partial.used, ...r.partial.others];
    expect(all).toHaveLength(3);
    for (const name of [BROWN, ZERAN, ROE]) expect(all).toContain(name);
  });

  it('names at most three, and counts the rest', () => {
    const five = [BROWN, MARBURY, ROE, ZERAN, 'Miranda v. Arizona, 384 U.S. 436 (1966)'];
    const r = repairLocally(five.join('; ') + '.');
    expect(r.partial.others).toHaveLength(3);
    expect(r.partial.more).toBe(1);
    expect(partialMessage(r.partial)).toContain('and 1 more');
  });

  it('also finds them in a long footnote of five citations, beyond what a single paste usually is', () => {
    const footnote = [BROWN, MARBURY, ROE, ZERAN, '47 U.S.C. § 230(c)(1)'].join(', and see also ');
    const r = repairLocally(footnote);
    expect(r.partial).not.toBeNull();
    expect(1 + r.partial.others.length + r.partial.more).toBe(5);
  });

  it('keeps the status of the citation that was used', () => {
    expect(repairLocally(`${BROWN}; Moody v. NetChoice`).status).toBe('resolved');
    const incomplete = repairLocally(`Moody v. NetChoice, 603 U.S.; ${MARBURY}`);
    expect(incomplete.partial).not.toBeNull();
  });

  it('says it in one sentence that gives the used citation, the others, and what to do', () => {
    const r = repairLocally(`${BROWN}; ${MARBURY}.`);
    expect(partialMessage(r.partial)).toBe(
      `Your paste has more than one citation. Only “${BROWN}” was formatted. ` +
        `Not formatted: “${MARBURY}”. Paste them one at a time, or use Check a document.`
    );
  });

  it('puts several others in one list', () => {
    expect(partialMessage({ used: 'A', others: ['B', 'C'], more: 0 })).toContain('Not formatted: “B”; “C”.');
  });

  it('does not name a signal word as part of a citation', () => {
    const r = repairLocally(`See ${BROWN}; see also ${MARBURY}.`);
    expect(r.partial.used).toBe(BROWN);
    expect(r.partial.others).toEqual([MARBURY]);
  });

  it('finds an other citation that only the data-driven engine reads (a constitutional amendment, a court rule)', () => {
    const r = repairLocally(`${BROWN}; U.S. Const. amend. XIV, § 1`);
    expect(r.partial.used).toBe(BROWN);
    expect(r.partial.others).toEqual(['U.S. Const. amend. XIV, § 1']);
    const rule = repairLocally(`${BROWN}; Fed. R. Civ. P. 12(b)(6)`);
    expect(rule.partial.others).toEqual(['Fed. R. Civ. P. 12(b)(6)']);
  });

  it('counts a citation once when the engine and the older readers both find part of it', () => {
    // The engine reads the whole GAO report; the older reader finds "Smith v. Jones" inside its title.
    const gao = "U.S. GOV'T ACCOUNTABILITY OFF., GAO-16-552, Smith v. Jones (2016)";
    const long = 'Zeran v. America Online Incorporated Holdings Group, 129 F.3d 327, 330-31 (4th Cir. 1997)';
    for (const paste of [`${long}; ${gao}`, `${gao}; ${long}`]) {
      const r = repairLocally(paste);
      expect(r.partial.used).toBe(long);
      expect(r.partial.others).toEqual([gao]);
      expect(r.partial.more).toBe(0);
    }
  });

  it('drops the signal "In" from a name, but keeps "In re", which is part of one', () => {
    const gault = 'In re Gault, 387 U.S. 1 (1967)';
    const keep = otherCitations(`${gault}; ${BROWN}`, { start: 0, end: gault.length });
    expect(keep.used).toBe(gault);
    const text = `In ${BROWN}; ${MARBURY}`;
    const start = text.indexOf('Brown');
    const drop = otherCitations(text, { start: 0, end: start + BROWN.length });
    expect(drop.used).toBe(BROWN);
  });
});

describe('prose around a single citation does not trigger it', () => {
  it.each([
    [`In ${BROWN}, the Court held that separate is not equal.`],
    [`See ${BROWN}.`],
    [`The Court said so in ${BROWN}, and nothing more needs saying.`],
    ['Brown v. Board of Education, 347 U.S. 483, 74 S. Ct. 686, 98 L. Ed. 873 (1954).'],
    ['Smith v. Jones, 123 F.3d 456, 460-61 (9th Cir. 1999) (en banc)'],
    ["Roe v. Wade, 410 U.S. 113 (1973), aff'd, 411 U.S. 1 (1974)"],
    ['U.S. Const. amend. XIV, § 1'],
    ['Restatement (Second) of Torts § 402A (Am. L. Inst. 1965)'],
    ['Moody v. NetChoice'],
    ['47 CFR 54.101'],
    ['GAO-16-552'],
    ['Smith, The Law of Things (2001)'],
    ['  \n  Brown v. Board of Education, 347 U.S. 483 (1954)  \n '],
  ])('%s', (paste) => {
    expect(repairLocally(paste).partial).toBeUndefined();
  });

  it('does not flag any single citation in the golden corpus the browser and the server are both held to', () => {
    const golden = JSON.parse(readFileSync(new URL('../../../../shared/spec_golden.json', import.meta.url), 'utf8'));
    expect(golden.cases.length).toBeGreaterThan(40);
    for (const c of golden.cases) {
      for (const style of ['law_review', 'practitioner']) {
        const r = repairLocally(c.input, style);
        expect(r.partial, `${c.name}: ${c.input}`).toBeUndefined();
      }
    }
  });
});

describe('otherCitations', () => {
  it('is null when nothing citation-shaped lies outside the span', () => {
    const text = `In ${BROWN}, the Court held it.`;
    const start = text.indexOf(BROWN);
    expect(otherCitations(text, { start, end: start + BROWN.length })).toBeNull();
  });

  it('reads the text on each side of the span with the same readers', () => {
    const text = `${MARBURY} and ${BROWN} and ${ROE}`;
    const start = text.indexOf(BROWN);
    const found = otherCitations(text, { start, end: start + BROWN.length });
    expect(found.used).toBe(BROWN);
    expect(found.others).toEqual([MARBURY, ROE]);
  });

  it('counts a citation once even though two readers find it', () => {
    const text = `${BROWN}; 47 U.S.C. § 230(c)(1)`;
    const found = otherCitations(text, { start: 0, end: BROWN.length });
    expect(found.others).toEqual(['47 U.S.C. § 230(c)(1)']);
    expect(found.more).toBe(0);
  });

  it('shortens a very long name', () => {
    const long = `${'Aaaaa '.repeat(7)}v. ${'Bbbbb '.repeat(7)}, 5 U.S. 137 (1803)`;
    const text = `${BROWN}; ${long}`;
    const found = otherCitations(text, { start: 0, end: BROWN.length });
    expect(found.others[0].length).toBeLessThanOrEqual(90);
  });
});

describe('parseCitationWithSpan says where the citation is', () => {
  it('start is an offset into what was passed in, whatever whitespace leads it', () => {
    const input = `  \n ${MARBURY}; ${BROWN}`;
    const read = parseCitationWithSpan(input);
    expect(input.slice(read.start, read.start + read.length)).toBe(MARBURY);
  });

  it('for a statute too', () => {
    const input = 'See 47 U.S.C. § 230';
    const read = parseCitationWithSpan(input);
    expect(input.slice(read.start, read.start + read.length)).toBe('47 U.S.C. § 230');
  });
});
