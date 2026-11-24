import React, { useState, useCallback, useEffect, useRef } from 'react';
import { explainNetworkFailure, getLimits, subscribeLimits, uploadDocument } from '../services/api';
import { checkFileBeforeUpload, limitsSummary, uploadingMessage } from '../utils/uploadChecks';

export default function FileUpload({ onUpload }) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(null); // the file being sent, or null
  const [error, setError] = useState(null);
  // The limits the server enforces, once the page has heard them; until then the defaults.
  const [limits, setLimits] = useState(getLimits);
  // A drop is not blocked by the disabled input, so guard against a second file while one is in flight.
  const busyRef = useRef(false);

  useEffect(() => subscribeLimits(setLimits), []);

  const handleFile = useCallback(async (file) => {
    if (busyRef.current) return;
    // The browser's reported type is NOT checked. Phones send an empty or
    // generic type for Word and PDF files that come from iCloud or Google Drive,
    // and rejecting on it blocked working files before a single byte was sent.
    // The server identifies the format from the file's own contents.
    const problem = checkFileBeforeUpload(file, getLimits());
    if (problem) {
      setError(problem);
      return;
    }

    setError(null);
    busyRef.current = true;
    setUploading(file);

    try {
      const result = await uploadDocument(file);
      onUpload(result);
    } catch (err) {
      if (err?.cancelled) return;
      // A response the server sent already says what is wrong (too long, unreadable, empty).
      // No response at all could be a crash, a restart or a dropped connection, and the
      // browser reports them all the same, so ask the server which it was.
      setError(
        err?.offline
          ? await explainNetworkFailure('The upload failed')
          : err?.message || 'The upload failed.'
      );
    } finally {
      busyRef.current = false;
      setUploading(null);
    }
  }, [onUpload]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);

    const file = e.dataTransfer.files[0];
    if (file) {
      handleFile(file);
    }
  }, [handleFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleInputChange = useCallback((e) => {
    const file = e.target.files[0];
    if (file) {
      handleFile(file);
    }
    // Picking the same file again after a failure must fire a change event.
    e.target.value = '';
  }, [handleFile]);

  return (
    <div className="w-full">
      <label
        className={`flex flex-col items-center justify-center w-full min-h-48 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
          isDragging
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
        } ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <div className="flex flex-col items-center justify-center px-4 pt-5 pb-6 text-center">
          {uploading ? (
            <>
              <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-200 border-t-blue-600 mb-3"></div>
              <p className="text-sm text-gray-500" role="status">{uploadingMessage(uploading)}</p>
            </>
          ) : (
            <>
              <svg className="w-10 h-10 mb-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="mb-2 text-sm text-gray-500">
                <span className="font-semibold">Click to upload</span> or drag and drop
              </p>
              <p className="text-xs text-gray-400" data-testid="upload-limits">{limitsSummary(limits)}</p>
            </>
          )}
        </div>
        <input
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
          onChange={handleInputChange}
          disabled={Boolean(uploading)}
        />
      </label>

      {error && (
        <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg" role="alert">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}
    </div>
  );
}
