import React, { memo, useEffect, useMemo, useRef, useState } from 'react';
import { copyCitation, copyCitations, renderCitation } from '../utils/citationText';
import { editedCitationText } from '../utils/editedCitation';
import { fmt } from '../utils/format';
import { PAGE_SIZE } from '../utils/paging';
import { missingLabels, suggestionFor } from '../utils/suggestion';
import { renderTemplate } from './CitationTypeGuide';

const statusColors = {
  complete: 'bg-green-100 text-green-800',
  incomplete: 'bg-yellow-100 text-yellow-800',
  needs_verification: 'bg-orange-100 text-orange-800',
  malformed: 'bg-red-100 text-red-800',
};

const typeLabels = {
  case: 'Case',
  statute: 'Statute',
  regulation: 'Regulation',
  law_review: 'Article',
  book: 'Book',
  website: 'Website',
  other: 'Other',
};

// Rendering every card is what makes a 4,000-citation result unusable on a phone: thousands
// of cards in the DOM, and every selection re-rendered all of them. Show a page at a time.

// Text that comes from the document or the server (a citation, a URL, a name) has no promise to
// contain a place to break a line. It breaks anywhere rather than push the page wider than the
// screen, and each box that holds it may shrink to the width it is given.
const TEXT = '[overflow-wrap:anywhere]';

/** Copy one edited citation. The result is spoken through `announce`, the list's own live region. */
function CopyEditedButton({ citation, number, announce }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    const ok = await copyCitation(editedCitationText(citation));
    setCopied(ok);
    announce(ok ? `Copied edited citation ${number} to the clipboard.` : 'Could not copy. Select the citation and copy it by hand.');
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`Copy edited citation ${number}`}
      className="min-h-[44px] px-4 rounded-lg border border-blue-200 bg-white text-xs font-medium text-blue-800 hover:bg-blue-50"
    >
      {copied ? 'Copied' : 'Copy edited citation'}
    </button>
  );
}

const CitationCard = memo(function CitationCard({ citation, index, suggestion, isSelected, onSelect, announce }) {
  const suggested = suggestionFor(citation, suggestion);
  const missing = missingLabels(citation);
  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-pressed={isSelected}
        data-card-index={index}
        data-citation-id={citation.id}
        onClick={(e) => onSelect(citation, e.currentTarget)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(citation, e.currentTarget);
          }
        }}
        className={`p-4 rounded-lg border cursor-pointer transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
          isSelected
            ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
            : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm'
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="text-xs font-medium text-gray-600">#{index + 1}</span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColors[citation.status]}`}>
                {citation.status.replace('_', ' ')}
              </span>
              <span className={`min-w-0 max-w-full px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700 ${TEXT}`}>
                {citation.kind_label || typeLabels[citation.type] || citation.type}
              </span>
              {/* A ternary on a number: `0 && ...` would print the 0. */}
              {Number(citation.footnote_number) > 0 ? (
                <span className="text-xs text-gray-600">Note {citation.footnote_number}</span>
              ) : null}
              {citation.edited && (
                <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                  Edited
                </span>
              )}
            </div>

            {citation.edited ? (
              <>
                <p dir="auto" className={`text-sm text-gray-900 mb-1 font-mono ${TEXT}`} data-testid="edited-text">
                  {renderCitation(editedCitationText(citation))}
                </p>
                <p dir="auto" className={`text-xs text-gray-600 mb-2 font-mono ${TEXT}`}>
                  As found in the document: {citation.raw_text}
                </p>
              </>
            ) : (
              <p dir="auto" className={`text-sm text-gray-700 mb-2 font-mono ${TEXT}`}>{citation.raw_text}</p>
            )}

            {suggested && (
              <div
                className={`mt-2 p-2 rounded border min-w-0 ${
                  suggested.complete ? 'bg-green-50 border-green-100' : 'bg-blue-50 border-blue-100'
                }`}
              >
                <p className={`text-xs font-medium mb-1 ${TEXT} ${suggested.complete ? 'text-green-800' : 'text-blue-800'}`}>
                  {suggested.label}
                </p>
                <p dir="auto" className={`text-sm font-mono ${TEXT} ${suggested.complete ? 'text-green-900' : 'text-blue-900'}`}>
                  {renderCitation(suggested.text)}
                </p>
                {suggestion.explanation && (
                  <p dir="auto" className={`text-xs mt-1 ${TEXT} ${suggested.complete ? 'text-green-800' : 'text-blue-800'}`}>
                    {suggestion.explanation}
                  </p>
                )}
              </div>
            )}

            {missing.length > 0 && (
              <div className="mt-2 p-2 bg-amber-50 rounded border border-amber-100 min-w-0">
                <p className={`text-xs text-amber-900 font-medium ${citation.template ? 'mb-1' : ''} ${TEXT}`}>
                  Still missing: {missing.join(', ')}
                </p>
                {citation.template && (
                  <p dir="auto" className={`text-sm text-gray-900 leading-relaxed ${TEXT}`}>
                    {renderTemplate(citation.template)}
                  </p>
                )}
              </div>
            )}
          </div>

          {citation.confidence_score > 0 && (
            <div className="flex-shrink-0">
              <div className="w-10 h-10 rounded-full flex items-center justify-center text-xs font-medium"
                style={{
                  background: `conic-gradient(${
                    citation.confidence_score > 0.8 ? '#22c55e' :
                    citation.confidence_score > 0.5 ? '#eab308' : '#ef4444'
                  } ${citation.confidence_score * 360}deg, #e5e7eb 0deg)`,
                }}>
                <span className="bg-white rounded-full w-7 h-7 flex items-center justify-center">
                  {Math.round(citation.confidence_score * 100)}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
      {/* Beside the card, not in it: a button inside a card that is itself a button is not allowed. */}
      {citation.edited && (
        <div className="mt-2">
          <CopyEditedButton citation={citation} number={index + 1} announce={announce} />
        </div>
      )}
    </div>
  );
});

export default function CitationList({
  citations,
  shortFormSuggestions,
  onSelect,
  selectedId,
  shown: controlledShown,
  onShownChange,
}) {
  // How many cards are out can be kept by the parent, so leaving this tab does not close them.
  const [ownShown, setOwnShown] = useState(PAGE_SIZE);
  const shown = controlledShown ?? ownShown;
  const setShown = onShownChange ?? setOwnShown;

  // What was spoken about copying: always in the page, so what is put in it is read out.
  const [copyNotice, setCopyNotice] = useState('');
  const editedCitations = useMemo(() => (citations || []).filter((c) => c.edited), [citations]);
  const copyAll = async () => {
    const ok = await copyCitations(editedCitations.map(editedCitationText));
    setCopyNotice(
      ok
        ? `Copied ${editedCitations.length} edited citation${editedCitations.length === 1 ? '' : 's'} to the clipboard.`
        : 'Could not copy. Select the citations and copy them by hand.'
    );
  };

  // One pass to index the suggestions; the old code ran .find() over all of them per card.
  const suggestionById = useMemo(() => {
    const map = new Map();
    (shortFormSuggestions || []).forEach((s) => map.set(s.citation_id, s));
    return map;
  }, [shortFormSuggestions]);

  // After "Show more" the button moves far down the page. Put focus on the first card that was
  // added, so a keyboard or screen-reader user is where the new cards begin.
  const listRef = useRef(null);
  const focusIndex = useRef(null);
  useEffect(() => {
    if (focusIndex.current == null) return;
    const card = listRef.current?.querySelector(`[data-card-index="${focusIndex.current}"]`);
    focusIndex.current = null;
    card?.focus();
  }, [shown]);

  if (!citations || citations.length === 0) {
    return (
      <div className="text-center py-8 text-gray-600">
        <p>No citations found in this document.</p>
      </div>
    );
  }

  const visible = citations.slice(0, shown);
  const remaining = citations.length - visible.length;

  return (
    <div ref={listRef}>
      {/* Spoken when "Show more" adds cards; the count on screen is the button's. */}
      <p className="sr-only" aria-live="polite">
        Showing {fmt(visible.length)} of {fmt(citations.length)} citations
      </p>
      <p className="sr-only" role="status" data-testid="copy-notice">{copyNotice}</p>
      {editedCitations.length > 0 && (
        <button
          type="button"
          onClick={copyAll}
          className="mb-3 min-h-[44px] px-4 rounded-lg border border-blue-200 bg-white text-sm font-medium text-blue-800 hover:bg-blue-50"
        >
          Copy all edited ({fmt(editedCitations.length)})
        </button>
      )}
      <div className="space-y-3">
      {visible.map((citation, index) => (
        <CitationCard
          key={citation.id}
          citation={citation}
          index={index}
          suggestion={suggestionById.get(citation.id)}
          isSelected={selectedId === citation.id}
          onSelect={onSelect}
          announce={setCopyNotice}
        />
      ))}
      {remaining > 0 && (
        <button
          type="button"
          onClick={() => {
            focusIndex.current = visible.length;
            setShown(shown + PAGE_SIZE);
          }}
          className="w-full min-h-[44px] py-3 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 hover:bg-gray-50"
        >
          Show {fmt(Math.min(PAGE_SIZE, remaining))} more ({fmt(remaining)} not shown)
        </button>
      )}
      </div>
    </div>
  );
}
