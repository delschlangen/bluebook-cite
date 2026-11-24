import React, { useState, useCallback } from 'react';
import { uploadDocument } from '../services/api';

const MAX_BYTES = 10 * 1024 * 1024;

// File types we can say, with certainty and before uploading, will not work.
// Anything not listed is sent, and the server decides from the file's bytes.
const KNOWN_UNSUPPORTED = {
  doc: 'Old-format Word (.doc) files are not supported. In Word, choose Save As and pick .docx, or export a PDF.',
  rtf: 'Rich Text Format (.rtf) is not supported. Save it as .docx or PDF.',
  odt: 'OpenDocument (.odt) files are not supported. Save it as .docx or PDF.',
  pages: 'Apple Pages files are not supported. Export to Word (.docx) or PDF first.',
  key: 'Keynote files are not supported. Upload a Word document, PDF or text file.',
  numbers: 'Numbers files are not supported. Upload a Word document, PDF or text file.',
  pptx: 'PowerPoint files are not supported. Upload a Word document, PDF or text file.',
  xlsx: 'Excel files are not supported. Upload a Word document, PDF or text file.',
  jpg: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
  jpeg: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
  png: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
  heic: 'Images are not supported. Upload a PDF with selectable text, or a Word or text file.',
};

function unsupportedReason(file) {
  const name = (file?.name || '').toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop() : '';
  return KNOWN_UNSUPPORTED[ext] || null;
}

// Hosting platforms reject large request bodies before the app sees them, and a
// rejected request carries no CORS headers, so the browser reports it only as a
// failed fetch. Say what is likely going on instead of "could not reach server".
const HOST_LIMIT_BYTES = 4 * 1024 * 1024;

function explainUploadFailure(err, file) {
  if (err?.offline && file.size > HOST_LIMIT_BYTES) {
    const mb = (file.size / (1024 * 1024)).toFixed(1);
    return (
      `The upload failed. This file is ${mb} MB, and some hosts reject uploads over ` +
      `about 4 MB without any explanation. Try a smaller file, or a PDF or ` +
      `text copy of the same document.`
    );
  }
  return err?.message || 'The upload failed.';
}

export default function FileUpload({ onUpload }) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);

  const handleFile = useCallback(async (file) => {
    // The browser's reported type is NOT checked. Phones send an empty or
    // generic type for Word and PDF files that come from iCloud or Google Drive,
    // and rejecting on it blocked working files before a single byte was sent.
    // The server identifies the format from the file's own contents.
    const problem = unsupportedReason(file);
    if (problem) {
      setError(problem);
      return;
    }

    if (file.size > MAX_BYTES) {
      setError('File size must be less than 10MB');
      return;
    }

    setError(null);
    setUploading(true);

    try {
      const result = await uploadDocument(file);
      onUpload(result);
    } catch (err) {
      setError(explainUploadFailure(err, file));
    } finally {
      setUploading(false);
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
  }, [handleFile]);

  return (
    <div className="w-full">
      <label
        className={`flex flex-col items-center justify-center w-full h-48 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
          isDragging
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
        } ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <div className="flex flex-col items-center justify-center pt-5 pb-6">
          {uploading ? (
            <>
              <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-200 border-t-blue-600 mb-3"></div>
              <p className="text-sm text-gray-500">Uploading...</p>
            </>
          ) : (
            <>
              <svg className="w-10 h-10 mb-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="mb-2 text-sm text-gray-500">
                <span className="font-semibold">Click to upload</span> or drag and drop
              </p>
              <p className="text-xs text-gray-400">PDF, Word (.docx), or text (max 10MB). Footnotes are read.</p>
            </>
          )}
        </div>
        <input
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
          onChange={handleInputChange}
          disabled={uploading}
        />
      </label>

      {error && (
        <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}
    </div>
  );
}
