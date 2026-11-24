import React, { useMemo, useState } from 'react';
import { WINDOW, buildHighlights, buildWindow, firstWindowStart } from '../utils/previewWindow';

export default function DocumentPreview({ text, citations, unsourcedClaims }) {
  const highlights = useMemo(
    () => buildHighlights(citations, unsourcedClaims),
    [citations, unsourcedClaims]
  );

  const [from, setFrom] = useState(() => firstWindowStart(highlights));

  const view = useMemo(
    () => (text ? buildWindow(text, highlights, from) : null),
    [text, highlights, from]
  );

  if (!text) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>No document content to display.</p>
      </div>
    );
  }

  const { segments, start, end } = view;

  return (
    <div className="space-y-4">
      <div className="flex gap-4 text-xs">
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 bg-blue-100 border-b-2 border-blue-500 rounded-sm"></span>
          <span className="text-gray-600">Citation</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="w-3 h-3 bg-red-100 border-b-2 border-red-500 border-dashed rounded-sm"></span>
          <span className="text-gray-600">Unsourced claim</span>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-gray-600">
        <button
          type="button"
          disabled={start <= 0}
          onClick={() => setFrom(Math.max(0, start - WINDOW))}
          className="px-3 py-2 rounded border border-gray-300 bg-white disabled:opacity-40"
        >
          Previous
        </button>
        <span>
          Characters {start.toLocaleString()} to {end.toLocaleString()} of {text.length.toLocaleString()}
        </span>
        <button
          type="button"
          disabled={end >= text.length}
          onClick={() => setFrom(end)}
          className="px-3 py-2 rounded border border-gray-300 bg-white disabled:opacity-40"
        >
          Next
        </button>
      </div>

      <div className="p-4 bg-white border border-gray-200 rounded-lg max-h-[600px] overflow-y-auto">
        <div className="prose prose-sm max-w-none font-serif text-gray-800 whitespace-pre-wrap">
          {segments.map((segment, index) => {
            if (segment.type === 'citation') {
              return (
                <span key={index} className="citation-highlight" title={`Citation (${segment.status})`}>
                  {segment.text}
                </span>
              );
            }
            if (segment.type === 'unsourced') {
              return (
                <span key={index} className="unsourced-highlight" title="May need citation">
                  {segment.text}
                </span>
              );
            }
            return <span key={index}>{segment.text}</span>;
          })}
        </div>
      </div>
    </div>
  );
}
