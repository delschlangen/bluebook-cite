import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getLimits, subscribeLimits } from '../services/api';
import { CHECKING_SERVER_MESSAGE, limitsSummary, uploadingMessage } from '../utils/uploadChecks';

/**
 * The upload box. It only shows what the page is doing and hands files up: the upload itself
 * (and the way to cancel it) lives in App, so it carries on, and can be cancelled, whichever
 * panel is on screen.
 *
 * - `uploading`: { file, phase } while a file is going up; phase is 'sending' or 'checking'
 *   (finding out why it did not finish). null otherwise.
 * - `error`, `notice`: what to say under the box; an error is a failure, a notice is a remark
 *   (a second file was ignored, the upload was cancelled).
 * - `onFiles(files)` is called with every file that was chosen or dropped.
 */
export default function FileUpload({ uploading = null, error = null, notice = null, onFiles, onCancel }) {
  const [isDragging, setIsDragging] = useState(false);
  // The limits the server enforces, once the page has heard them; until then the defaults.
  const [limits, setLimits] = useState(getLimits);

  useEffect(() => subscribeLimits(setLimits), []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer?.files || []);
      if (files.length) onFiles?.(files);
    },
    [onFiles]
  );

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleInputChange = useCallback(
    (e) => {
      const files = Array.from(e.target.files || []);
      // Picking the same file again after a failure must fire a change event.
      e.target.value = '';
      if (files.length) onFiles?.(files);
    },
    [onFiles]
  );

  const busy = Boolean(uploading);

  // On a small phone the box and its Cancel can start below the first screen, under the heading
  // and the intro. When an upload starts, bring Cancel (and the box above it) into view, scrolling
  // only as far as needed. Optional calls: jsdom has no scrollIntoView.
  const cancelRef = useRef(null);
  useEffect(() => {
    if (busy) cancelRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [busy]);

  return (
    <div className="w-full">
      <label
        data-testid="dropzone"
        className={`flex flex-col items-center justify-center w-full min-h-48 border-2 border-dashed rounded-lg transition-colors focus-within:ring-2 focus-within:ring-blue-500 focus-within:ring-offset-2 ${
          busy ? 'cursor-wait' : 'cursor-pointer'
        } ${
          isDragging
            ? 'border-blue-500 bg-blue-50'
            : busy
              ? 'border-gray-300 bg-gray-100'
              : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
        }`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <div className="flex flex-col items-center justify-center px-4 pt-5 pb-6 text-center">
          {busy ? (
            <>
              <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-200 border-t-blue-600 mb-3"></div>
              <p className="text-sm text-gray-700 wrap-anywhere" role="status">
                {uploading.phase === 'checking' ? CHECKING_SERVER_MESSAGE : uploadingMessage(uploading.file)}
              </p>
            </>
          ) : (
            <>
              <svg className="w-10 h-10 mb-3 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="mb-2 text-sm text-gray-600">
                <span className="font-semibold">Click to upload</span> or drag and drop
              </p>
              <p className="text-xs text-gray-600" data-testid="upload-limits">{limitsSummary(limits)}</p>
            </>
          )}
        </div>
        {/* Visually hidden, not display:none, so the keyboard can reach it. */}
        <input
          type="file"
          className="sr-only"
          aria-label="Choose a document to check"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
          onChange={handleInputChange}
          disabled={busy}
        />
      </label>

      {/* Cancel comes first and the reason the other tab is off after it, so that Cancel is not
          pushed down the screen by a line above the box. */}
      {busy && (
        <>
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="mt-3 min-h-[44px] px-5 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            Cancel
          </button>
          <p className="mt-2 text-sm text-gray-600">A file is uploading. Cancel the upload to switch.</p>
        </>
      )}

      {notice && (
        <p className="mt-3 text-sm text-gray-700" role="status" data-testid="upload-notice">
          {notice}
        </p>
      )}

      {error && (
        <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg" role="alert">
          <p className="text-sm text-red-700 wrap-anywhere">{error}</p>
        </div>
      )}
    </div>
  );
}
