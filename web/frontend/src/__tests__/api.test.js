import { afterEach, describe, expect, it, vi } from 'vitest';
import { cancelAuditJob, clearAuthCredentials, submitAudit } from '../services/api.js';

function jsonResponse(payload, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: () => 'application/json',
    },
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  });
}

describe('services/api', () => {
  afterEach(() => {
    clearAuthCredentials();
    vi.unstubAllGlobals();
  });

  it('submits audits using the backend options contract', async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn(() => jsonResponse({ job_id: 'run-1' }, 202));
    vi.stubGlobal('fetch', fetchMock);

    await submitAudit(
      'case-1',
      { options: { agent_mode: 'full' }, signal },
      'static',
    );

    expect(fetchMock).toHaveBeenCalledWith('/api/audit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        case_id: 'case-1',
        options: {
          agent_mode: 'full',
          reproducibility_tier: 'static',
        },
      }),
      signal,
    });
  });

  it('cancels audits with DELETE /api/audit/{jobId}', async () => {
    const fetchMock = vi.fn(() => jsonResponse({ status: 'cancelled' }));
    vi.stubGlobal('fetch', fetchMock);

    await cancelAuditJob('run/1');

    expect(fetchMock).toHaveBeenCalledWith('/api/audit/run%2F1', {
      method: 'DELETE',
      headers: {},
      credentials: 'same-origin',
      body: undefined,
      signal: undefined,
    });
  });
});
