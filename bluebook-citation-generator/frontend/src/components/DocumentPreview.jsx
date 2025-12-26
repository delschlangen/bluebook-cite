import React, { useMemo } from 'react';

export default function DocumentPreview({ text, citations, unsourcedClaims }) {
  const highlightedText = useMemo(() => {
    if (!text) return null;
    
    // Collect all highlights
    const highlights = [];
    
    citations?.forEach(c => {
      highlights.push({
        start: c.position_start,
        end: c.position_end,
        type: 'citation',
        status: c.status,
      });
    });
    
    unsourcedClaims?.forEach(c => {
      highlights.push({
        start: c.position_start,
        end: c.position_end,
        type: 'unsourced',
      });
    });
    
    // Sort by position
    highlights.sort((a, b) => a.start - b.start);
    
    // Build segments
    const segments = [];
    let lastEnd = 0;
    
    for (const highlight of highlights) {
      // Add text before highlight
      if (highlight.start > lastEnd) {
        segments.push({
          text: text.slice(lastEnd, highlight.start),
          type: 'normal',
        });
      }
      
      // Add highlighted text
      if (highlight.end > lastEnd) {
        const start = Math.max(highlight.start, lastEnd);
        segments.push({
          text: text.slice(start, highlight.end),
          type: highlight.type,
          status: highlight.status,
        });
        lastEnd = highlight.end;
      }
    }
    
    // Add remaining text
    if (lastEnd < text.length) {
      segments.push({
        text: text.slice(lastEnd),
        type: 'normal',
      });
    }
    
    return segments;
  }, [text, citations, unsourcedClaims]);

  if (!text) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>No document content to display.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Legend */}
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
      
      {/* Document text */}
      <div className="p-4 bg-white border border-gray-200 rounded-lg max-h-[600px] overflow-y-auto">
        <div className="prose prose-sm max-w-none font-serif text-gray-800 whitespace-pre-wrap">
          {highlightedText?.map((segment, index) => {
            if (segment.type === 'normal') {
              return <span key={index}>{segment.text}</span>;
            }
            
            if (segment.type === 'citation') {
              return (
                <span
                  key={index}
                  className="citation-highlight"
                  title={`Citation (${segment.status})`}
                >
                  {segment.text}
                </span>
              );
            }
            
            if (segment.type === 'unsourced') {
              return (
                <span
                  key={index}
                  className="unsourced-highlight"
                  title="May need citation"
                >
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
