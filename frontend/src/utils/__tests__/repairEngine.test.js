import { describe, expect, it } from 'vitest';
import { EDITION_NOTE, browseTypes, repairLocally } from '../localCitation';

// The citation a user pasted from an iPhone: curly apostrophe, en dashes, and a title
// that capitalises "With" and "The". Both forms below are the sourced ones (AALL 2025).
const GAO_PASTE =
  'U.S. GOV’T ACCOUNTABILITY OFF., GAO–16–552, Firearms Data: ' +
  'ATF Did Not Always Comply With The Appropriations Act Restrictions (2016)';
const GAO_LAW_REVIEW =
  "U.S. GOV'T ACCOUNTABILITY OFF., GAO-16-552, FIREARMS DATA: ATF DID NOT ALWAYS " +
  'COMPLY WITH THE APPROPRIATIONS ACT RESTRICTIONS (2016).';
const GAO_PRACTITIONER =
  "U.S. Gov't Accountability Off., GAO-16-552, *Firearms Data: ATF Did Not Always " +
  'Comply with the Appropriations Act Restrictions* (2016).';

describe('the GAO report that was rejected as "not a citation"', () => {
  it('is recognised and formatted in law review style', () => {
    const r = repairLocally(GAO_PASTE, 'law_review');
    expect(r.status).toBe('resolved');
    expect(r.kind).toBe('agency_report');
    expect(r.formatted).toBe(GAO_LAW_REVIEW);
    expect(r.needsLookup).toBe(false);
  });

  it('lowercases "with" and "the" in court-document style', () => {
    expect(repairLocally(GAO_PASTE, 'practitioner').formatted).toBe(GAO_PRACTITIONER);
  });

  it('defaults to law review style', () => {
    expect(repairLocally(GAO_PASTE).style).toBe('law_review');
  });

  it('is left unchanged when corrected a second time', () => {
    expect(repairLocally(GAO_PRACTITIONER, 'practitioner').formatted).toBe(GAO_PRACTITIONER);
  });

  it('is not misread as a case or a U.S. Code citation', () => {
    expect(repairLocally(GAO_PASTE).citation_type).toBe('other');
  });
});

describe('what the engine reports', () => {
  it('names the kind and how well established its format is', () => {
    const r = repairLocally('U.S. Const. amend. XIV, § 1');
    expect(r.kind_label).toBe('U.S. Constitution, amendment');
    expect(r.format_confidence).toBe('high');
  });

  it('says so when a format is less established', () => {
    const r = repairLocally('Restatement (Second) of Torts § 402A (Am. L. Inst. 1965)');
    expect(r.format_confidence).toBe('medium');
    expect(r.notes.join(' ')).toMatch(/Confirm it in your Bluebook/);
  });

  it('marks the gaps in the finished shape', () => {
    const r = repairLocally('47 CFR 54.101');
    expect(r.status).toBe('incomplete');
    expect(r.template).toBe('47 C.F.R. § 54.101 ([year]).');
    expect(r.formatted).toBeNull();
  });

  it('shows only verified rule numbers, with the edition caveat available', () => {
    const r = repairLocally('47 CFR 54.101');
    expect(r.missing_details[0].display_rule).toEqual({
      number: '14.2',
      title: 'Rules, Regulations, and Other Publications',
    });
    expect(EDITION_NOTE).toMatch(/21st edition/);
  });

  it('never fabricates a source', () => {
    const r = repairLocally('GAO-16-552');
    expect(r.candidates).toEqual([]);
    expect(r.verify_url).toBeNull();
    expect(r.source).toBeNull();
  });
});

describe('which reader wins', () => {
  it('lets the engine read C.F.R., which the older reader no longer does', () => {
    expect(repairLocally('47 C.F.R. § 54 (2022)').formatted).toBe('47 C.F.R. § 54 (2022).');
  });

  it('still reads a case with the case reader', () => {
    const r = repairLocally('Brandenburg v. Ohio, 395 U.S. 444 (1969)');
    expect(r.kind).toBeNull();
    expect(r.formatted).toBe('*Brandenburg v. Ohio*, 395 U.S. 444 (1969).');
  });

  it('still reads the U.S. Code with the older reader, where no year is required', () => {
    expect(repairLocally('47 USC 230').formatted).toBe('47 U.S.C. § 230.');
  });
});

describe('what it does when it cannot read the paste', () => {
  it('does not guess, and points at the guide', () => {
    const r = repairLocally('hello world');
    expect(r.status).toBe('unparseable');
    expect(r.formatted).toBeNull();
    expect(r.notes[0]).toMatch(/kind of source/);
  });

  it('asks the server, which reads books, articles and websites', () => {
    expect(repairLocally('hello world').needsLookup).toBe(true);
    expect(repairLocally('').needsLookup).toBe(false);
  });
});

describe('the guide to every kind of citation', () => {
  const families = browseTypes('law_review');
  const types = families.flatMap((f) => f.types);

  it('lists every family with at least one type', () => {
    expect(families.length).toBeGreaterThanOrEqual(7);
    families.forEach((f) => expect(f.types.length).toBeGreaterThan(0));
  });

  it('gives every type a finished shape, an example without gaps, and its fields', () => {
    types.forEach((t) => {
      expect(t.template, t.id).toBeTruthy();
      expect(t.example, t.id).toBeTruthy();
      expect(t.example, t.id).not.toContain('[');
      expect(t.fields.length, t.id).toBeGreaterThan(0);
    });
  });

  it('gives every field a verified rule to show', () => {
    types.forEach((t) =>
      t.fields.forEach((f) => expect(f.display_rule, `${t.id}.${f.name}`).not.toBeNull())
    );
  });

  it('marks guidance-only types, which are never used to rewrite a paste', () => {
    const guidance = types.filter((t) => !t.recognises);
    expect(guidance.map((t) => t.id).sort()).toEqual(
      ['hearing', 'record_cite', 'state_statute', 'treaty_bilateral']
    );
    guidance.forEach((t) => expect(t.confidence === 'low' || t.id === 'hearing').toBe(true));
  });

  it('renders the examples in the requested style', () => {
    const practitioner = browseTypes('practitioner').flatMap((f) => f.types);
    const lr = types.find((t) => t.id === 'agency_report').example;
    const pr = practitioner.find((t) => t.id === 'agency_report').example;
    expect(lr).not.toBe(pr);
    expect(lr).toBe(lr.toUpperCase());
  });
});
