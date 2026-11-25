import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { diagnose, getLimits, repairCitation, subscribeLimits } from '../services/api';
import { copyCitation, renderCitation } from '../utils/citationText';
import { countCharacters, fmt } from '../utils/format';
import { partialMessage, repairLocally } from '../utils/localCitation';
import CitationTypeGuide, {
  ConfidenceNote,
  RuleLabel,
  renderTemplate,
} from './CitationTypeGuide';
import ExternalLink from './ExternalLink';
import RetryButton from './RetryButton';

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

// A paste that holds more than one citation is only partly handled, whatever its status says.
const PARTIAL_META = {
  label: 'Only part of your paste',
  tone: 'border-amber-300 bg-amber-50',
  badge: 'bg-amber-200 text-amber-950',
};

const STYLE_KEY = 'bluebook-style';

// The counter appears when the text is this close to the limit.
const COUNTER_FROM = 0.8;

const RETRY_CLASS =
  'mt-3 min-h-[44px] px-4 py-1.5 bg-white border border-red-200 rounded-lg ' +
  'text-xs font-medium text-red-800 hover:bg-red-50 disabled:text-red-900 disabled:opacity-70 ' +
  'disabled:cursor-not-allowed';

let errorSerial = 0;

function loadStyle() {
  try {
    const saved = window.localStorage.getItem(STYLE_KEY);
    return STYLES.some((s) => s.id === saved) ? saved : 'law_review';
  } catch {
    return 'law_review';
  }
}

const isPartial = (value) =>
  Boolean(value) && typeof value.used === 'string' && Array.isArray(value.others) && value.others.length > 0;
const list = (value) => (Array.isArray(value) ? value : []);

export default function CitationRepair() {
  const [text, setText] = useState('');
  const [style, setStyle] = useState(loadStyle);
  const [result, setResult] = useState(null);
  // The text and style the result on screen was worked out for. Typing changes the text but
  // not the result, so a card for one thing must not sit under another, ready to copy.
  const [resultFor, setResultFor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [limits, setLimits] = useState(getLimits);
  // Each run gets a number, and its own AbortController. An answer, or a failure, that arrives
  // after Clear or after a newer run belongs to a run that no longer exists and is dropped.
  const requestId = useRef(0);
  const controller = useRef(null);

  useEffect(() => subscribeLimits(setLimits), []);

  const limit = limits.max_repair_chars;
  const limitRef = useRef(limit);
  limitRef.current = limit;

  // Stop whatever is running and make its answer unwelcome.
  const cancelPending = useCallback(() => {
    requestId.current += 1;
    controller.current?.abort();
    controller.current = null;
    setLoading(false);
  }, []);

  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(
    async (value, chosenStyle) => {
      // Whatever was running was for text the person has moved on from.
      cancelPending();
      const trimmed = value.trim();
      if (!trimmed) {
        setResult(null);
        setResultFor(null);
        setError(null);
        return;
      }
      // The server refuses more than this, and the page does not cut the text to fit it.
      if (countCharacters(value) > limitRef.current) return;

      const id = requestId.current;
      setError(null);

      // Parse and format locally first. This is instant, needs no network, and is the
      // complete answer whenever the citation is one the browser understands.
      const local = repairLocally(trimmed, chosenStyle);
      setResult(local);
      setResultFor({ text: trimmed, style: chosenStyle });
      if (!local.needsLookup) return;

      // Either a database could fill the gaps, or the browser did not recognise the paste
      // and the server may (it reads books, articles and websites).
      const mine = new AbortController();
      controller.current = mine;
      setLoading(true);
      try {
        const response = await repairCitation(trimmed, chosenStyle, { signal: mine.signal });
        if (id !== requestId.current) return;
        // The server reads the same text with the same readers, so the citations it left aside
        // are the ones the browser found.
        setResult(local.partial ? { ...response, partial: local.partial } : response);
      } catch (err) {
        if (err?.cancelled || id !== requestId.current) return;
        const info = await diagnose(err, '/api/repair');
        // The probe can take many seconds; something newer may have happened in that time.
        if (id !== requestId.current) return;
        const kept =
          local.status === 'unparseable'
            ? 'Books, articles and websites can only be checked by the server.'
            : 'The missing fields shown were worked out in your browser and are still correct.';
        setError({
          id: ++errorSerial,
          message: info.message,
          detail: [info.detail, kept].filter(Boolean).join(' '),
          retryAfter: info.retryAfter,
          canRetry: true,
        });
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [cancelPending]
  );

  const characters = useMemo(() => countCharacters(text), [text]);
  const tooLong = characters > limit;
  const nearLimit = characters >= Math.floor(limit * COUNTER_FROM);

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

  const handleClear = () => {
    cancelPending();
    setText('');
    setResult(null);
    setResultFor(null);
    setError(null);
  };

  const handleCopy = async () => {
    const ok = await copyCitation(result?.formatted);
    if (ok) {
      setCopied(true);
    } else {
      setError({
        id: ++errorSerial,
        message: 'Could not copy.',
        detail: 'Select the citation and copy it manually.',
        canRetry: false,
      });
    }
  };

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const partial = isPartial(result?.partial) ? result.partial : null;
  const meta = result ? (partial ? PARTIAL_META : STATUS_META[result.status] ?? STATUS_META.unparseable) : null;
  const stale = Boolean(result) && (!resultFor || resultFor.text !== text.trim() || resultFor.style !== style);
  const unrecognised = result?.status === 'unparseable' && text.trim() && !loading;
  const missingDetails = list(result?.missing_details);
  const candidates = list(result?.candidates);
  const notes = list(result?.notes);

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
              className={`min-h-[44px] px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
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
          placeholder="Moody v. NetChoice"
          aria-invalid={tooLong || undefined}
          aria-describedby={nearLimit ? 'citation-count' : undefined}
          className={`w-full px-4 py-3 border rounded-lg font-mono text-sm
                     focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-y ${
                       tooLong ? 'border-red-400' : 'border-gray-300'
                     }`}
        />
        {/* The text is never cut to fit. Near the limit the count is shown; over it, Fix it is off. */}
        {nearLimit && (
          <p
            id="citation-count"
            data-testid="citation-count"
            className={`mt-1.5 text-xs leading-relaxed ${tooLong ? 'text-red-700' : 'text-gray-600'}`}
          >
            {fmt(characters)} of {fmt(limit)} characters.
            {tooLong &&
              ' That is too long for Fix a citation. Paste one citation at a time, or use ' +
                'Check a document for a longer text.'}
          </p>
        )}
        {/* Spoken once when the limit is neared or passed, not on every key. */}
        <p className="sr-only" role="status">
          {tooLong
            ? `Over the ${fmt(limit)} character limit. Fix it is off until the text is shorter.`
            : nearLimit
              ? `Close to the ${fmt(limit)} character limit.`
              : ''}
        </p>

        <div className="flex flex-wrap items-center gap-3 mt-3">
          <button
            type="submit"
            disabled={loading || !text.trim() || tooLong}
            className="min-h-[44px] px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium
                       hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors"
          >
            {loading ? 'Checking...' : 'Fix it'}
          </button>
          {text && (
            <button
              type="button"
              onClick={handleClear}
              className="min-h-[44px] px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
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
                className="min-h-[44px] px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-full
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
          {error.canRetry && (
            <RetryButton
              key={error.id}
              waitSeconds={error.retryAfter}
              onRetry={() => run(text, style)}
              className={RETRY_CLASS}
            />
          )}
        </div>
      )}

      {result && !loading && (
        <div
          className={`mt-6 rounded-lg border p-5 ${stale ? 'border-gray-200 bg-gray-50 opacity-70' : meta.tone}`}
          aria-live="polite"
        >
          {stale && (
            <p className="mb-4 text-sm font-medium text-amber-900" data-testid="stale-note">
              This result is for the text before you changed it. Press Fix it to update it.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${meta.badge}`}>
              {meta.label}
            </span>
            {(result.kind_label || result.citation_type) && (
              <span className="px-2 py-0.5 rounded text-xs bg-white/70 text-gray-700">
                {result.kind_label || String(result.citation_type).replace('_', ' ')}
              </span>
            )}
            {result.format_confidence && <ConfidenceNote level={result.format_confidence} />}
          </div>

          {partial && (
            <p
              data-testid="partial-note"
              className="mb-4 rounded border border-amber-300 bg-amber-100 px-3 py-2 text-sm leading-relaxed text-amber-950"
            >
              {partialMessage(partial)}
            </p>
          )}

          {result.formatted && (
            <div className="mb-4">
              <p className="text-base text-gray-900 leading-relaxed">
                {renderCitation(result.formatted)}
              </p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-3">
                <button
                  type="button"
                  onClick={handleCopy}
                  disabled={stale}
                  className="min-h-[44px] px-4 py-1.5 bg-white border border-gray-300 rounded-lg
                             text-xs font-medium hover:bg-gray-50 transition-colors
                             disabled:text-gray-500 disabled:cursor-not-allowed"
                >
                  {copied ? 'Copied' : 'Copy'}
                </button>
                <ExternalLink
                  href={result.verify_url}
                  className="inline-flex items-center min-h-[44px] text-xs text-blue-700 hover:underline font-medium"
                >
                  Verify on {result.source || 'the source'}
                </ExternalLink>
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

          {missingDetails.length > 0 && (
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-600 mb-2">Still needs</p>
              <ul className="space-y-2">
                {missingDetails.map((detail, index) => (
                  <li
                    key={detail.field || detail.label || index}
                    className="p-3 bg-white/80 border border-gray-200 rounded"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                      <span className="min-w-0 text-sm font-medium text-gray-900 [overflow-wrap:anywhere]">
                        {detail.label}
                      </span>
                      <RuleLabel rule={detail.display_rule} />
                    </div>
                    {detail.why && (
                      <p className="text-xs text-gray-600 mt-1 leading-relaxed">{detail.why}</p>
                    )}
                  </li>
                ))}
              </ul>
              {missingDetails.some((d) => d.display_rule) && (
                <p className="text-xs text-gray-500 mt-2 leading-relaxed">
                  Rule numbers follow the Bluebook 21st edition. If you use the 22nd, confirm
                  the number there.
                </p>
              )}
            </div>
          )}

          {candidates.length > 0 && (
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-600 mb-2">Possible matches</p>
              <ul className="space-y-2">
                {candidates.map((candidate, index) => (
                  <li
                    key={`${index}-${candidate.verify_url}`}
                    className="p-3 bg-white rounded border border-gray-200"
                  >
                    <p className="text-sm text-gray-900 [overflow-wrap:anywhere]">{candidate.label}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {[candidate.court, candidate.date].filter(Boolean).join(' · ')}
                    </p>
                    <ExternalLink
                      href={candidate.verify_url}
                      className="inline-flex items-center min-h-[44px] text-xs text-blue-700 hover:underline"
                    >
                      Open source
                    </ExternalLink>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {notes.map((note, index) => (
            <p key={`${index}-${note}`} className="text-xs text-gray-600 leading-relaxed mt-1">
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
            className="inline-flex items-center min-h-[44px] text-sm text-blue-700 hover:underline font-medium"
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
