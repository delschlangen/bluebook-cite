import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import FileUpload from './components/FileUpload';
import CitationList from './components/CitationList';
import CitationEditor from './components/CitationEditor';
import CitationRepair from './components/CitationRepair';
import ConfirmDialog from './components/ConfirmDialog';
import SourceSuggestions from './components/SourceSuggestions';
import DocumentPreview from './components/DocumentPreview';
import RetryButton from './components/RetryButton';
import { useMediaQuery } from './hooks/useMediaQuery';
import {
  UNEXPECTED_FORMAT_MESSAGE,
  analyzeDocument,
  checkHealth,
  explainNetworkFailure,
  getLimits,
  lookupCitation,
  uploadDocument,
} from './services/api';
import { normalizeAnalysis, normalizeUpload } from './utils/analysisShape';
import { editedFieldsDiffer } from './utils/editedCitation';
import { focusIfLost } from './utils/focus';
import { describeFailure } from './utils/failures';
import { PAGE_SIZE } from './utils/paging';
import { rovingKeys } from './utils/roving';
import { analysisNotices, checkFileBeforeUpload, claimsNotice } from './utils/uploadChecks';

// Below this width the results are one column, so the editor cannot sit beside the list.
const NARROW_SCREEN = '(max-width: 1023px)';

let errorSerial = 0;

const STOPPED_MESSAGE =
  'Stopped before the analysis finished. Your document is still loaded. Try again when you are ready.';

function App() {
  const [doc, setDoc] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [loading, setLoading] = useState(false);
  // What the page is doing while it waits, when that is more than the analysis itself.
  const [checkingServer, setCheckingServer] = useState(false);
  // { id, message, hint, canRetry, retryAfter }
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('citations');
  // Pasting one citation is the common case, so it is the default door.
  const [mode, setMode] = useState('repair');
  // Where the person had got to in each results tab. Kept here, not in the tab, so switching
  // tabs and coming back does not close the cards they opened or move the preview.
  const [citationsShown, setCitationsShown] = useState(PAGE_SIZE);
  const [claimsShown, setClaimsShown] = useState(PAGE_SIZE);
  const [previewPosition, setPreviewPosition] = useState(null);
  // The file being uploaded, { file, phase }, and what to say about the upload. Kept here, not in
  // the upload box, so it goes on (and can be cancelled) whichever panel is showing.
  const [upload, setUpload] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const [uploadNote, setUploadNote] = useState(null);
  // Spoken, not shown: what a saved edit did.
  const [savedNotice, setSavedNotice] = useState('');

  const narrow = useMediaQuery(NARROW_SCREEN);

  // The backend sleeps on a free tier. Wake it while the visitor is reading,
  // so their first real request is not paying for a cold start.
  useEffect(() => {
    checkHealth();
  }, []);

  // Each upload and each analysis gets a run number. A result that arrives after the person
  // cancelled or reset, or after a newer run began, belongs to a run that no longer exists and
  // must be dropped.
  const runRef = useRef(0);
  const abortRef = useRef(null);
  const uploadRunRef = useRef(0);
  const uploadAbortRef = useRef(null);
  // A ref, not the state: two files dropped in one gesture must not both start.
  const uploadBusyRef = useRef(false);

  // What has been typed into the editor, per citation. Kept here, not in the editor, so it
  // outlives the editor being put away (another results tab, another card, the screen changing
  // width) and is thrown away on Save, on Cancel or Close, and for a new document. A ref, not
  // state: the editor already shows what it holds, and a keystroke should not redraw the page.
  const draftsRef = useRef(new Map());
  const drafts = useMemo(
    () => ({
      get: (id) => draftsRef.current.get(id) ?? null,
      set: (id, draft) => draftsRef.current.set(id, draft),
      clear: (id) => draftsRef.current.delete(id),
      clearAll: () => draftsRef.current.clear(),
    }),
    []
  );

  const startAnalysis = useCallback(async (uploadResult) => {
    const run = ++runRef.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setDoc(uploadResult);
    setAnalysis(null);
    setSelectedCitation(null);
    drafts.clearAll();
    setActiveTab('citations');
    setCitationsShown(PAGE_SIZE);
    setClaimsShown(PAGE_SIZE);
    setPreviewPosition(null);
    setSavedNotice('');
    setLoading(true);
    setError(null);

    const fail = (failure) => setError({ ...failure, id: ++errorSerial });

    try {
      const raw = await analyzeDocument(
        uploadResult.document_id,
        uploadResult.full_text,
        uploadResult.filename,
        { signal: controller.signal }
      );
      if (run !== runRef.current) return;
      const result = normalizeAnalysis(raw);
      if (!result) {
        fail({
          message: `Failed to analyze document: ${UNEXPECTED_FORMAT_MESSAGE}`,
          canRetry: true,
        });
        return;
      }
      setAnalysis(result);
    } catch (err) {
      if (run !== runRef.current) return;
      if (err?.cancelled) {
        // Cancel was pressed. The run is still current, so say what happened rather than
        // leaving an empty page.
        fail({ message: STOPPED_MESSAGE, canRetry: true });
        return;
      }
      if (err?.offline) {
        // No response at all could be a crash, a restart or a dropped connection, and the
        // browser reports them all alike. Ask the server which it was before blaming it.
        setCheckingServer(true);
        let message;
        try {
          message = await explainNetworkFailure('Failed to analyze document', {
            signal: controller.signal,
            sent: err.sent,
          });
        } catch (probeError) {
          if (run !== runRef.current) return;
          message = probeError?.cancelled ? STOPPED_MESSAGE : `Failed to analyze document: ${err.message}`;
        }
        if (run !== runRef.current) return;
        fail({ message, canRetry: true });
      } else {
        fail(describeFailure(err, { prefix: 'Failed to analyze document' }));
      }
      console.error(err);
    } finally {
      if (run === runRef.current) {
        setLoading(false);
        setCheckingServer(false);
      }
    }
  }, [drafts]);

  const handleFiles = useCallback(
    async (files) => {
      const list = Array.from(files || []);
      if (list.length === 0) return;

      if (uploadBusyRef.current) {
        setUploadNote(
          'A file is already uploading, so the one you just added was ignored. ' +
            'Cancel the upload first if you want to use a different file.'
        );
        return;
      }
      const file = list[0];
      setUploadNote(
        list.length > 1
          ? `Only one file is checked at a time, so only ${file.name} was used. ` +
              `The other ${list.length - 1} ${list.length === 2 ? 'file was' : 'files were'} ignored.`
          : null
      );

      // The browser's reported type is NOT checked. Phones send an empty or generic type for
      // Word and PDF files that come from iCloud or Google Drive, and rejecting on it blocked
      // working files before a single byte was sent. The server identifies the format from the
      // file's own contents.
      const problem = checkFileBeforeUpload(file, getLimits());
      if (problem) {
        setUploadError(problem);
        return;
      }

      setUploadError(null);
      const run = ++uploadRunRef.current;
      const controller = new AbortController();
      uploadAbortRef.current = controller;
      uploadBusyRef.current = true;
      setUpload({ file, phase: 'sending' });

      try {
        const result = await uploadDocument(file, { signal: controller.signal });
        if (run !== uploadRunRef.current) return;
        const uploaded = normalizeUpload(result);
        if (!uploaded) {
          setUploadError(UNEXPECTED_FORMAT_MESSAGE);
          return;
        }
        setUploadNote(null);
        setUploadError(null);
        startAnalysis(uploaded);
      } catch (err) {
        if (run !== uploadRunRef.current) return;
        // A response the server sent already says what is wrong (too long, unreadable, empty).
        // No response at all could be a crash, a restart or a dropped connection, and the
        // browser reports them all the same, so ask the server which it was.
        if (err?.offline) {
          setUpload({ file, phase: 'checking' });
          let message;
          try {
            message = await explainNetworkFailure('The upload failed', {
              signal: controller.signal,
              sent: err.sent,
            });
          } catch {
            // Only Cancel stops the probe, and Cancel has made this run stale.
            if (run !== uploadRunRef.current) return;
            message = err.message;
          }
          if (run !== uploadRunRef.current) return;
          setUploadError(message);
        } else {
          setUploadError(err?.message || 'The upload failed.');
        }
      } finally {
        if (run === uploadRunRef.current) {
          uploadBusyRef.current = false;
          setUpload(null);
        }
      }
    },
    [startAnalysis]
  );

  const cancelUpload = useCallback(() => {
    if (!uploadBusyRef.current) return;
    uploadRunRef.current++;
    uploadAbortRef.current?.abort();
    uploadBusyRef.current = false;
    setUpload(null);
    setUploadError(null);
    setUploadNote('Upload cancelled. Choose the file again to start over.');
  }, []);

  // Stop waiting for the analysis, or stop asking whether the server is up, and keep the
  // document so the analysis can be retried without uploading again.
  const cancelAnalysis = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // Where focus goes back to when the editor closes, so a keyboard user is not dropped at the top.
  const returnFocusRef = useRef(null);

  // The citation being edited, for the handlers that close the editor.
  const selectedRef = useRef(null);
  selectedRef.current = selectedCitation;

  // True from the moment a card is chosen until the editor has appeared: the editor takes focus then,
  // and not when it is brought back by returning to the Citations tab.
  const focusEditor = useRef(false);
  useEffect(() => {
    focusEditor.current = false;
  });

  const handleCitationSelect = useCallback((citation, trigger) => {
    focusEditor.current = true;
    returnFocusRef.current = trigger || null;
    setSavedNotice('');
    setSelectedCitation(citation);
  }, []);

  // Cancel, Close, Escape, a tap outside, and Back all end up here: the draft goes with them.
  const closeEditor = useCallback(() => {
    if (selectedRef.current) drafts.clear(selectedRef.current.id);
    setSelectedCitation(null);
  }, [drafts]);

  useEffect(() => {
    if (selectedCitation || !returnFocusRef.current) return;
    const trigger = returnFocusRef.current;
    returnFocusRef.current = null;
    if (trigger.isConnected) trigger.focus();
  }, [selectedCitation]);

  const handleCitationUpdate = useCallback(
    (updated) => {
      drafts.clear(updated.id);
      if (analysis) {
        const citations = analysis.analysis.citations;
        const index = citations.findIndex((c) => c.id === updated.id);
        if (index >= 0) {
          const original = citations[index];
          const changed = editedFieldsDiffer(original, updated);
          const next = citations.slice();
          next[index] = changed || original.edited ? { ...updated, edited: true } : updated;
          setAnalysis({ ...analysis, analysis: { ...analysis.analysis, citations: next } });
          setSavedNotice(changed ? `Saved changes to citation ${index + 1}.` : 'No changes to save.');
        }
      }
      setSelectedCitation(null);
    },
    [analysis, drafts]
  );

  const handleLookup = useCallback((citation, options) => lookupCitation(citation, options), []);

  // After starting over, the button that was pressed is gone; focus goes to the first thing on the
  // landing page instead of falling to the top of the document.
  const focusLanding = useRef(false);

  const handleReset = useCallback(() => {
    focusLanding.current = true;
    runRef.current++;
    abortRef.current?.abort();
    setLoading(false);
    setCheckingServer(false);
    setDoc(null);
    setAnalysis(null);
    setSelectedCitation(null);
    drafts.clearAll();
    setError(null);
    setSavedNotice('');
  }, [drafts]);

  const resetButton = useRef(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const editedCount = analysis ? analysis.analysis.citations.filter((c) => c.edited).length : 0;
  // Starting over throws the results away, edited citations included. With edits, ask first.
  const requestReset = () => {
    if (editedCount > 0) setConfirmingReset(true);
    else handleReset();
  };
  const keepWorking = () => {
    setConfirmingReset(false);
    // The dialog is leaving; the button that opened it is where the person was.
    window.setTimeout(() => resetButton.current?.focus(), 0);
  };
  const discardAndStartOver = () => {
    setConfirmingReset(false);
    handleReset();
  };

  const landingFocus = mode === 'repair' ? 'mode-repair' : 'mode-upload';
  useEffect(() => {
    if (doc || !focusLanding.current) return;
    focusLanding.current = false;
    window.document.getElementById(landingFocus)?.focus();
  }, [doc, landingFocus]);

  // On a phone the editor is a sheet over the page; the page behind should not scroll with it.
  const sheetOpen = narrow && Boolean(selectedCitation) && activeTab === 'citations';
  useEffect(() => {
    if (!sheetOpen) return undefined;
    const previous = window.document.body.style.overflow;
    window.document.body.style.overflow = 'hidden';
    return () => {
      window.document.body.style.overflow = previous;
    };
  }, [sheetOpen]);

  // Back closes the sheet. Opening it adds one history entry, so Back (the Android button, an iOS
  // swipe) takes that entry away and closes the sheet, where it used to leave the page and lose
  // the results. When the sheet is closed any other way (Close, Cancel, Save, a tap outside,
  // Escape, another tab, a wider screen) the entry is taken away again, so nothing piles up.
  //
  // `history.back()` is answered later by a popstate. `ownPops` counts the ones this page asked
  // for, so they are not mistaken for the person pressing Back, and a sheet that opens while one
  // is on its way gets its entry when that popstate arrives, not before: a push made in between
  // would be walked back over by it.
  const sheetEntry = useRef(false); // the sheet's entry is on the history now
  const sheetWanted = useRef(false); // the sheet is open now
  const ownPops = useRef(0);
  const unmounting = useRef(false);

  const addSheetEntry = () => {
    window.history.pushState({ sheet: true }, '');
    sheetEntry.current = true;
  };

  useEffect(() => {
    unmounting.current = false;
    const onPopState = () => {
      if (ownPops.current > 0) {
        ownPops.current -= 1;
        if (ownPops.current === 0 && sheetWanted.current && !sheetEntry.current) addSheetEntry();
        return;
      }
      if (!sheetEntry.current) return;
      // The person pressed Back: the entry is already gone.
      sheetEntry.current = false;
      closeEditor();
    };
    window.addEventListener('popstate', onPopState);
    return () => {
      unmounting.current = true;
      window.removeEventListener('popstate', onPopState);
    };
  }, [closeEditor]);

  useEffect(() => {
    if (!sheetOpen) return undefined;
    sheetWanted.current = true;
    if (ownPops.current === 0) addSheetEntry();
    return () => {
      sheetWanted.current = false;
      if (!sheetEntry.current) return; // Back already took it, or it was never added
      sheetEntry.current = false;
      if (unmounting.current) return;
      if (window.history.state?.sheet) {
        ownPops.current += 1;
        window.history.back();
      }
    };
  }, [sheetOpen]);

  const uploading = Boolean(upload);
  const editorOpen = Boolean(selectedCitation && analysis);
  const progressNotice = loading
    ? checkingServer
      ? 'Checking whether the server is still running.'
      : 'Analyzing citations.'
    : analysis && doc
      ? `Analysis finished. ${analysis.stats.total_citations} citation${analysis.stats.total_citations === 1 ? '' : 's'} found.`
      : '';

  // The page that was being worked on is gone when the analysis finishes or fails (the box the file
  // was chosen in, the Cancel that was pressed). Focus goes to what has just appeared, when it was lost.
  const summaryHeading = useRef(null);
  const errorBox = useRef(null);
  const hadResults = useRef(false);
  useEffect(() => {
    if (analysis && doc && !loading) {
      if (!hadResults.current) {
        hadResults.current = true;
        focusIfLost(summaryHeading.current);
      }
    } else if (!analysis) {
      hadResults.current = false;
    }
  }, [analysis, doc, loading]);
  useEffect(() => {
    if (error) focusIfLost(errorBox.current);
  }, [error]);

  return (
    <div className="min-h-screen bg-gray-50 overflow-x-clip">
      {/* Header */}
      <header className="bg-blue-900 text-white py-6 px-4 shadow-lg">
        {/* The title and the button share a row when there is room, and the button goes under the
            title when there is not (a narrow phone, or text enlarged to 200%). */}
        <div className="max-w-7xl mx-auto flex flex-wrap justify-between items-center gap-3">
          <div className="min-w-0 flex-1 basis-[11rem]">
            <h1 className="text-2xl font-bold [overflow-wrap:anywhere]">Bluebook Citation Generator</h1>
            <p className="text-blue-100 mt-1 text-sm">
              Automated citation formatting per Bluebook 21st Edition
            </p>
          </div>
          {doc && (
            <button
              ref={resetButton}
              onClick={requestReset}
              className="flex-shrink-0 max-w-full min-h-[44px] px-3 sm:px-4 py-2 bg-blue-700 hover:bg-blue-600 rounded-lg text-sm transition-colors"
            >
              Upload New Document
            </button>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto py-8 px-4">
        {/* Spoken, not shown: the result of saving an edit. */}
        <p className="sr-only" role="status">{savedNotice}</p>
        {/* Spoken, not shown: how the analysis is going. In the page before it has anything to say. */}
        <p className="sr-only" role="status" data-testid="progress-status">{progressNotice}</p>

        {/* Error Display */}
        {error && (
          <div ref={errorBox} tabIndex={-1} role="alert" className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
            <div className="flex items-start">
              <svg className="w-5 h-5 text-red-500 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              <div className="min-w-0">
                <p dir="auto" className="text-red-800 [overflow-wrap:anywhere]">{error.message}</p>
                {error.hint && <p dir="auto" className="mt-1 text-sm text-red-800 [overflow-wrap:anywhere]">{error.hint}</p>}
              </div>
            </div>
          </div>
        )}

        {/* After a failed analysis the upload is still in memory, so offer a retry instead of a
            re-upload, unless sending the same thing again cannot work. */}
        {error?.canRetry && doc && !analysis && !loading && (
          <RetryButton
            key={error.id}
            waitSeconds={error.retryAfter}
            onRetry={() => startAnalysis(doc)}
          />
        )}

        {/* The page and the server do not agree, so sending it again changes nothing: the page
            has to be loaded again. That starts from nothing, and the error says so. */}
        {error?.reload && !loading && (
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mb-6 min-h-[44px] px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium"
          >
            Reload page
          </button>
        )}

        {/* Landing: repair a single citation, or analyze a whole document. Both panels stay
            mounted, hidden when not in use, so what was typed or chosen in one survives a trip
            to the other and back, and a trip through the results. */}
        <div hidden={Boolean(doc || loading)}>
          <div className="flex flex-wrap gap-2 mb-5" role="tablist" aria-label="Choose a mode" onKeyDown={rovingKeys()}>
            <ModeButton
              id="mode-repair"
              controls="panel-repair"
              active={mode === 'repair'}
              disabled={uploading}
              onClick={() => setMode('repair')}
            >
              Fix a citation
            </ModeButton>
            <ModeButton
              id="mode-upload"
              controls="panel-upload"
              active={mode === 'upload'}
              onClick={() => setMode('upload')}
            >
              Check a document
            </ModeButton>
          </div>
          <div role="tabpanel" id="panel-repair" aria-labelledby="mode-repair" hidden={mode !== 'repair'}>
            <CitationRepair />
          </div>

          <div role="tabpanel" id="panel-upload" aria-labelledby="mode-upload" hidden={mode !== 'upload'}>
            <div className="bg-white rounded-lg shadow-lg p-5 sm:p-8">
              <h2 className="text-xl font-semibold mb-4">Check a whole document</h2>
              <p className="text-gray-600 mb-6">
                Upload a legal document (PDF, DOCX, or TXT) to analyze and format citations
                according to Bluebook 21st Edition rules.
              </p>
              <FileUpload
                uploading={upload}
                error={uploadError}
                notice={uploadNote}
                onFiles={handleFiles}
                onCancel={cancelUpload}
              />

              <div className="mt-8 border-t pt-6">
                <h3 className="font-medium text-gray-700 mb-3">Features</h3>
                <ul className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm text-gray-600">
                  <li className="flex items-start">
                    <svg className="w-5 h-5 text-green-500 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    <span>Complete incomplete citations with database lookups</span>
                  </li>
                  <li className="flex items-start">
                    <svg className="w-5 h-5 text-green-500 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    <span>Context-aware Id. and supra suggestions</span>
                  </li>
                  <li className="flex items-start">
                    <svg className="w-5 h-5 text-green-500 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                    <span>Detect claims that need citations</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="bg-white rounded-lg shadow-lg p-6 sm:p-12 text-center">
            <div className="animate-spin motion-reduce:animate-none rounded-full h-12 w-12 border-4 border-blue-200 border-t-blue-600 mx-auto"></div>
            <p className="mt-4 text-gray-700">
              {checkingServer ? 'Checking whether the server is still running...' : 'Analyzing citations...'}
            </p>
            <p className="mt-2 text-sm text-gray-600">
              {checkingServer
                ? 'The request did not finish. This can take up to half a minute.'
                : 'A long document can take up to a minute. Looking up incomplete citations is the slow part.'}
            </p>
            <button
              type="button"
              onClick={cancelAnalysis}
              className="mt-4 min-h-[44px] px-5 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-800 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        )}

        {/* Analysis Results */}
        {analysis && doc && !loading && (
          <div className="space-y-6">
            {/* Stats Overview */}
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 mb-4">
                <h2 ref={summaryHeading} tabIndex={-1} className="text-lg font-semibold focus:outline-none">Analysis Summary</h2>
                <span dir="auto" className="min-w-0 text-sm text-gray-600 [overflow-wrap:anywhere]">{doc.filename}</span>
              </div>
              {(doc.footnote_count > 0 || doc.endnote_count > 0) && (
                <p className="text-xs text-gray-600 mb-4">
                  Read {doc.footnote_count} footnote{doc.footnote_count === 1 ? '' : 's'}
                  {doc.endnote_count > 0
                    ? ` and ${doc.endnote_count} endnote${doc.endnote_count === 1 ? '' : 's'}`
                    : ''}
                  {' '}from the Word file.
                </p>
              )}
              {analysisNotices(analysis).map((notice) => (
                <p key={notice} dir="auto" className="text-xs text-gray-600 mb-3 [overflow-wrap:anywhere]">{notice}</p>
              ))}
              {doc.warnings?.map((w, i) => (
                <p key={`${i}-${w}`} dir="auto" className="text-xs text-amber-800 mb-2 [overflow-wrap:anywhere]">{w}</p>
              ))}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <StatCard label="Total Citations" value={analysis.stats.total_citations} color="blue" />
                <StatCard label="Complete" value={analysis.stats.complete} color="green" />
                <StatCard label="Incomplete" value={analysis.stats.incomplete} color="yellow" />
                <StatCard label="Needs Review" value={analysis.stats.needs_verification} color="orange" />
                <StatCard label="Unsourced Claims" value={analysis.stats.unsourced_claims} color="red" />
              </div>
            </div>

            {/* Tabs */}
            <div className="bg-white rounded-lg shadow">
              <div className="border-b">
                <nav className="flex -mb-px" role="tablist" aria-label="Results" onKeyDown={rovingKeys()}>
                  <TabButton
                    id="citations"
                    active={activeTab === 'citations'}
                    onClick={() => setActiveTab('citations')}
                    count={analysis.stats.total_citations}
                  >
                    Citations
                  </TabButton>
                  <TabButton
                    id="unsourced"
                    active={activeTab === 'unsourced'}
                    onClick={() => setActiveTab('unsourced')}
                    count={analysis.stats.unsourced_claims}
                  >
                    Unsourced Claims
                  </TabButton>
                  <TabButton
                    id="preview"
                    active={activeTab === 'preview'}
                    onClick={() => setActiveTab('preview')}
                  >
                    Document Preview
                  </TabButton>
                </nav>
              </div>

              <div className="p-4" role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
                {activeTab === 'citations' && (
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 min-w-0">
                      <CitationList
                        citations={analysis.analysis.citations}
                        shortFormSuggestions={analysis.short_form_suggestions}
                        onSelect={handleCitationSelect}
                        selectedId={selectedCitation?.id}
                        shown={citationsShown}
                        onShownChange={setCitationsShown}
                      />
                    </div>
                    {/* Beside the list the editor stays in view while the list scrolls, and scrolls inside
                        itself if it is taller than the screen: opened from far down a long list it
                        would otherwise be thousands of pixels above. */}
                    <div className="min-w-0 lg:sticky lg:top-4 lg:self-start lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
                      {/* The backdrop is a sibling, and the editor is ONE element whether it is a
                          sheet or a panel, so the screen changing width never remounts it. */}
                      {sheetOpen && <SheetBackdrop onClose={closeEditor} />}
                      {editorOpen ? (
                        <EditorShell sheet={narrow} onClose={closeEditor}>
                          <CitationEditor
                            key={selectedCitation.id}
                            citation={selectedCitation}
                            suggestion={analysis.short_form_suggestions.find(
                              (s) => s.citation_id === selectedCitation.id
                            )}
                            onSave={handleCitationUpdate}
                            onLookup={handleLookup}
                            onCancel={closeEditor}
                            focusOnOpen={focusEditor.current}
                            draft={drafts.get(selectedCitation.id)}
                            onDraftChange={drafts.set}
                          />
                        </EditorShell>
                      ) : (
                        <div className="hidden lg:block bg-gray-50 rounded-lg p-6 text-center text-gray-600">
                          <svg className="w-12 h-12 mx-auto mb-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                          </svg>
                          <p>Select a citation to view details and edit</p>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === 'unsourced' && (
                  <SourceSuggestions
                    claims={analysis.analysis.unsourced_claims}
                    notice={claimsNotice(analysis.stats)}
                    shown={claimsShown}
                    onShownChange={setClaimsShown}
                  />
                )}

                {activeTab === 'preview' && (
                  <DocumentPreview
                    text={doc.full_text}
                    citations={analysis.analysis.citations}
                    unsourcedClaims={analysis.analysis.unsourced_claims}
                    position={previewPosition}
                    onPositionChange={setPreviewPosition}
                  />
                )}
              </div>
            </div>
          </div>
        )}
      </main>

      {confirmingReset && (
        <ConfirmDialog
          title="Discard your edits?"
          confirmLabel="Start over and discard"
          cancelLabel="Keep working"
          onConfirm={discardAndStartOver}
          onCancel={keepWorking}
        >
          <p>
            {editedCount === 1 ? '1 citation has' : `${editedCount} citations have`} been edited here.
            Starting over removes the results and {editedCount === 1 ? 'that edit' : 'those edits'}.
            To keep {editedCount === 1 ? 'it' : 'them'}, choose Keep working, then use the Copy buttons on the
            Citations tab.
          </p>
        </ConfirmDialog>
      )}

      {/* Footer */}
      <footer className="bg-gray-800 text-gray-300 py-6 px-4 mt-12">
        <div className="max-w-7xl mx-auto text-center text-sm">
          <p>Bluebook Citation Generator - Using Bluebook 21st Edition Rules</p>
          <p className="mt-2 text-gray-400">
            Note: Always verify citations before submission. This tool provides suggestions only.
          </p>
        </div>
      </footer>
    </div>
  );
}

/** The dim layer behind the sheet. A tap on it closes the sheet. */
function SheetBackdrop({ onClose }) {
  return (
    <div
      data-testid="sheet-backdrop"
      className="fixed inset-0 z-40 bg-black/40"
      onClick={onClose}
      aria-hidden="true"
    />
  );
}

/**
 * The element the editor sits in. On a phone (`sheet`) it is a sheet rising over the list.
 * Tapping a card used to open the editor in a column that, on one screen, sat 20,000 px below
 * the list, so nothing seemed to happen. The list stays where it is; Close, Escape, a tap
 * outside, or Back goes back to it.
 *
 * It is ONE element in both cases, and only its role, label and classes change: the editor
 * inside is not remounted when the window crosses the width where the sheet becomes a panel (a
 * tablet turned on its side), so what was typed in it is not lost.
 */
function EditorShell({ sheet, onClose, children }) {
  const shell = useRef(null);

  useEffect(() => {
    if (sheet) shell.current?.focus();
  }, [sheet]);

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    // Beside the list the page is not covered, so Tab may leave the editor.
    if (!sheet || event.key !== 'Tab' || !shell.current) return;
    // Keep Tab inside the sheet; the page behind it is covered.
    const stops = Array.from(
      shell.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter((el) => !el.disabled);
    if (stops.length === 0) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    const active = window.document.activeElement;
    if (event.shiftKey && (active === first || active === shell.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const sheetProps = sheet
    ? {
        role: 'dialog',
        'aria-modal': 'true',
        'aria-label': 'Edit citation',
        tabIndex: -1,
        className:
          'editor-sheet fixed inset-x-0 bottom-0 z-50 max-w-full min-w-0 overflow-y-auto overscroll-contain rounded-t-2xl bg-white shadow-2xl focus:outline-none',
      }
    : {};

  return (
    <div ref={shell} onKeyDown={handleKeyDown} {...sheetProps}>
      {children}
    </div>
  );
}

function StatCard({ label, value, color }) {
  const colors = {
    blue: 'bg-blue-50 text-blue-900',
    green: 'bg-green-50 text-green-700',
    yellow: 'bg-yellow-50 text-yellow-700',
    orange: 'bg-orange-50 text-orange-700',
    red: 'bg-red-50 text-red-700',
  };

  return (
    <div className={`${colors[color]} p-4 rounded-lg text-center`}>
      <div className="text-3xl font-bold">{value}</div>
      <div className="text-sm">{label}</div>
    </div>
  );
}

function ModeButton({ children, id, controls, active, disabled = false, onClick }) {
  return (
    <button
      type="button"
      role="tab"
      id={id}
      aria-controls={controls}
      aria-selected={active}
      // The selected tab is the one stop in the Tab order; the arrow keys move between them.
      tabIndex={active ? 0 : -1}
      disabled={disabled}
      onClick={onClick}
      className={`min-h-[44px] px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-600 ${
        active
          ? 'bg-blue-600 text-white shadow'
          : 'bg-white text-gray-700 border border-gray-200 hover:bg-gray-50'
      }`}
    >
      {children}
    </button>
  );
}

function TabButton({ children, id, active, onClick, count }) {
  // Three tabs share the row on a phone, so a label may wrap and the count sits under it.
  return (
    <button
      type="button"
      role="tab"
      id={`tab-${id}`}
      aria-selected={active}
      aria-controls={`panel-${id}`}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={`flex-1 sm:flex-none min-h-[48px] min-w-0 px-1 sm:px-6 py-2 sm:py-3 flex flex-col sm:flex-row items-center justify-center gap-1 text-xs sm:text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-blue-600 text-blue-700'
          : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300'
      }`}
    >
      <span className="min-w-0 [overflow-wrap:anywhere]">{children}</span>
      {count !== undefined && (
        <span className={`sm:ml-2 px-2 py-0.5 rounded-full text-xs ${
          active ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-700'
        }`}>
          {count}
        </span>
      )}
    </button>
  );
}

export default App;
