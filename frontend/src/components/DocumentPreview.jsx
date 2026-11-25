import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  buildHighlights,
  hasNext,
  hasPrevious,
  nextPosition,
  openingPosition,
  previousPosition,
  segmentsFor,
} from '../utils/previewWindow';
import { fmt } from '../utils/format';

const navButton =
  'min-h-[44px] px-4 rounded border border-gray-300 bg-white text-gray-800 ' +
  'disabled:bg-gray-100 disabled:text-gray-500 disabled:border-gray-200 disabled:cursor-not-allowed';

/**
 * One window of the document at a time. The window being shown can be kept by the parent
 * (`position` and `onPositionChange`), so leaving this tab and coming back does not send the
 * reader back to the first highlight; on its own it keeps the position itself.
 */
export default function DocumentPreview({
  text,
  citations,
  unsourcedClaims,
  position: controlled,
  onPositionChange,
}) {
  // The server's positions count code points; the window arithmetic here counts UTF-16 units.
  // The text is what lets them be converted, so a new text makes new highlights.
  const highlights = useMemo(
    () => buildHighlights(citations, unsourcedClaims, text),
    [citations, unsourcedClaims, text]
  );

  const [own, setOwn] = useState(null);
  const remembered = controlled ?? own;
  const setPosition = onPositionChange ?? setOwn;

  const position = useMemo(() => {
    if (!text) return null;
    // A position left over from a different text cannot be trusted.
    if (remembered && remembered.end <= text.length) return remembered;
    return openingPosition(text, highlights);
  }, [text, highlights, remembered]);

  const segments = useMemo(
    () => (position ? segmentsFor(text, highlights, position.start, position.end) : []),
    [text, highlights, position]
  );

  // A new window is read from its top. The pane keeps its scroll offset otherwise, so after
  // reading to the bottom of one window, Next would land near the bottom of the next.
  const paneRef = useRef(null);
  const windowStart = position?.start;
  useLayoutEffect(() => {
    if (paneRef.current) paneRef.current.scrollTop = 0;
  }, [windowStart]);

  if (!text) {
    return (
      <div className="text-center py-8 text-gray-600">
        <p>No document content to display.</p>
      </div>
    );
  }

  const { start, end } = position;

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

      <div className="flex items-center justify-between gap-2 text-xs text-gray-600">
        <button
          type="button"
          disabled={!hasPrevious(position)}
          onClick={() => setPosition(previousPosition(text, position))}
          className={navButton}
        >
          Previous
        </button>
        <span className="text-center" aria-live="polite">
          Characters {fmt(start)} to {fmt(end)} of {fmt(text.length)}
        </span>
        <button
          type="button"
          disabled={!hasNext(text, position)}
          onClick={() => setPosition(nextPosition(text, position))}
          className={navButton}
        >
          Next
        </button>
      </div>

      <div
        ref={paneRef}
        data-testid="preview-pane"
        className="p-4 bg-white border border-gray-200 rounded-lg max-h-[600px] overflow-y-auto"
      >
        <div className="prose prose-sm max-w-none font-serif text-gray-800 whitespace-pre-wrap wrap-anywhere">
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
