const API_URL = import.meta.env.VITE_API_URL || '';

async function handleResponse(response) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch(`${API_URL}/api/upload`, {
    method: 'POST',
    body: formData,
  });
  
  return handleResponse(response);
}

export async function analyzeDocument(documentId, text, filename) {
  const response = await fetch(`${API_URL}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_id: documentId, text, filename }),
  });
  
  return handleResponse(response);
}

export async function formatCitation(citation) {
  const response = await fetch(`${API_URL}/api/format`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(citation),
  });
  
  return handleResponse(response);
}

export async function lookupCitation(citation) {
  const response = await fetch(`${API_URL}/api/lookup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(citation),
  });
  
  return handleResponse(response);
}

export async function lookupCase(parties, citation) {
  const response = await fetch(`${API_URL}/api/lookup/case`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parties, citation }),
  });

  return handleResponse(response);
}

export async function completeFromText(text) {
  const response = await fetch(`${API_URL}/api/complete-from-text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });

  return handleResponse(response);
}

export async function findSources(text, maxSuggestions = 3) {
  const response = await fetch(`${API_URL}/api/find-sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, max_suggestions: maxSuggestions }),
  });

  return handleResponse(response);
}

export async function analyzeComprehensive(documentId, text, filename, findSources = true) {
  const response = await fetch(`${API_URL}/api/analyze-comprehensive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      document_id: documentId,
      text,
      filename,
      find_sources: findSources
    }),
  });

  return handleResponse(response);
}

export async function searchCitations(query, searchType = 'case') {
  const response = await fetch(`${API_URL}/api/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, search_type: searchType }),
  });

  return handleResponse(response);
}
