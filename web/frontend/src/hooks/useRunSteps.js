import { useCallback, useEffect, useRef, useState } from 'react';
import { getAuthCredentials } from '../services/api.js';

const SSE_FAIL_THRESHOLD = 3;
const MAX_RECONNECT_ATTEMPTS = 10;
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const POLL_INTERVAL_MS = 5000;

const INITIAL_PROGRESS = Object.freeze({
  total: 0,
  completed: 0,
  running: 0,
  failed: 0,
  progress_pct: 0,
});

function buildStreamUrl(caseId, runId) {
  const creds = getAuthCredentials();
  let token = '';
  if (creds) {
    token = btoa(`${creds.username}:${creds.password}`);
  }
  const params = new URLSearchParams();
  params.set('events', 'lifecycle');
  if (token) params.set('token', token);
  return `/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/stream?${params.toString()}`;
}

function buildStepsUrl(caseId, runId) {
  return `/api/cases/${encodeURIComponent(caseId)}/runs/${encodeURIComponent(runId)}/steps`;
}

function authHeaders() {
  const creds = getAuthCredentials();
  if (!creds) return {};
  return { Authorization: `Basic ${btoa(`${creds.username}:${creds.password}`)}` };
}

/**
 * Subscribe to run progress via SSE, with exponential-backoff reconnection
 * and automatic fallback to polling when SSE repeatedly fails.
 *
 * @param {string} caseId
 * @param {string} runId
 * @returns {{ steps: Array, progress: Object, loading: boolean, error: Error|null }}
 */
export function useRunSteps(caseId, runId) {
  const [steps, setSteps] = useState([]);
  const [progress, setProgress] = useState(INITIAL_PROGRESS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const mountedRef = useRef(true);
  const esRef = useRef(null);
  const lastEventIdRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const sseFailCountRef = useRef(0);
  const usePollingRef = useRef(false);
  const pollTimerRef = useRef(null);
  const terminatedRef = useRef(false);

  // Initial fetch to populate steps list
  const fetchInitialSteps = useCallback(async () => {
    if (!caseId || !runId) return;
    try {
      const res = await fetch(buildStepsUrl(caseId, runId), {
        headers: authHeaders(),
        credentials: 'same-origin',
      });
      if (!res.ok) {
        throw new Error(`steps request failed: ${res.status}`);
      }
      const data = await res.json();
      if (!mountedRef.current) return;
      setSteps(data.steps ?? []);
      setProgress({
        total: data.total ?? 0,
        completed: data.completed ?? 0,
        running: data.running ?? 0,
        failed: data.failed ?? 0,
        progress_pct: data.progress_pct ?? 0,
      });
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err);
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [caseId, runId]);

  // Polling fallback
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return;
    usePollingRef.current = true;

    const poll = async () => {
      if (!mountedRef.current || terminatedRef.current) return;
      try {
        const res = await fetch(buildStepsUrl(caseId, runId), {
          headers: authHeaders(),
          credentials: 'same-origin',
        });
        if (!res.ok) {
          throw new Error(`steps request failed: ${res.status}`);
        }
        const data = await res.json();
        if (!mountedRef.current) return;
        setSteps(data.steps ?? []);
        setProgress({
          total: data.total ?? 0,
          completed: data.completed ?? 0,
          running: data.running ?? 0,
          failed: data.failed ?? 0,
          progress_pct: data.progress_pct ?? 0,
        });
        setError(null);
        // Stop polling if pipeline completed or failed
        if (data.progress_pct >= 100 || data.failed > 0) {
          terminatedRef.current = true;
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
        }
      } catch (err) {
        if (!mountedRef.current) return;
        setError(err);
      }
    };

    poll();
    pollTimerRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, [caseId, runId]);

  // SSE event handlers
  const applySSEEvent = useCallback((eventType, data) => {
    switch (eventType) {
      case 'step.start':
        setSteps((prev) => {
          const idx = prev.findIndex((s) => s.key === data.step_key);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], status: 'running', title: data.title, phase: data.phase };
            return next;
          }
          return [...prev, { key: data.step_key, title: data.title, phase: data.phase, status: 'running' }];
        });
        break;
      case 'step.progress':
        // Update step-level progress (not shown in step list, but in progress bar)
        break;
      case 'step.complete':
        setSteps((prev) => {
          const idx = prev.findIndex((s) => s.key === data.step_key);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = {
              ...next[idx],
              status: data.status === 'success' ? 'completed' : data.status,
              duration_seconds: data.duration_seconds,
              findings_count: data.findings_count,
            };
            return next;
          }
          return prev;
        });
        break;
      case 'step.failed':
        setSteps((prev) => {
          const idx = prev.findIndex((s) => s.key === data.step_key);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], status: 'failed', error: data.error };
            return next;
          }
          return prev;
        });
        break;
      case 'step.skipped':
        setSteps((prev) => {
          const idx = prev.findIndex((s) => s.key === data.step_key);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], status: 'skipped', reason: data.reason };
            return next;
          }
          return prev;
        });
        break;
      case 'progress.update':
        // Update overall progress
        setProgress((prev) => ({
          ...prev,
          progress_pct: data.overall_percent ?? prev.progress_pct,
        }));
        break;
      case 'pipeline.complete':
        // Pipeline finished successfully
        if (data.summary) {
          setProgress((prev) => ({
            ...prev,
            total: data.summary.total ?? prev.total,
            completed: data.summary.completed ?? prev.completed,
            failed: data.summary.failed ?? prev.failed,
            progress_pct: 100,
          }));
        }
        terminatedRef.current = true;
        // Close the EventSource since we're done
        if (esRef.current) {
          esRef.current.close();
          esRef.current = null;
        }
        break;
      case 'pipeline.failed':
        // Pipeline failed
        setError(new Error(data.error || 'Pipeline failed'));
        terminatedRef.current = true;
        // Close the EventSource since we're done
        if (esRef.current) {
          esRef.current.close();
          esRef.current = null;
        }
        break;
      default:
        break;
    }
  }, []);

  // Connect to SSE
  const connectSSE = useCallback(() => {
    if (terminatedRef.current || !caseId || !runId) return;
    if (usePollingRef.current) return;

    let url = buildStreamUrl(caseId, runId);
    // Add Last-Event-ID for reconnection
    if (lastEventIdRef.current) {
      url += `&last-event-id=${lastEventIdRef.current}`;
    }

    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      reconnectAttemptRef.current = 0;
      sseFailCountRef.current = 0;
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;

      if (terminatedRef.current || !mountedRef.current) return;

      reconnectAttemptRef.current += 1;
      sseFailCountRef.current += 1;

      // Fallback to polling after 3 failures
      if (sseFailCountRef.current >= SSE_FAIL_THRESHOLD) {
        startPolling();
        return;
      }

      // Stop reconnecting after 10 attempts
      if (reconnectAttemptRef.current > MAX_RECONNECT_ATTEMPTS) {
        startPolling();
        return;
      }

      // Exponential backoff
      const backoff = Math.min(
        INITIAL_BACKOFF_MS * 2 ** (reconnectAttemptRef.current - 1),
        MAX_BACKOFF_MS,
      );
      setTimeout(connectSSE, backoff);
    };

    // Register event handlers
    const eventTypes = [
      'step.start',
      'step.progress',
      'step.complete',
      'step.failed',
      'step.skipped',
      'progress.update',
      'pipeline.complete',
      'pipeline.failed',
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (event) => {
        try {
          const data = JSON.parse(event.data);
          // Track last event ID for reconnection
          if (event.lastEventId) {
            lastEventIdRef.current = event.lastEventId;
          }
          applySSEEvent(eventType, data);
        } catch {
          // malformed JSON — skip
        }
      });
    }
  }, [caseId, runId, applySSEEvent, startPolling]);

  // Cleanup
  const cleanup = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  // Main effect
  useEffect(() => {
    mountedRef.current = true;
    terminatedRef.current = false;
    reconnectAttemptRef.current = 0;
    sseFailCountRef.current = 0;
    usePollingRef.current = false;
    lastEventIdRef.current = null;

    if (!caseId || !runId) {
      setSteps([]);
      setProgress(INITIAL_PROGRESS);
      setLoading(false);
      return cleanup;
    }

    setLoading(true);
    setError(null);

    // Fetch initial steps list via REST
    fetchInitialSteps().then(() => {
      // After initial fetch, connect to SSE for live updates
      if (mountedRef.current && !terminatedRef.current) {
        connectSSE();
      }
    });

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [caseId, runId, fetchInitialSteps, connectSSE, cleanup]);

  return { steps, progress, loading, error };
}
