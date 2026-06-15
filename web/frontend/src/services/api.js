const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL.replace(/\/$/, '')}${path}`;
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
    const detail = typeof payload === 'string' ? payload : payload.detail || payload.error || 'request failed';
    throw new Error(detail);
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

export function visualImageUrl(caseId, imagePath) {
  const cleanPath = imagePath.replace(/^\/+/, '');
  return buildUrl(`/api/cases/${encodeURIComponent(caseId)}/visual/images/${cleanPath}`);
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
