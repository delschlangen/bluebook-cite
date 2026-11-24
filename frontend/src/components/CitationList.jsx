import React, { memo, useMemo, useState } from 'react';
import { renderCitation } from '../utils/citationText';
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
const PAGE_SIZE = 100;

const CitationCard = memo(function CitationCard({ citation, index, suggestion, isSelected, onSelect }) {
  return (
    <div
      onClick={() => onSelect(citation)}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
          : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-gray-400">#{index + 1}</span>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColors[citation.status]}`}>
              {citation.status.replace('_', ' ')}
            </span>
            <span className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600">
              {citation.kind_label || typeLabels[citation.type] || citation.type}
            </span>
            {citation.footnote_number && (
              <span className="text-xs text-gray-400">Note {citation.footnote_number}</span>
            )}
          </div>

          <p className="text-sm text-gray-700 mb-2 font-mono break-words">{citation.raw_text}</p>

          {suggestion?.suggested_form && suggestion.suggested_form !== citation.raw_text && (
            <div className="mt-2 p-2 bg-green-50 rounded border border-green-100">
              <p className="text-xs text-green-700 font-medium mb-1">
                Suggested ({suggestion.short_form_type}):
              </p>
              <p className="text-sm text-green-800 font-mono">{renderCitation(suggestion.suggested_form)}</p>
              {suggestion.explanation && (
                <p className="text-xs text-green-600 mt-1">{suggestion.explanation}</p>
              )}
            </div>
          )}

          {citation.missing?.length > 0 && citation.template && (
            <div className="mt-2 p-2 bg-amber-50 rounded border border-amber-100">
              <p className="text-xs text-amber-800 font-medium mb-1">
                Still needs: {citation.missing.join(', ')}
              </p>
              <p className="text-sm text-gray-900 leading-relaxed">{renderTemplate(citation.template)}</p>
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
  );
});

export default function CitationList({ citations, shortFormSuggestions, onSelect, selectedId }) {
  const [shown, setShown] = useState(PAGE_SIZE);
  // One pass to index the suggestions; the old code ran .find() over all of them per card.
  const suggestionById = useMemo(() => {
    const map = new Map();
    (shortFormSuggestions || []).forEach((s) => map.set(s.citation_id, s));
    return map;
  }, [shortFormSuggestions]);

  if (!citations || citations.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>No citations found in this document.</p>
      </div>
    );
  }

  const visible = citations.slice(0, shown);
  const remaining = citations.length - visible.length;

  return (
    <div className="space-y-3">
      {visible.map((citation, index) => (
        <CitationCard
          key={citation.id}
          citation={citation}
          index={index}
          suggestion={suggestionById.get(citation.id)}
          isSelected={selectedId === citation.id}
          onSelect={onSelect}
        />
      ))}
      {remaining > 0 && (
        <button
          type="button"
          onClick={() => setShown((n) => n + PAGE_SIZE)}
          className="w-full py-3 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 hover:bg-gray-50"
        >
          Show {Math.min(PAGE_SIZE, remaining)} more ({remaining} not shown)
        </button>
      )}
    </div>
  );
}
