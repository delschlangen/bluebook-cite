import React, { useMemo, useState } from 'react';
import { browseTypes, EDITION_NOTE } from '../utils/localCitation';
import { renderCitation } from '../utils/citationText';

// Render a template: *italics* as emphasis, [gaps] as visible blanks.
export function renderTemplate(text) {
  if (!text) return null;
  return text.split(/(\*[^*]+\*|\[[^\]]+\])/g).map((part, i) => {
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith('[') && part.endsWith(']')) {
      return (
        <span
          key={i}
          className="px-1.5 py-0.5 mx-0.5 rounded bg-amber-100 text-amber-900
                     text-sm font-medium border border-amber-200"
        >
          {part.slice(1, -1)}
        </span>
      );
    }
    return part;
  });
}

/**
 * "Rule 10.3 · Reporters and Services", or nothing when no rule is verified. The number stays in
 * one piece; the title may wrap, and may break inside a word if one is longer than the line, so
 * a long title cannot push the card wider than a phone. (A label that never wrapped made the page
 * 23 px wider than a 390 px screen for "Rule 15 - Books, Reports, and Other Nonperiodic
 * Materials".)
 */
export function RuleLabel({ rule }) {
  if (!rule) return null;
  return (
    <span className="min-w-0 max-w-full text-xs font-mono text-blue-700 [overflow-wrap:anywhere]">
      <span className="whitespace-nowrap">Rule {rule.number}</span>
      <span className="font-sans text-gray-500"> · {rule.title}</span>
    </span>
  );
}

export function ConfidenceNote({ level }) {
  if (level === 'high') {
    return <span className="text-xs text-green-700">Format well established</span>;
  }
  return (
    <span className="text-xs text-amber-700">
      Check this format against your Bluebook
    </span>
  );
}

/**
 * Every kind of citation the tool knows, grouped by family, each with its finished
 * shape, a worked example, and the rule governing each part. This is also the answer
 * to a paste the tool does not recognise: say what the source is, and see what it needs.
 */
export default function CitationTypeGuide({ style, defaultOpenId = null }) {
  const families = useMemo(() => browseTypes(style), [style]);
  const [openId, setOpenId] = useState(defaultOpenId);

  return (
    <div className="space-y-5">
      {families.map((family) => (
        <section key={family.id}>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            {family.label}
          </h3>
          <ul className="space-y-1.5">
            {family.types.map((type) => {
              const open = openId === type.id;
              return (
                <li key={type.id} className="rounded-lg border border-gray-200 bg-white">
                  <button
                    type="button"
                    onClick={() => setOpenId(open ? null : type.id)}
                    aria-expanded={open}
                    className="w-full min-h-[44px] flex items-center justify-between gap-3 px-3 py-2.5
                               text-left text-sm font-medium text-gray-900 hover:bg-gray-50
                               rounded-lg"
                  >
                    <span className="min-w-0">{type.label}</span>
                    <span className="flex-shrink-0 text-xs font-normal text-gray-400">{open ? 'Hide' : 'Show'}</span>
                  </button>

                  {open && (
                    <div className="px-3 pb-3 space-y-3 border-t border-gray-100 pt-3">
                      <div>
                        <p className="text-xs font-medium text-gray-500 mb-1">The finished shape</p>
                        <p className="text-sm text-gray-900 leading-relaxed">
                          {renderTemplate(type.template)}
                        </p>
                      </div>

                      {type.example && (
                        <div>
                          <p className="text-xs font-medium text-gray-500 mb-1">Example</p>
                          <p className="text-sm text-gray-900 leading-relaxed">
                            {renderCitation(type.example)}
                          </p>
                        </div>
                      )}

                      <ul className="space-y-1.5">
                        {type.fields.map((f) => (
                          <li key={f.name} className="text-xs">
                            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                              <span className="min-w-0 font-medium text-gray-800 [overflow-wrap:anywhere]">
                                {f.label}
                                {!f.required && <span className="font-normal text-gray-400"> (optional)</span>}
                              </span>
                              <RuleLabel rule={f.display_rule} />
                            </div>
                            <p className="text-gray-600 leading-relaxed">{f.why}</p>
                          </li>
                        ))}
                      </ul>

                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <ConfidenceNote level={type.confidence} />
                        {!type.recognises && (
                          <span className="text-xs text-gray-500">
                            Guidance only: this tool will not rewrite a pasted citation of this kind.
                          </span>
                        )}
                      </div>

                      {type.notes.map((note) => (
                        <p key={note} className="text-xs text-gray-600 leading-relaxed">{note}</p>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {EDITION_NOTE && <p className="text-xs text-gray-500 leading-relaxed">{EDITION_NOTE}</p>}
    </div>
  );
}
