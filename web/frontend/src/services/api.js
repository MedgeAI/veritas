const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL.replace(/\/$/, '')}${path}`;
}

function requestErrorMessage(payload) {
  if (typeof payload === 'string') {
    return payload || 'request failed';
  }

  const detail = payload?.detail ?? payload?.error;
  if (typeof detail === 'string') {
    return detail;
  }

  if (detail && typeof detail === 'object') {
    const code = detail.error || payload?.error;
    const message = detail.detail || detail.message || payload?.message;
    if (code && message) return `${code}: ${message}`;
    if (code) return String(code);
    if (message) return String(message);
    return JSON.stringify(detail);
  }

  return payload?.message || 'request failed';
}

async function request(path, options = {}) {
  const response = await fetch(buildUrl(path), {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();

  if (!response.ok) {
    throw new Error(requestErrorMessage(payload));
  }

  return payload;
}

export async function listCases() {
  return request('/api/cases');
}

export async function checkHealth() {
  return request('/api/health');
}

export async function createCase(payload) {
  return request('/api/cases', {
    method: 'POST',
    body: payload,
  });
}

export async function uploadInput(caseId, file) {
  const contentBase64 = await fileToBase64(file);
  return request(`/api/cases/${encodeURIComponent(caseId)}/inputs`, {
    method: 'POST',
    body: {
      filename: file.webkitRelativePath || file.name,
      content_base64: contentBase64,
    },
  });
}

export async function startRun(caseId, payload) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/runs`, {
    method: 'POST',
    body: payload,
  });
}

export async function getRun(caseId, runId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}`);
}

export async function getEvents(caseId, runId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/events`);
}

export async function listArtifacts(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/artifacts`);
}

export async function getArtifactText(caseId, artifactId) {
  const response = await fetch(buildUrl(`/api/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(artifactId)}`));
  const text = await response.text();
  if (!response.ok) {
    throw new Error(text || `artifact request failed: ${artifactId}`);
  }
  return text;
}

export function reportHtmlUrl(caseId) {
  return buildUrl(`/api/cases/${encodeURIComponent(caseId)}/report/html`);
}

// Visual Forensics API functions
export async function fetchVisualFigures(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/visual/figures`);
}

export async function fetchVisualPanels(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/visual/panels`);
}

export async function fetchVisualRelationships(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/visual/relationships`);
}

export async function fetchVisualFindings(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/visual/findings`);
}

export async function fetchOverlapReuse(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/artifacts/visual_overlap_reuse`);
}

export async function listInvestigations(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/investigations`);
}

export async function startVisualInvestigation(caseId, payload) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/investigations`, {
    method: 'POST',
    body: payload,
  });
}

export function visualImageUrl(caseId, imagePath) {
  const cleanPath = imagePath.replace(/^\/+/, '');
  return buildUrl(`/api/cases/${encodeURIComponent(caseId)}/visual/images/${cleanPath}`);
}

// Review Queue API
export async function fetchReviewItems(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/review-items`);
}

export async function saveReviewDecision(caseId, sourceRef, payload) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/review-items/${encodeURIComponent(sourceRef)}/decision`, {
    method: 'POST',
    body: payload,
  });
}

// Tool Catalog API
export async function fetchToolCatalog() {
  return request('/api/tools/catalog');
}

export async function fetchToolsHealth() {
  return request('/api/tools/health');
}

// Embeddings / Similarity API
export async function triggerEmbeddingIndex(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/embeddings/index`, {
    method: 'POST',
  });
}

export async function getEmbeddingStatus(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/embeddings/status`);
}

export async function fetchSimilarPanels(caseId, panelId, { topK = 20, threshold = 0.85 } = {}) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/similarity?panel_id=${encodeURIComponent(panelId)}&top_k=${topK}&threshold=${threshold}`);
}

export async function fetchAllSimilarPairs(caseId, { threshold = 0.85 } = {}) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/similarity/pairs?threshold=${threshold}`);
}

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',').pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error(`failed to read file: ${file.name}`));
    reader.readAsDataURL(file);
  });
}
