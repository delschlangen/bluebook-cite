import React, { useState, useCallback } from 'react';
import FileUpload from './components/FileUpload';
import CitationList from './components/CitationList';
import CitationEditor from './components/CitationEditor';
import SourceSuggestions from './components/SourceSuggestions';
import DocumentPreview from './components/DocumentPreview';
import { analyzeDocument, lookupCitation } from './services/api';

function App() {
  const [document, setDocument] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('citations');

  const handleUpload = useCallback(async (uploadResult) => {
    setDocument(uploadResult);
    setLoading(true);
    setError(null);
    
    try {
      const analysisResult = await analyzeDocument(
        uploadResult.document_id,
        uploadResult.full_text,
        uploadResult.filename
      );
      setAnalysis(analysisResult);
    } catch (err) {
      setError(`Failed to analyze document: ${err.message}`);
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleCitationSelect = useCallback((citation) => {
    setSelectedCitation(citation);
  }, []);

  const handleCitationUpdate = useCallback((updatedCitation) => {
    if (analysis) {
      const updatedCitations = analysis.analysis.citations.map(c =>
        c.id === updatedCitation.id ? updatedCitation : c
      );
      setAnalysis({
        ...analysis,
        analysis: {
          ...analysis.analysis,
          citations: updatedCitations
        }
      });
    }
    setSelectedCitation(null);
  }, [analysis]);

  const handleLookup = useCallback(async (citation) => {
    return await lookupCitation(citation);
  }, []);

  const handleReset = useCallback(() => {
    setDocument(null);
    setAnalysis(null);
    setSelectedCitation(null);
    setError(null);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-blue-900 text-white py-6 px-4 shadow-lg">
        <div className="max-w-7xl mx-auto flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold">Bluebook Citation Generator</h1>
            <p className="text-blue-200 mt-1 text-sm">
              Automated citation formatting per Bluebook 21st Edition
            </p>
          </div>
          {document && (
            <button
              onClick={handleReset}
              className="px-4 py-2 bg-blue-700 hover:bg-blue-600 rounded-lg text-sm transition-colors"
            >
              Upload New Document
            </button>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto py-8 px-4">
        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <div className="flex items-center">
              <svg className="w-5 h-5 text-red-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              <p className="text-red-800">{error}</p>
            </div>
          </div>
        )}

        {/* Upload Section */}
        {!document && !loading && (
          <div className="bg-white rounded-lg shadow-lg p-8">
            <h2 className="text-xl font-semibold mb-4">Upload Your Document</h2>
            <p className="text-gray-600 mb-6">
              Upload a legal document (PDF, DOCX, or TXT) to analyze and format citations
              according to Bluebook 21st Edition rules.
            </p>
            <FileUpload onUpload={handleUpload} />
            
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
        )}

        {/* Loading State */}
        {loading && (
          <div className="bg-white rounded-lg shadow-lg p-12 text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-200 border-t-blue-600 mx-auto"></div>
            <p className="mt-4 text-gray-600">Analyzing citations...</p>
            <p className="mt-2 text-sm text-gray-400">This may take a moment for longer documents</p>
          </div>
        )}

        {/* Analysis Results */}
        {analysis && !loading && (
          <div className="space-y-6">
            {/* Stats Overview */}
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold">Analysis Summary</h2>
                <span className="text-sm text-gray-500">{document.filename}</span>
              </div>
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
                <nav className="flex -mb-px">
                  <TabButton
                    active={activeTab === 'citations'}
                    onClick={() => setActiveTab('citations')}
                    count={analysis.stats.total_citations}
                  >
                    Citations
                  </TabButton>
                  <TabButton
                    active={activeTab === 'unsourced'}
                    onClick={() => setActiveTab('unsourced')}
                    count={analysis.stats.unsourced_claims}
                  >
                    Unsourced Claims
                  </TabButton>
                  <TabButton
                    active={activeTab === 'preview'}
                    onClick={() => setActiveTab('preview')}
                  >
                    Document Preview
                  </TabButton>
                </nav>
              </div>

              <div className="p-4">
                {activeTab === 'citations' && (
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2">
                      <CitationList
                        citations={analysis.analysis.citations}
                        shortFormSuggestions={analysis.short_form_suggestions}
                        onSelect={handleCitationSelect}
                        selectedId={selectedCitation?.id}
                      />
                    </div>
                    <div>
                      {selectedCitation ? (
                        <CitationEditor
                          citation={selectedCitation}
                          suggestion={analysis.short_form_suggestions.find(
                            s => s.citation_id === selectedCitation.id
                          )}
                          onSave={handleCitationUpdate}
                          onLookup={handleLookup}
                          onCancel={() => setSelectedCitation(null)}
                        />
                      ) : (
                        <div className="bg-gray-50 rounded-lg p-6 text-center text-gray-500">
                          <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                          </svg>
                          <p>Select a citation to view details and edit</p>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === 'unsourced' && (
                  <SourceSuggestions claims={analysis.analysis.unsourced_claims} />
                )}

                {activeTab === 'preview' && (
                  <DocumentPreview
                    text={document.full_text}
                    citations={analysis.analysis.citations}
                    unsourcedClaims={analysis.analysis.unsourced_claims}
                  />
                )}
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="bg-gray-800 text-gray-400 py-6 px-4 mt-12">
        <div className="max-w-7xl mx-auto text-center text-sm">
          <p>Bluebook Citation Generator - Using Bluebook 21st Edition Rules</p>
          <p className="mt-2 text-gray-500">
            Note: Always verify citations before submission. This tool provides suggestions only.
          </p>
        </div>
      </footer>
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
      <div className="text-sm opacity-80">{label}</div>
    </div>
  );
}

function TabButton({ children, active, onClick, count }) {
  return (
    <button
      onClick={onClick}
      className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-blue-600 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
      }`}
    >
      {children}
      {count !== undefined && (
        <span className={`ml-2 px-2 py-0.5 rounded-full text-xs ${
          active ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-600'
        }`}>
          {count}
        </span>
      )}
    </button>
  );
}

export default App;
