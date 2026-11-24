/**
 * Data-driven citation engine. A line-for-line twin of backend/app/services/spec_engine.py.
 *
 * Both read the same spec (generated from the Python source of truth) and are held to
 * the same answers by shared/engine_conformance.json, which both test suites run.
 * If you change behaviour here, change it there, and the conformance corpus will
 * tell you if the two have drifted.
 *
 * Template syntax
 *   {name}              the field, or "[label]" when missing and gaps are shown
 *   {name|a|b}          the field passed through transforms a then b
 *   <<text {name}>>     optional block, emitted only if every field inside is present
 */

const PLACEHOLDER = /\{(\w+)((?:\|\w+)*)\}/g;
const OPTIONAL = /<<([\s\S]*?)>>/g;

export const MIN_COVERAGE = 0.55;

export const TRANSFORMS = {
  upper: (value) => value.toUpperCase(),
  // Plain text has no small capitals. Law review style sets authors and titles of
  // books in large and small caps, rendered here as capitals; a practitioner
  // document uses ordinary type.
  smallcaps: (value, style) => (style === 'law_review' ? value.toUpperCase() : value),
  italic: (value) => (value ? `*${value}*` : value),
  roman: (value) => value.toUpperCase(),
};

export function registerTransform(name, fn) {
  TRANSFORMS[name] = fn;
}

class Drop extends Error {}

function clean(value) {
  return value.replace(/\s+/g, ' ').replace(/^[ \t\n,;]+|[ \t\n,;]+$/g, '');
}

function tidy(text) {
  return text
    .replace(/\s+([,.;:)])/g, '$1')
    .replace(/\(\s+/g, '(')
    .replace(/\s{2,}/g, ' ')
    .replace(/,\s*,/g, ',')
    .trim();
}

// Python spells a named group (?P<name>...). JavaScript spells it (?<name>...).
function toJsRegex(source, flags, global) {
  let f = global ? 'g' : '';
  if ((flags || '').includes('i')) f += 'i';
  return new RegExp(source.replace(/\(\?P</g, '(?<'), f);
}

function rank(m) {
  // Match length, not a rounded ratio, so ties break exactly as they do in Python.
  return [m.end - m.start, Object.keys(m.fields).length, m.priority, -m.patternIndex];
}

function compareRank(a, b) {
  const ra = rank(a);
  const rb = rank(b);
  for (let i = 0; i < ra.length; i += 1) {
    if (ra[i] !== rb[i]) return ra[i] - rb[i];
  }
  return 0;
}

export function createEngine(spec) {
  const types = new Map();
  spec.types.forEach((entry) => {
    types.set(entry.id, {
      spec: entry,
      patterns: (entry.patterns || []).map((p) => ({
        source: p.regex,
        flags: p.flags || '',
        // A paste-only pattern is anchored to the start of the input or loose
        // enough to be a false positive in prose, so it is never used to scan a
        // whole document.
        pasteOnly: Boolean(p.paste_only),
      })),
    });
  });

  const typeSpec = (id) => types.get(id).spec;
  const fieldSpecs = (id) => typeSpec(id).fields;
  const requiredFields = (id) => fieldSpecs(id).filter((f) => f.required).map((f) => f.name);

  function* scan(compiled, rawText, document = false) {
    // Italics are written with asterisks, in this tool's own output and in many
    // pasted drafts. They are not part of a title, and left in they get read back into
    // it and doubled: correcting a corrected citation would corrupt it. One space for
    // one asterisk keeps every offset valid.
    const text = rawText.replace(/\*/g, ' ');
    for (let index = 0; index < compiled.patterns.length; index += 1) {
      const p = compiled.patterns[index];
      if (document && p.pasteOnly) continue;
      const re = toJsRegex(p.source, p.flags, true);
      for (const m of text.matchAll(re)) {
        const fields = {};
        Object.entries(m.groups || {}).forEach(([name, value]) => {
          if (value !== undefined) {
            const cleaned = clean(value);
            if (cleaned) fields[name] = cleaned;
          }
        });
        yield {
          typeId: compiled.spec.id,
          start: m.index,
          end: m.index + m[0].length,
          fields,
          patternIndex: index,
          priority: compiled.spec.priority || 0,
          coverage: 0,
        };
      }
    }
  }

  function findAll(text) {
    const candidates = [];
    types.forEach((compiled) => {
      for (const cand of scan(compiled, text, true)) candidates.push(cand);
    });

    // Longest first, then higher priority, then earlier (more specific) pattern.
    candidates.sort(
      (a, b) =>
        (b.end - b.start) - (a.end - a.start) ||
        b.priority - a.priority ||
        a.patternIndex - b.patternIndex ||
        a.start - b.start
    );

    const chosen = [];
    candidates.forEach((cand) => {
      const overlaps = chosen.some((c) => !(cand.end <= c.start || cand.start >= c.end));
      if (!overlaps) chosen.push(cand);
    });
    chosen.sort((a, b) => a.start - b.start);
    return chosen;
  }

  function bestMatch(text) {
    const stripped = (text || '').trim();
    if (!stripped) return null;
    let best = null;
    types.forEach((compiled) => {
      for (const cand of scan(compiled, stripped)) {
        cand.coverage = (cand.end - cand.start) / Math.max(stripped.length, 1);
        if (best === null || compareRank(cand, best) > 0) best = cand;
      }
    });
    if (best === null || best.coverage < MIN_COVERAGE) return null;
    return best;
  }

  const missing = (id, fields) => requiredFields(id).filter((n) => !fields[n]);

  // The nearest VERIFIED rule at or above `number`, from the spec's own table.
  // "10.3.2" is shown as "10.3" unless 10.3.2 itself is verified. Nothing is
  // returned when no ancestor is verified, so an unverified number is never shown.
  function displayRule(number) {
    const rules = spec.rules || {};
    if (!number) return null;
    const parts = number.split('(')[0].trim().split('.');
    for (let end = parts.length; end > 0; end -= 1) {
      const candidate = parts.slice(0, end).join('.');
      if (Object.prototype.hasOwnProperty.call(rules, candidate)) {
        return { number: candidate, title: rules[candidate] };
      }
    }
    return null;
  }

  function render(id, fields, style = 'law_review', gaps = false) {
    const spec1 = typeSpec(id);
    const template = spec1.templates[style] || spec1.templates.law_review;
    const labels = {};
    spec1.fields.forEach((f) => {
      labels[f.name] = f.label;
    });
    const required = new Set(requiredFields(id));

    if (!gaps && [...required].some((n) => !fields[n])) return null;

    function fill(segment, inOptional) {
      try {
        return segment.replace(PLACEHOLDER, (m, name, chain) => {
          let value = fields[name] || '';
          if (!value) {
            if (inOptional) throw new Drop();
            return required.has(name) || gaps ? `[${labels[name] || name}]` : '';
          }
          chain
            .split('|')
            .filter(Boolean)
            .forEach((t) => {
              value = TRANSFORMS[t](value, style);
            });
          return value;
        });
      } catch (e) {
        if (e instanceof Drop) return null;
        throw e;
      }
    }

    const body = template.replace(OPTIONAL, (m, inner) => fill(inner, true) || '');
    return tidy(fill(body, false) || '');
  }

  // The type's worked example, rendered through its own template.
  function renderExample(id, style = 'law_review') {
    const example = typeSpec(id).example;
    if (!example) return null;
    const fields = {};
    Object.entries(example).forEach(([k, v]) => {
      if (v) fields[k] = v;
    });
    return render(id, fields, style);
  }

  function diagnose(text, style = 'law_review') {
    const match = bestMatch(text);
    if (match === null) return null;
    const spec1 = typeSpec(match.typeId);
    const miss = missing(match.typeId, match.fields);
    const byName = {};
    spec1.fields.forEach((f) => {
      byName[f.name] = f;
    });
    return {
      typeId: match.typeId,
      label: spec1.label,
      fields: match.fields,
      missing: miss,
      formatted: render(match.typeId, match.fields, style),
      template: render(match.typeId, match.fields, style, true) || '',
      details: miss.map((n) => ({
        field: n,
        label: byName[n].label,
        rule: byName[n].rule || '',
        display_rule: displayRule(byName[n].rule),
        why: byName[n].why || '',
      })),
      citationType: spec1.citation_type || 'other',
      confidence: spec1.confidence || 'medium',
      notes: [...(spec1.notes || [])],
      family: spec1.family || '',
    };
  }

  return {
    spec,
    typeSpec,
    fieldSpecs,
    requiredFields,
    findAll,
    bestMatch,
    missing,
    displayRule,
    render,
    renderExample,
    diagnose,
  };
}
