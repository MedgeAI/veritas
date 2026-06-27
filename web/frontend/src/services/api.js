const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

// ---------------------------------------------------------------------------
// Auth credential management
// ---------------------------------------------------------------------------

let authCredentials = null;

export function setAuthCredentials(username, password) {
  authCredentials = { username, password };
  sessionStorage.setItem('veritas_auth', btoa(`${username}:${password}`));
}

export function clearAuthCredentials() {
  authCredentials = null;
  sessionStorage.removeItem('veritas_auth');
}

export function getAuthCredentials() {
  if (authCredentials) return authCredentials;
  const stored = sessionStorage.getItem('veritas_auth');
  if (stored) {
    try {
      const [username, password] = atob(stored).split(':');
      authCredentials = { username, password };
      return authCredentials;
    } catch {
      sessionStorage.removeItem('veritas_auth');
    }
  }
  return null;
}

function authHeaders() {
  const creds = getAuthCredentials();
  if (!creds) return {};
  return { Authorization: `Basic ${btoa(`${creds.username}:${creds.password}`)}` };
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function buildUrl(path) {
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL.replace(/\/$/, '')}${path}`;
}

// ---------------------------------------------------------------------------
// Centralized error translation: backend payload → user-friendly message
// ---------------------------------------------------------------------------

const GENERIC_ERROR_MESSAGES = {
  400: '请求参数有误，请检查输入后重试',
  401: '认证已过期，请重新登录',
  403: '没有权限执行此操作',
  404: '请求的资源不存在',
  409: '数据冲突，请刷新页面后重试',
  422: '数据校验失败，请检查输入格式',
  429: '操作过于频繁，请稍后再试',
  500: '服务内部错误，请稍后重试或联系管理员',
  502: '服务暂时不可用，请稍后重试',
  503: '服务维护中，请稍后重试',
};

export function translateError(status, payload) {
  const detail = typeof payload === 'string'
    ? payload
    : (payload?.detail ?? payload?.error ?? payload?.message);

  // Business-level overrides (matched against backend detail text)
  if (typeof detail === 'string' && detail.length > 0) {
    if (detail.includes('duplicate') || detail.includes('already exists'))
      return '该记录已存在，请勿重复提交';
    if (detail.includes('not found'))
      return '请求的资源未找到';
  }

  return GENERIC_ERROR_MESSAGES[status] || `操作失败（${status}），请稍后重试`;
}

async function request(path, options = {}) {
  const method = options.method || 'GET';
  const headers = {
    ...authHeaders(),
    ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers || {}),
  };
  const response = await fetch(buildUrl(path), {
    method,
    headers,
    credentials: 'same-origin', // 允许同源 cookie（Cloudflare Access JWT）
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();

  if (!response.ok) {
    console.error(`[API] ${method} ${path} → ${response.status}`, payload);
    const error = new Error(translateError(response.status, payload));
    error.status = response.status;
    throw error;
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

export function uploadInputWithAbort(caseId, file, { onProgress } = {}) {
  const formData = new FormData();
  formData.append('file', file);
  if (file.webkitRelativePath) {
    formData.append('relative_path', file.webkitRelativePath);
  }

  let xhr;
  const promise = new Promise((resolve, reject) => {
    xhr = new XMLHttpRequest();
    xhr.open('POST', buildUrl(`/api/cases/${encodeURIComponent(caseId)}/inputs`));
    // Basic auth header for legacy/basic mode; Cloudflare mode uses
    // same-origin cookies automatically (credentials: 'include').
    const creds = getAuthCredentials();
    if (creds) {
      xhr.setRequestHeader('Authorization', `Basic ${btoa(`${creds.username}:${creds.password}`)}`);
    }
    xhr.withCredentials = true;

    if (onProgress && xhr.upload) {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      });
    }
    xhr.onload = () => {
      const contentType = xhr.getResponseHeader('content-type') || '';
      let parsed;
      if (contentType.includes('application/json')) {
        try { parsed = JSON.parse(xhr.responseText); } catch { parsed = xhr.responseText; }
      } else {
        parsed = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(parsed);
      } else {
        console.error(`[API] XHR upload → ${xhr.status}`, parsed);
        reject(new Error(translateError(xhr.status, parsed)));
      }
    };
    xhr.onerror = () => reject(new Error('Upload network error'));
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'));
    xhr.send(formData);
  });

  return { promise, abort: () => xhr && xhr.abort() };
}

export async function uploadInput(caseId, file, { onProgress } = {}) {
  return uploadInputWithAbort(caseId, file, { onProgress }).promise;
}

export function uploadInputsParallel(caseId, files, {
  onProgress,
  onFileProgress,
  onFileComplete,
  onFileError,
  concurrency = 3,
} = {}) {
  const totalSize = files.reduce((sum, f) => sum + (f.size || 0), 0);
  const fileLoaded = new Map();
  const activeAborts = new Set();
  let aborted = false;

  function overallPercent() {
    if (totalSize === 0) return 0;
    let loaded = 0;
    for (const v of fileLoaded.values()) loaded += v;
    return Math.round((loaded / totalSize) * 100);
  }

  function emitOverall() {
    if (onProgress) onProgress(overallPercent());
  }

  function uploadOne(file) {
    return new Promise((resolve) => {
      const { promise, abort } = uploadInputWithAbort(caseId, file, {
        onProgress: (pct) => {
          if (aborted) return;
          const loadedBytes = ((file.size || 0) * pct) / 100;
          fileLoaded.set(file, loadedBytes);
          emitOverall();
          if (onFileProgress) onFileProgress(file, pct);
        },
      });
      activeAborts.add(abort);
      promise
        .then((result) => {
          activeAborts.delete(abort);
          fileLoaded.set(file, file.size || 0);
          emitOverall();
          if (onFileComplete) onFileComplete(file, result);
          resolve({ file, result, error: null });
        })
        .catch((error) => {
          activeAborts.delete(abort);
          if (onFileError) onFileError(file, error);
          resolve({ file, result: null, error });
        });
    });
  }

  const results = [];
  const errors = [];
  let nextIndex = 0;

  async function runNext() {
    while (nextIndex < files.length) {
      if (aborted) return;
      const idx = nextIndex++;
      const outcome = await uploadOne(files[idx]);
      if (outcome.error) {
        errors.push(outcome);
      } else {
        results.push(outcome);
      }
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, files.length) }, () => runNext());

  const promise = Promise.all(workers).then(() => ({ results, errors }));

  return {
    promise,
    abortAll: () => {
      aborted = true;
      for (const abort of activeAborts) abort();
      activeAborts.clear();
    },
  };
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

export async function getRiskSummary(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/risk-summary`);
}

export async function getArtifactText(caseId, artifactId) {
  const response = await fetch(buildUrl(`/api/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(artifactId)}`), {
    headers: authHeaders(),
  });
  const text = await response.text();
  if (!response.ok) {
    console.error(`[API] artifact ${artifactId} → ${response.status}`, text);
    throw new Error(translateError(response.status, text));
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

export async function fetchProvenanceGraph(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/artifacts/provenance_graph`);
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

// Material Completeness Check API
export async function checkMaterials(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}/materials`);
}

// ---------------------------------------------------------------------------
// User management APIs (admin only unless noted)
// ---------------------------------------------------------------------------

export async function listUsers() {
  return request('/api/users');
}

export async function createUser(username, password, email, roles) {
  return request('/api/users', {
    method: 'POST',
    body: { username, password, email, roles },
  });
}

export async function updateUser(userId, email, roles) {
  // In basic mode: userId = username, body = { email, roles }
  // In cloudflare mode: userId = email, body = { roles }
  const body = email !== undefined ? { email, roles } : { roles };
  return request(`/api/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    body,
  });
}

export async function deleteUser(userId) {
  return request(`/api/users/${encodeURIComponent(userId)}`, { method: 'DELETE' });
}

export async function changePassword(username, newPassword) {
  return request(`/api/users/${encodeURIComponent(username)}/password`, {
    method: 'POST',
    body: { password: newPassword },
  });
}

export async function deleteCase(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Audit job APIs
// ---------------------------------------------------------------------------

export async function submitAudit(caseId, options = {}) {
  return request(`/api/audit`, {
    method: 'POST',
    body: { case_id: caseId, ...options },
    signal: options.signal,
  });
}

export async function getAuditJob(jobId) {
  return request(`/api/audit/${encodeURIComponent(jobId)}`);
}

export async function cancelAuditJob(jobId) {
  return request(`/api/audit/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
}

export async function getAuditQueue() {
  return request('/api/audit/queue');
}

// ---------------------------------------------------------------------------
// Current user info
// ---------------------------------------------------------------------------

export async function getCurrentUser() {
  try {
    const me = await request('/api/me');
    return {
      email: me.email,
      roles: me.roles || [],
      isAdmin: me.is_admin || false,
    };
  } catch (e) {
    if (e.status === 401) {
      clearAuthCredentials();
      return null;
    }
    throw e;
  }
}

// ---------------------------------------------------------------------------
// Public verification API (no auth required)
// ---------------------------------------------------------------------------

export async function verifyReport(reportId) {
  return request(`/api/verify/${encodeURIComponent(reportId)}`);
}
