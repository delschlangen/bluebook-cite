import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { TRANSFORMS, createEngine, registerTransform } from '../citationEngine';

/**
 * The cases below live in shared/engine_conformance.json and are ALSO run by the
 * Python test suite against the Python engine. The two engines are held to the
 * same answers, so neither can drift without a test failing.
 */
const corpus = JSON.parse(
  readFileSync(new URL('../../../../shared/engine_conformance.json', import.meta.url), 'utf8')
);
const engine = createEngine(corpus.spec);

describe('conformance: single pasted citations', () => {
  it.each(corpus.match_cases.map((c) => [c.name, c]))('%s', (_name, c) => {
    const result = engine.diagnose(c.input, c.style);

    if (c.type_id === null) {
      expect(result).toBeNull();
      return;
    }
    expect(result).not.toBeNull();
    expect(result.typeId).toBe(c.type_id);
    expect(result.missing).toEqual(c.missing);
    expect(result.formatted).toBe(c.formatted);
    expect(result.template).toBe(c.template);
  });
});

describe('conformance: every citation in a document', () => {
  it.each(corpus.find_all_cases.map((c) => [c.name, c]))('%s', (_name, c) => {
    const found = engine.findAll(c.input).map((m) => ({
      type_id: m.typeId,
      text: c.input.slice(m.start, m.end),
    }));
    expect(found).toEqual(c.expected);
  });
});

describe('the guarantee that matters', () => {
  it('never formats a citation with a required field missing', () => {
    const result = engine.diagnose('GAO-16-552');
    expect(result.formatted).toBeNull();
    expect(result.missing).toEqual(['author', 'title', 'year']);
  });

  it('shows gaps only when asked', () => {
    const match = engine.bestMatch('GAO-16-552');
    expect(engine.render(match.typeId, match.fields)).toBeNull();
    expect(engine.render(match.typeId, match.fields, 'law_review', true)).toContain('[author]');
  });

  it('gives every missing field its rule and explanation', () => {
    const result = engine.diagnose('GAO-16-552');
    expect(result.details.map((d) => d.rule)).toEqual(['R1', 'R3', 'R4']);
    result.details.forEach((d) => {
      expect(d.why).toBeTruthy();
      expect(d.label).toBeTruthy();
    });
  });
});

describe('engine mechanics', () => {
  const single = (templates, patterns, fields) =>
    createEngine({ types: [{ id: 't', label: 't', patterns, fields, templates }] });

  afterEach(() => {
    delete TRANSFORMS.add_x;
  });

  it('applies transforms left to right, using two that do not commute', () => {
    registerTransform('add_x', (v) => `${v}x`);
    const e = single(
      { law_review: '{a|add_x|upper} / {a|upper|add_x}' },
      [{ regex: '(?P<a>[a-z]+)' }],
      [{ name: 'a', label: 'a', required: true }]
    );
    const match = e.bestMatch('word');
    expect(e.render('t', match.fields)).toBe('WORDX / WORDx');
  });

  it('needs every field inside an optional block for it to appear', () => {
    const e = single(
      { law_review: '{a}<< pair {b} and {c}>>.' },
      [{ regex: '(?P<a>A\\d)(?:-(?P<b>B\\d))?(?:-(?P<c>C\\d))?' }],
      [{ name: 'a', label: 'a', required: true }]
    );
    expect(e.render('t', e.bestMatch('A1-B2-C3').fields)).toBe('A1 pair B2 and C3.');
    expect(e.render('t', e.bestMatch('A1-B2').fields)).toBe('A1.');
  });

  it('breaks a tie by priority', () => {
    const e = createEngine({
      types: [
        { id: 'low', label: 'low', priority: 1, patterns: [{ regex: '(?P<a>ABC)' }],
          fields: [{ name: 'a', label: 'a', required: true }], templates: { law_review: '{a}' } },
        { id: 'high', label: 'high', priority: 9, patterns: [{ regex: '(?P<a>ABC)' }],
          fields: [{ name: 'a', label: 'a', required: true }], templates: { law_review: '{a}' } },
      ],
    });
    expect(e.bestMatch('ABC').typeId).toBe('high');
  });

  it('rejects a pattern that covers little of the input', () => {
    expect(engine.bestMatch(`${'x'.repeat(80)} GAO-16-552 ${'y'.repeat(80)}`)).toBeNull();
  });

  it('knows the same transforms as the Python engine', () => {
    expect(Object.keys(TRANSFORMS)).toEqual(
      expect.arrayContaining(['italic', 'roman', 'smallcaps', 'upper'])
    );
  });
});
