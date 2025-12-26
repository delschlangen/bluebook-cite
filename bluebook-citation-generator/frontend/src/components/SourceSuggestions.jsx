import React from 'react';

const claimTypeColors = {
  legal: 'bg-purple-100 text-purple-800',
  statistical: 'bg-blue-100 text-blue-800',
  factual: 'bg-gray-100 text-gray-800',
  quotation: 'bg-yellow-100 text-yellow-800',
};

export default function SourceSuggestions({ claims }) {
  if (!claims || claims.length === 0) {
    return (
      <div className="text-center py-8">
        <svg className="w-12 h-12 mx-auto mb-3 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-gray-600 font-medium">No unsourced claims detected</p>
        <p className="text-sm text-gray-400 mt-1">All statements appear to have citations</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        The following statements may need citations. Review each and consider adding appropriate sources.
      </p>
      
      {claims.map((claim, index) => (
        <div key={claim.id || index} className="p-4 bg-red-50 border border-red-100 rounded-lg">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-400">#{index + 1}</span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${claimTypeColors[claim.claim_type]}`}>
                {claim.claim_type}
              </span>
              <span className="text-xs text-gray-500">
                {Math.round(claim.confidence * 100)}% confidence
              </span>
            </div>
          </div>
          
          <p className="text-sm text-gray-800 mb-3 leading-relaxed">
            "{claim.text}"
          </p>
          
          {claim.suggested_search_terms && claim.suggested_search_terms.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-gray-500 mb-2">Suggested search terms:</p>
              <div className="flex flex-wrap gap-2">
                {claim.suggested_search_terms.map((term, i) => (
                  <a
                    key={i}
                    href={`https://www.courtlistener.com/?q=${encodeURIComponent(term)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-2 py-1 bg-white border border-gray-200 rounded text-xs text-blue-600 hover:bg-blue-50 hover:border-blue-200 transition-colors"
                  >
                    {term} →
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
