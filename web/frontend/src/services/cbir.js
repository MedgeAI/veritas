/**
 * CBIR (Content-Based Image Retrieval) API client
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL.replace(/\/$/, '')}${path}`;
}

async function request(path, options = {}) {
  const method = options.method || 'GET';
  const headers = {
    ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers || {}),
  };

  const response = await fetch(buildUrl(path), {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();

  if (!response.ok) {
    throw new Error(payload?.detail || payload?.error || payload || `request failed: ${response.status}`);
  }

  return payload;
}

/**
 * Search for similar panels by panel ID
 * @param {string} panelId - Query panel ID
 * @param {Object} options - Search options
 * @param {string} [options.caseId] - Optional case ID to restrict search scope
 * @param {number} [options.topK=20] - Maximum results to return
 * @param {number} [options.threshold=0.85] - Minimum similarity threshold
 * @param {string} [options.label] - Optional label filter
 * @param {AbortSignal} [options.signal] - Abort signal
 */
export async function searchSimilarPanels(panelId, { caseId, topK = 20, threshold = 0.85, label, signal } = {}) {
  const body = {
    panel_id: panelId,
    top_k: topK,
    threshold: threshold,
  };
  if (caseId) body.case_id = caseId;
  if (label) body.label = label;

  return request('/api/cbir/search', {
    method: 'POST',
    body,
    signal,
  });
}

/**
 * Upload an image and search for similar panels (NOT YET IMPLEMENTED IN BACKEND)
 * This endpoint is planned but not yet available.
 * @param {File} imageFile - Image file to upload
 * @param {Object} options - Search options
 * @param {number} [options.topK=20] - Maximum results
 * @param {number} [options.threshold=0.85] - Minimum similarity threshold
 */
export async function searchByImageUpload(_imageFile, _options = {}) {
  // TODO: Backend endpoint not yet implemented
  // const formData = new FormData();
  // formData.append('file', imageFile);
  // formData.append('top_k', String(topK));
  // formData.append('threshold', String(threshold));
  //
  // const response = await fetch(buildUrl('/api/cbir/search/upload'), {
  //   method: 'POST',
  //   body: formData,
  // });
  // return response.json();

  throw new Error('Image upload search is not yet implemented. Backend endpoint /api/cbir/search/upload is pending.');
}
