import React, { useState, useEffect } from 'react';

export default function CitationEditor({ citation, suggestion, onSave, onLookup, onCancel }) {
  const [formData, setFormData] = useState({});
  const [lookupResults, setLookupResults] = useState(null);
  const [lookingUp, setLookingUp] = useState(false);

  useEffect(() => {
    setFormData({
      parties: citation.parties?.join(' v. ') || '',
      volume: citation.volume || '',
      reporter: citation.reporter || '',
      page: citation.page || '',
      pincite: citation.pincite || '',
      court: citation.court || '',
      year: citation.year || '',
      author: citation.author || '',
      title: citation.title || '',
      journal: citation.journal || '',
      section: citation.section || '',
      title_number: citation.title_number || '',
      url: citation.url || '',
    });
    setLookupResults(citation.lookup_results);
  }, [citation]);

  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleLookup = async () => {
    setLookingUp(true);
    try {
      const results = await onLookup(citation);
      setLookupResults(results);
      
      // Auto-fill from results
      if (results.found && results.data) {
        const data = results.data;
        setFormData(prev => ({
          ...prev,
          parties: data.case_name || prev.parties,
          court: data.court || prev.court,
          year: data.date_filed?.slice(0, 4) || prev.year,
          author: data.author || prev.author,
          title: data.title || prev.title,
          volume: data.volume || prev.volume,
          page: data.page || prev.page,
        }));
      }
    } catch (err) {
      console.error('Lookup failed:', err);
    } finally {
      setLookingUp(false);
    }
  };

  const handleSave = () => {
    const updated = { ...citation };
    
    if (formData.parties) {
      updated.parties = formData.parties.split(' v. ').map(p => p.trim());
    }
    if (formData.volume) updated.volume = formData.volume;
    if (formData.reporter) updated.reporter = formData.reporter;
    if (formData.page) updated.page = formData.page;
    if (formData.pincite) updated.pincite = formData.pincite;
    if (formData.court) updated.court = formData.court;
    if (formData.year) updated.year = parseInt(formData.year) || null;
    if (formData.author) updated.author = formData.author;
    if (formData.title) updated.title = formData.title;
    if (formData.journal) updated.journal = formData.journal;
    if (formData.section) updated.section = formData.section;
    if (formData.title_number) updated.title_number = formData.title_number;
    if (formData.url) updated.url = formData.url;
    
    onSave(updated);
  };

  const renderFields = () => {
    switch (citation.type) {
      case 'case':
        return (
          <>
            <Field label="Parties" value={formData.parties} onChange={v => handleChange('parties', v)} placeholder="Plaintiff v. Defendant" />
            <div className="grid grid-cols-3 gap-3">
              <Field label="Volume" value={formData.volume} onChange={v => handleChange('volume', v)} />
              <Field label="Reporter" value={formData.reporter} onChange={v => handleChange('reporter', v)} />
              <Field label="Page" value={formData.page} onChange={v => handleChange('page', v)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Court" value={formData.court} onChange={v => handleChange('court', v)} />
              <Field label="Year" value={formData.year} onChange={v => handleChange('year', v)} type="number" />
            </div>
            <Field label="Pincite" value={formData.pincite} onChange={v => handleChange('pincite', v)} placeholder="e.g., 123-25" />
          </>
        );
      
      case 'statute':
      case 'regulation':
        return (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Title" value={formData.title_number} onChange={v => handleChange('title_number', v)} />
              <Field label="Section" value={formData.section} onChange={v => handleChange('section', v)} />
            </div>
            <Field label="Year" value={formData.year} onChange={v => handleChange('year', v)} type="number" />
          </>
        );
      
      case 'law_review':
        return (
          <>
            <Field label="Author" value={formData.author} onChange={v => handleChange('author', v)} />
            <Field label="Title" value={formData.title} onChange={v => handleChange('title', v)} />
            <Field label="Journal" value={formData.journal} onChange={v => handleChange('journal', v)} />
            <div className="grid grid-cols-3 gap-3">
              <Field label="Volume" value={formData.volume} onChange={v => handleChange('volume', v)} />
              <Field label="Page" value={formData.page} onChange={v => handleChange('page', v)} />
              <Field label="Year" value={formData.year} onChange={v => handleChange('year', v)} type="number" />
            </div>
          </>
        );
      
      case 'book':
        return (
          <>
            <Field label="Author" value={formData.author} onChange={v => handleChange('author', v)} />
            <Field label="Title" value={formData.title} onChange={v => handleChange('title', v)} />
            <Field label="Year" value={formData.year} onChange={v => handleChange('year', v)} type="number" />
          </>
        );
      
      case 'website':
        return (
          <>
            <Field label="Author" value={formData.author} onChange={v => handleChange('author', v)} />
            <Field label="Title" value={formData.title} onChange={v => handleChange('title', v)} />
            <Field label="URL" value={formData.url} onChange={v => handleChange('url', v)} />
          </>
        );
      
      default:
        return (
          <p className="text-sm text-gray-500">
            No editable fields for this citation type.
          </p>
        );
    }
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg">
      <div className="p-4 border-b bg-gray-50">
        <h3 className="font-medium">Edit Citation</h3>
        <p className="text-xs text-gray-500 mt-1">{citation.type}</p>
      </div>
      
      <div className="p-4 space-y-4">
        {/* Original */}
        <div className="p-3 bg-gray-50 rounded text-sm font-mono text-gray-600">
          {citation.raw_text}
        </div>

        {/* Lookup button */}
        <button
          onClick={handleLookup}
          disabled={lookingUp}
          className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
        >
          {lookingUp ? 'Looking up...' : 'Look Up in Database'}
        </button>

        {/* Lookup results */}
        {lookupResults?.found && (
          <div className="p-3 bg-green-50 border border-green-100 rounded-lg">
            <p className="text-xs font-medium text-green-700 mb-2">
              Found in {lookupResults.source}
            </p>
            {lookupResults.data?.absolute_url && (
              <a
                href={lookupResults.data.absolute_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-600 hover:underline"
              >
                View source →
              </a>
            )}
            {lookupResults.data?.url && !lookupResults.data?.absolute_url && (
              <a
                href={lookupResults.data.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-600 hover:underline"
              >
                View source →
              </a>
            )}
          </div>
        )}

        {/* Form fields */}
        <div className="space-y-3">
          {renderFields()}
        </div>

        {/* Suggestion */}
        {suggestion?.suggested_form && (
          <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
            <p className="text-xs font-medium text-blue-700 mb-1">Formatted suggestion:</p>
            <p className="text-sm font-mono text-blue-800">{suggestion.suggested_form}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium transition-colors"
          >
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = 'text' }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
      />
    </div>
  );
}
