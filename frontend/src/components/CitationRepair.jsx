import React, { useCallback, useEffect, useRef, useState } from 'react';
import { diagnose, repairCitation } from '../services/api';
import { copyCitation, renderCitation } from '../utils/citationText';
import { repairLocally } from '../utils/localCitation';
import CitationTypeGuide, {
  ConfidenceNote,
  RuleLabel,
  renderTemplate,
} from './CitationTypeGuide';

const EXAMPLES = [
  'Moody v. NetChoice',
  'U.S. Const. amend. XIV',
  '47 CFR 54.101',
  'GAO-16-552',
  'Restatement (Second) of Torts § 402A',
];

const STYLES = [
  { id: 'law_review', label: 'Law review footnote', hint: 'Authors and titles in capitals' },
  { id: 'practitioner', label: 'Court document', hint: 'Ordinary type, italic titles' },
];

const STATUS_META = {
  resolved: {
    label: 'Ready to use',
    tone: 'border-green-200 bg-green-50',
    badge: 'bg-green-100 text-green-800',
  },
  ambiguous: {
    label: 'Needs your choice',
    tone: 'border-amber-200 bg-amber-50',
    badge: 'bg-amber-100 text-amber-800',
  },
  incomplete: {
    label: 'Missing information',
    tone: 'border-blue-200 bg-blue-50',
    badge: 'bg-blue-100 text-blue-800',
  },
  unparseable: {
    label: 'Not recognized',
    tone: 'border-gray-200 bg-gray-50',
    badge: 'bg-gray-200 text-gray-700',
  },
};

const STYLE_KEY = 'bluebook-style';

function loadStyle() {
  try {
    const saved = window.localStorage.getItem(STYLE_KEY);
    return STYLES.some((s) => s.id === saved) ? saved : 'law_review';
  } catch {
    return 'law_review';
  }
}

export default function CitationRepair() {
  const [text, setText] = useState('');
  const [style, setStyle] = useState(loadStyle);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const requestId = useRef(0);

  const run = useCallback(async (value, chosenStyle) => {
    const trimmed = value.trim();
    if (!trimmed) {
      setResult(null);
      setError(null);
      return;
    }

    const id = ++requestId.current;
    setError(null);

    // Parse and format locally first. This is instant, needs no network, and is the
    // complete answer whenever the citation is one the browser understands.
    const local = repairLocally(trimmed, chosenStyle);
    if (id === requestId.current) setResult(local);

    if (!local.needsLookup) {
      if (id === requestId.current) setLoading(false);
      return;
    }

    // Either a database could fill the gaps, or the browser did not recognise the paste
    // and the server may (it reads books, articles and websites).
    setLoading(true);
    try {
      const response = await repairCitation(trimmed, chosenStyle);
      if (id === requestId.current) setResult(response);
    } catch (err) {
      if (id === requestId.current) {
        const info = await diagnose(err, '/api/repair');
        const unrecognised = local.status === 'unparseable';
        setError({
          ...info,
          detail: unrecognised
            ? `${info.detail} Books, articles and websites can only be checked by the server.`
            : `${info.detail} The missing fields shown were worked out in your browser and are still correct.`,
        });
      }
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  const handleSubmit = (event) => {
    event.preventDefault();
    run(text, style);
  };

  const chooseStyle = (next) => {
    setStyle(next);
    try {
      window.localStorage.setItem(STYLE_KEY, next);
    } catch {
      // A blocked or full store only means the choice is not remembered.
    }
    if (text.trim()) run(text, next);
  };

  const handleCopy = async () => {
    const ok = await copyCitation(result?.formatted);
    if (ok) {
      setCopied(true);
    } else {
      setError({
        message: 'Could not copy.',
        detail: 'Select the citation and copy it manually.',
      });
    }
  };

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const meta = result ? STATUS_META[result.status] ?? STATUS_META.unparseable : null;
  const unrecognised = result?.status === 'unparseable' && text.trim() && !loading;

  return (
    <div className="bg-white rounded-lg shadow-lg p-6 md:p-8">
      <h2 className="text-xl font-semibold">Fix a citation</h2>
      <p className="text-gray-600 mt-1 mb-5">
        Paste any legal citation, whole or partial. You get the Bluebook form, or the
        finished shape with exactly what is missing marked.
      </p>

      <form onSubmit={handleSubmit}>
        <div
          role="radiogroup"
          aria-label="Citation style"
          className="inline-flex rounded-lg border border-gray-200 p-0.5 mb-3 bg-gray-50"
        >
          {STYLES.map((s) => (
            <button
              key={s.id}
              type="button"
              role="radio"
              aria-checked={style === s.id}
              title={s.hint}
              onClick={() => chooseStyle(s.id)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                style === s.id ? 'bg-white shadow text-blue-700' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <label htmlFor="citation-input" className="sr-only">
          Citation to repair
        </label>
        <textarea
          id="citation-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e);
          }}
          rows={3}
          maxLength={2000}
          placeholder="Moody v. NetChoice"
          className="w-full px-4 py-3 border border-gray-300 rounded-lg font-mono text-sm
                     focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-y"
        />

        <div className="flex flex-wrap items-center gap-3 mt-3">
          <button
            type="submit"
            disabled={loading || !text.trim()}
            className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium
                       hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors"
          >
            {loading ? 'Checking...' : 'Fix it'}
          </button>
          {text && (
            <button
              type="button"
              onClick={() => { setText(''); setResult(null); setError(null); }}
              className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
            >
              Clear
            </button>
          )}
          <span className="text-xs text-gray-400 ml-auto">Cmd/Ctrl + Enter</span>
        </div>
      </form>

      {!result && !loading && (
        <div className="mt-6 border-t pt-5">
          <p className="text-xs font-medium text-gray-500 mb-2">Try one of these</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => { setText(example); run(example, style); }}
                className="px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-full
                           text-xs font-mono text-gray-700 hover:bg-blue-50
                           hover:border-blue-200 transition-colors"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="mt-5 p-4 bg-red-50 border border-red-200 rounded-lg" role="alert">
          <p className="text-sm font-medium text-red-900">{error.message}</p>
          {error.detail && (
            <p className="text-xs text-red-700 mt-1 leading-relaxed">{error.detail}</p>
          )}
          <button
            type="button"
            onClick={() => run(text, style)}
            className="mt-3 px-3 py-1.5 bg-white border border-red-200 rounded-lg
                       text-xs font-medium text-red-800 hover:bg-red-50"
          >
            Try again
          </button>
        </div>
      )}

      {result && !loading && (
        <div className={`mt-6 rounded-lg border p-5 ${meta.tone}`} aria-live="polite">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${meta.badge}`}>
              {meta.label}
            </span>
            {(result.kind_label || result.citation_type) && (
              <span className="px-2 py-0.5 rounded text-xs bg-white/70 text-gray-700">
                {result.kind_label || result.citation_type.replace('_', ' ')}
              </span>
            )}
            {result.format_confidence && <ConfidenceNote level={result.format_confidence} />}
          </div>

          {result.formatted && (
            <div className="mb-4">
              <p className="text-base text-gray-900 leading-relaxed">
                {renderCitation(result.formatted)}
              </p>
              <div className="flex flex-wrap items-center gap-3 mt-3">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg
                             text-xs font-medium hover:bg-gray-50 transition-colors"
                >
                  {copied ? 'Copied' : 'Copy'}
                </button>
                {result.verify_url && (
                  <a
                    href={result.verify_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-700 hover:underline font-medium"
                  >
                    Verify on {result.source || 'the source'}
                  </a>
                )}
              </div>
            </div>
          )}

          {result.template && !result.formatted && (
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-600 mb-2">
                What the finished citation looks like
              </p>
              <p className="text-base text-gray-900 leading-relaxed">
                {renderTemplate(result.template)}
              </p>
              <p className="text-xs text-gray-500 mt-1.5">
                Bracketed parts are what you still need to supply.
              </p>
            </div>
          )}

          {result.missing_details?.length > 0 && (
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-600 mb-2">Still needs</p>
              <ul className="space-y-2">
                {result.missing_details.map((detail) => (
                  <li
                    key={detail.field || detail.label}
                    className="p-3 bg-white/80 border border-gray-200 rounded"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                      <span className="text-sm font-medium text-gray-900">{detail.label}</span>
                      <RuleLabel rule={detail.display_rule} />
                    </div>
                    {detail.why && (
                      <p className="text-xs text-gray-600 mt-1 leading-relaxed">{detail.why}</p>
                    )}
                  </li>
                ))}
              </ul>
              {result.missing_details.some((d) => d.display_rule) && (
                <p className="text-xs text-gray-500 mt-2 leading-relaxed">
                  Rule numbers follow the Bluebook 21st edition. If you use the 22nd, confirm
                  the number there.
                </p>
              )}
            </div>
          )}

          {result.candidates?.length > 0 && (
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-600 mb-2">Possible matches</p>
              <ul className="space-y-2">
                {result.candidates.map((candidate) => (
                  <li
                    key={candidate.verify_url}
                    className="p-3 bg-white rounded border border-gray-200"
                  >
                    <p className="text-sm text-gray-900">{candidate.label}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {[candidate.court, candidate.date].filter(Boolean).join(' · ')}
                    </p>
                    <a
                      href={candidate.verify_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-700 hover:underline"
                    >
                      Open source
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.notes?.map((note) => (
            <p key={note} className="text-xs text-gray-600 leading-relaxed mt-1">
              {note}
            </p>
          ))}
        </div>
      )}

      {unrecognised && (
        <div className="mt-5">
          <p className="text-sm font-medium text-gray-900 mb-3">What kind of source is it?</p>
          <CitationTypeGuide style={style} />
        </div>
      )}

      {!unrecognised && (
        <div className="mt-6">
          <button
            type="button"
            onClick={() => setShowGuide((v) => !v)}
            aria-expanded={showGuide}
            className="text-sm text-blue-700 hover:underline font-medium"
          >
            {showGuide ? 'Hide' : 'Browse'} every kind of citation this tool knows
          </button>
          {showGuide && (
            <div className="mt-4">
              <CitationTypeGuide style={style} />
            </div>
          )}
        </div>
      )}

      <p className="mt-6 pt-4 border-t text-xs text-gray-500 leading-relaxed">
        Nothing is reported as found unless it can be linked to a real record. Always open
        the source and confirm before filing.
      </p>
    </div>
  );
}
