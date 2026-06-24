import { useCallback, useEffect, useRef, useState } from 'react';
import { getAuthCredentials } from '../services/api.js';

const TERMINAL_EVENTS = new Set(['completed', 'failed', 'cancelled']);
const MAX_RECONNECT_ATTEMPTS = 10;
const MAX_BACKOFF_MS = 30000;
const INITIAL_BACKOFF_MS = 1000;
const POLL_INTERVAL_MS = 3000;
const SSE_FAIL_THRESHOLD = 3;

function buildStreamUrl(jobId) {
  const creds = getAuthCredentials();
  let token = '';
  if (creds) {
    token = btoa(`${creds.username}:${creds.password}`);
  }
  const params = new URLSearchParams();
  if (token) params.set('token', token);
  const qs = params.toString();
  return `/api/audit/${encodeURIComponent(jobId)}/stream${qs ? `?${qs}` : ''}`;
}

function buildPollUrl(jobId) {
  return `/api/audit/${encodeURIComponent(jobId)}`;
}

async function pollProgress(jobId, signal) {
  const headers = {};
  const creds = getAuthCredentials();
  if (creds) {
    headers.Authorization = `Basic ${btoa(`${creds.username}:${creds.password}`)}`;
  }
  const response = await fetch(buildPollUrl(jobId), { headers, signal, credentials: 'same-origin' });
  if (!response.ok) {
    throw new Error(`poll failed: ${response.status}`);
  }
  return response.json();
}

/**
 * Hook that subscribes to audit job progress via SSE, with exponential-backoff
 * reconnection and automatic fallback to polling when SSE repeatedly fails.
 *
 * @param {string|null} jobId - The audit job ID to track, or null to disable.
 * @returns {{ progress: Object|null, connected: boolean, stages: Array }}
 */
export function useAuditProgress(jobId) {
  const [progress, setProgress] = useState(null);
  const [connected, setConnected] = useState(false);
  const [stages, setStages] = useState([]);

  const esRef = useRef(null);
  const reconnectAttempt = useRef(0);
  const sseFailCount = useRef(0);
  const usePolling = useRef(false);
  const terminated = useRef(false);
  const pollTimer = useRef(null);

  const cleanup = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const applyEvent = useCallback((eventType, data) => {
    switch (eventType) {
      case 'stage_changed':
        setStages((prev) => {
          const idx = prev.findIndex((s) => s.key === data.key);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], ...data };
            return next;
          }
          return [...prev, data];
        });
        break;
      case 'progress':
        setProgress((prev) => ({ ...prev, ...data }));
        break;
      case 'completed':
      case 'failed':
      case 'cancelled':
        setProgress((prev) => ({ ...prev, ...data, status: eventType }));
        terminated.current = true;
        break;
      default:
        break;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollTimer.current) return;
    usePolling.current = true;
    setConnected(false);

    const controller = new AbortController();
    pollTimer.current = setInterval(async () => {
      try {
        const data = await pollProgress(jobId, controller.signal);
        if (data.progress) setProgress((prev) => ({ ...prev, ...data.progress }));
        if (data.stages) setStages(data.stages);
        if (data.status && TERMINAL_EVENTS.has(data.status)) {
          setProgress((prev) => ({ ...prev, status: data.status }));
          terminated.current = true;
          clearInterval(pollTimer.current);
          pollTimer.current = null;
        }
      } catch {
        // poll errors are silent; next tick retries
      }
    }, POLL_INTERVAL_MS);

    // Also run an immediate poll
    pollProgress(jobId, controller.signal)
      .then((data) => {
        if (data.progress) setProgress((prev) => ({ ...prev, ...data.progress }));
        if (data.stages) setStages(data.stages);
        if (data.status && TERMINAL_EVENTS.has(data.status)) {
          setProgress((prev) => ({ ...prev, status: data.status }));
          terminated.current = true;
          clearInterval(pollTimer.current);
          pollTimer.current = null;
        }
      })
      .catch(() => {});
  }, [jobId]);

  const connectSSE = useCallback(() => {
    if (terminated.current || !jobId) return;
    if (usePolling.current) return;

    const es = new EventSource(buildStreamUrl(jobId));
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      reconnectAttempt.current = 0;
      sseFailCount.current = 0;
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setConnected(false);

      if (terminated.current) return;

      reconnectAttempt.current += 1;
      sseFailCount.current += 1;

      if (sseFailCount.current >= SSE_FAIL_THRESHOLD) {
        startPolling();
        return;
      }

      if (reconnectAttempt.current > MAX_RECONNECT_ATTEMPTS) {
        startPolling();
        return;
      }

      const backoff = Math.min(
        INITIAL_BACKOFF_MS * 2 ** (reconnectAttempt.current - 1),
        MAX_BACKOFF_MS,
      );
      setTimeout(connectSSE, backoff);
    };

    const makeHandler = (eventType) => (event) => {
      try {
        const data = JSON.parse(event.data);
        applyEvent(eventType, data);
        if (TERMINAL_EVENTS.has(eventType)) {
          es.close();
          esRef.current = null;
          setConnected(false);
        }
      } catch {
        // malformed JSON — skip
      }
    };

    es.addEventListener('stage_changed', makeHandler('stage_changed'));
    es.addEventListener('progress', makeHandler('progress'));
    es.addEventListener('completed', makeHandler('completed'));
    es.addEventListener('failed', makeHandler('failed'));
    es.addEventListener('cancelled', makeHandler('cancelled'));
  }, [jobId, applyEvent, startPolling]);

  // Main effect: connect when jobId changes, cleanup on unmount
  useEffect(() => {
    terminated.current = false;
    reconnectAttempt.current = 0;
    sseFailCount.current = 0;
    usePolling.current = false;

    if (!jobId) {
      setProgress(null);
      setConnected(false);
      setStages([]);
      return cleanup;
    }

    connectSSE();

    return cleanup;
  }, [jobId, connectSSE, cleanup]);

  return { progress, connected, stages };
}
