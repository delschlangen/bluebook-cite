import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import spec from '../citationSpec.json';
import { createEngine } from '../citationEngine';
import { normalizeText } from '../localCitation';
import '../transforms';

/**
 * shared/spec_golden.json is ALSO run by the Python suite against the Python engine.
 * Both engines are held to the same answers on the same real citations, using the
 * spec exported from the one Python source of truth.
 */
const golden = JSON.parse(
  readFileSync(new URL('../../../../shared/spec_golden.json', import.meta.url), 'utf8')
);
const engine = createEngine(spec);

describe('golden citations', () => {
  it.each(golden.cases.map((c) => [c.name, c]))('%s', (_name, c) => {
    const result = engine.diagnose(normalizeText(c.input), c.style || 'law_review');

    if (c.type_id === null) {
      expect(result).toBeNull();
      return;
    }
    expect(result).not.toBeNull();
    expect(result.typeId).toBe(c.type_id);
    expect(result.missing).toEqual(c.missing);
    expect(result.formatted).toBe(c.formatted);
    if ('template' in c) expect(result.template).toBe(c.template);
  });
});

describe('golden documents', () => {
  it.each(golden.document_cases.map((c) => [c.name, c]))('%s', (_name, c) => {
    const text = normalizeText(c.input);
    const found = engine.findAll(text).map((m) => ({
      type_id: m.typeId,
      text: text.slice(m.start, m.end),
    }));
    expect(found).toEqual(c.expected);
  });
});

describe('spec integrity', () => {
  it('has unique ids and a law_review template for every type', () => {
    const ids = spec.types.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    spec.types.forEach((t) => expect(t.templates.law_review).toBeTruthy());
  });

  it('renders every worked example without gaps, in every style', () => {
    spec.types.forEach((t) => {
      Object.keys(t.templates).forEach((style) => {
        const rendered = engine.renderExample(t.id, style);
        expect(rendered, `${t.id}/${style}`).toBeTruthy();
        expect(rendered, `${t.id}/${style}`).not.toContain('[');
      });
    });
  });

  it('reads back every worked example as its own type, complete', () => {
    spec.types
      .filter((t) => t.patterns.length > 0)
      .forEach((t) => {
        const rendered = engine.renderExample(t.id, 'law_review');
        const result = engine.diagnose(rendered, 'law_review');
        expect(result, `${t.id}: ${rendered}`).not.toBeNull();
        expect(result.typeId, `${t.id}: ${rendered}`).toBe(t.id);
        expect(result.missing, `${t.id}: ${rendered}`).toEqual([]);
      });
  });

  it('leaves a corrected citation unchanged when corrected again', () => {
    golden.cases
      .filter((c) => c.formatted)
      .forEach((c) => {
        const style = c.style || 'law_review';
        const again = engine.diagnose(c.formatted, style);
        expect(again, c.name).not.toBeNull();
        expect(again.formatted, c.name).toBe(c.formatted);
      });
  });

  it('resolves every claimed rule to a verified one', () => {
    spec.types.forEach((t) =>
      t.fields.forEach((f) =>
        expect(engine.displayRule(f.rule), `${t.id}.${f.name}: ${f.rule}`).not.toBeNull()
      )
    );
  });

  it('never lets a low-confidence type correct input', () => {
    spec.types
      .filter((t) => t.confidence === 'low')
      .forEach((t) => expect(t.patterns, t.id).toEqual([]));
  });
});

describe('displayRule', () => {
  it('falls back to the nearest verified ancestor, never showing an unverified number', () => {
    expect(engine.displayRule('10.3.2')).toEqual({ number: '10.3', title: 'Reporters and Services' });
    expect(engine.displayRule('12.9.4')).toEqual({ number: '12', title: 'Statutes' });
    // 15.7 was claimed for report numbers by the sources but could not be verified.
    expect(engine.displayRule('15.7')).toEqual({
      number: '15',
      title: 'Books, Reports, and Other Nonperiodic Materials',
    });
  });

  it('keeps a number that is itself verified', () => {
    expect(engine.displayRule('12.3.2').number).toBe('12.3.2');
    expect(engine.displayRule('10.4').number).toBe('10.4');
  });

  it('ignores a parenthetical sub-paragraph letter', () => {
    expect(engine.displayRule('15.1(c)').number).toBe('15.1');
  });

  it('returns nothing for a rule with no verified ancestor', () => {
    expect(engine.displayRule('99.1')).toBeNull();
    expect(engine.displayRule('')).toBeNull();
    expect(engine.displayRule(null)).toBeNull();
  });
});
