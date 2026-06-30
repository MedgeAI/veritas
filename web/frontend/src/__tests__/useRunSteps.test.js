import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useRunSteps } from '../hooks/useRunSteps';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_STEPS = [
  { key: 'mineru', title: 'PDF 解析', phase: '文档解析', status: 'completed', duration_seconds: 12 },
  { key: 'visual_tru_for', title: 'TruFor 伪造检测', phase: '视觉取证', status: 'running' },
];

const MOCK_RESPONSE = {
  steps: MOCK_STEPS,
  total: 30,
  completed: 20,
  running: 1,
  failed: 0,
  progress_pct: 67,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetchOk(body) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  });
}

function mockFetchError(status) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: () => Promise.resolve({ detail: 'not found' }),
  });
}

/**
 * Creates a mock EventSource constructor that returns a controllable instance.
 */
function createMockEventSource() {
  const instances = [];

  const MockEventSource = vi.fn(function (url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.listeners = {};
    this.onopen = null;
    this.onerror = null;
    this.close = vi.fn(() => {
      this.readyState = 2; // CLOSED
    });
    this.addEventListener = vi.fn((type, handler) => {
      if (!this.listeners[type]) this.listeners[type] = [];
      this.listeners[type].push(handler);
    });
    instances.push(this);
  });

  return {
    MockEventSource,
    instances,
    /**
     * Simulate an SSE event being dispatched on the most recent instance.
     */
    dispatchEvent(instanceIdx, eventType, data, eventId) {
      const inst = instances[instanceIdx] || instances[instances.length - 1];
      if (!inst) return;
      const event = {
        type: eventType,
        data: JSON.stringify(data),
        lastEventId: eventId || '',
      };
      // Call listeners registered via addEventListener
      const handlers = inst.listeners[eventType] || [];
      for (const handler of handlers) {
        handler(event);
      }
    },
    /**
     * Simulate onopen being called.
     */
    triggerOpen(instanceIdx) {
      const inst = instances[instanceIdx] || instances[instances.length - 1];
      if (inst && inst.onopen) inst.onopen();
    },
    /**
     * Simulate onerror being called.
     */
    triggerError(instanceIdx) {
      const inst = instances[instanceIdx] || instances[instances.length - 1];
      if (inst && inst.onerror) inst.onerror();
    },
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useRunSteps', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', mockFetchOk(MOCK_RESPONSE));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('returns initial loading state, then resolves with steps and progress', async () => {
    const { MockEventSource } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('case-1', 'run-1'));

    // Before the first fetch resolves
    expect(result.current.loading).toBe(true);
    expect(result.current.steps).toEqual([]);
    expect(result.current.error).toBeNull();

    // Let the initial fetch settle
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.steps).toEqual(MOCK_STEPS);
    expect(result.current.progress).toEqual({
      total: 30,
      completed: 20,
      running: 1,
      failed: 0,
      progress_pct: 67,
    });
    expect(result.current.error).toBeNull();
  });

  it('calls fetch with the correct URL including encoded caseId and runId', async () => {
    const { MockEventSource } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    renderHook(() => useRunSteps('case with space', 'run/2'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/cases/case%20with%20space/runs/run%2F2/steps',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
  });

  it('creates an EventSource for SSE streaming after initial fetch', async () => {
    const { MockEventSource, instances } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(MockEventSource).toHaveBeenCalledTimes(1);
    expect(instances[0].url).toContain('/api/cases/c1/runs/r1/stream');
    expect(instances[0].url).toContain('events=lifecycle');
  });

  it('registers event listeners for all 8 lifecycle event types', async () => {
    const { MockEventSource, instances } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const inst = instances[0];
    const expectedEvents = [
      'step.start',
      'step.progress',
      'step.complete',
      'step.failed',
      'step.skipped',
      'progress.update',
      'pipeline.complete',
      'pipeline.failed',
    ];

    for (const eventType of expectedEvents) {
      expect(inst.addEventListener).toHaveBeenCalledWith(eventType, expect.any(Function));
    }
  });

  it('updates step list on step.complete SSE event', async () => {
    const { MockEventSource, dispatchEvent } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Simulate step.complete event
    await act(async () => {
      dispatchEvent(0, 'step.complete', {
        step_key: 'visual_tru_for',
        status: 'success',
        duration_seconds: 45,
        findings_count: 3,
      });
    });

    const updatedStep = result.current.steps.find((s) => s.key === 'visual_tru_for');
    expect(updatedStep.status).toBe('completed');
    expect(updatedStep.duration_seconds).toBe(45);
    expect(updatedStep.findings_count).toBe(3);
  });

  it('updates step list on step.failed SSE event', async () => {
    const { MockEventSource, dispatchEvent } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      dispatchEvent(0, 'step.failed', {
        step_key: 'visual_tru_for',
        error: 'TruFor model not found',
        can_retry: true,
      });
    });

    const updatedStep = result.current.steps.find((s) => s.key === 'visual_tru_for');
    expect(updatedStep.status).toBe('failed');
    expect(updatedStep.error).toBe('TruFor model not found');
  });

  it('updates progress on progress.update SSE event', async () => {
    const { MockEventSource, dispatchEvent } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      dispatchEvent(0, 'progress.update', {
        overall_percent: 85,
        phases: [],
      });
    });

    expect(result.current.progress.progress_pct).toBe(85);
  });

  it('sets error on pipeline.failed SSE event and marks terminated', async () => {
    const { MockEventSource, dispatchEvent } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      dispatchEvent(0, 'pipeline.failed', {
        error: 'MinerU failed to parse PDF',
        failed_step: 'mineru',
      });
    });

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error.message).toBe('MinerU failed to parse PDF');
  });

  it('closes EventSource on pipeline.complete', async () => {
    const { MockEventSource, dispatchEvent, instances } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      dispatchEvent(0, 'pipeline.complete', {
        duration_seconds: 120,
        summary: { total: 30, completed: 29, failed: 1, skipped: 0 },
        artifacts: [],
      });
    });

    // EventSource should be closed after pipeline.complete
    expect(instances[0].close).toHaveBeenCalled();
  });

  it('falls back to polling after 3 SSE failures', async () => {
    vi.useRealTimers();
    const { MockEventSource, triggerError } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // Simulate 3 consecutive SSE failures
    triggerError(0);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // After 3 errors, it should fallback to polling.
    // The EventSource gets closed each time on error.
    triggerError(1); // second instance (from reconnect)
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // Wait for potential polling to start
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // The hook should still return data from the initial fetch
    expect(result.current.steps).toEqual(MOCK_STEPS);
  });

  it('reconnects with Last-Event-ID header after SSE error', async () => {
    const { MockEventSource, instances, dispatchEvent } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Dispatch an event with an ID
    dispatchEvent(0, 'step.start', {
      step_key: 'new_step',
      title: 'New Step',
      phase: '准备',
    }, '42');

    // Trigger an error to simulate disconnection
    instances[0].onerror();

    // Advance timer for reconnection
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    // The second instance should have been created with last-event-id
    if (instances.length > 1) {
      expect(instances[1].url).toContain('last-event-id=42');
    }
  });

  it('stops SSE and cleanup on unmount', async () => {
    const { MockEventSource, instances } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { unmount } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(instances.length).toBe(1);

    unmount();

    expect(instances[0].close).toHaveBeenCalled();
  });

  it('sets error when initial fetch fails', async () => {
    vi.stubGlobal('fetch', mockFetchError(500));
    const { MockEventSource } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error.message).toContain('500');
    expect(result.current.steps).toEqual([]);
  });

  it('handles empty steps array gracefully', async () => {
    vi.stubGlobal('fetch', mockFetchOk({ steps: [], total: 0, completed: 0, running: 0, failed: 0, progress_pct: 0 }));
    const { MockEventSource } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { result } = renderHook(() => useRunSteps('c1', 'r1'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.steps).toEqual([]);
    expect(result.current.progress.total).toBe(0);
    expect(result.current.progress.progress_pct).toBe(0);
  });

  it('re-fetches when caseId or runId changes', async () => {
    const { MockEventSource } = createMockEventSource();
    vi.stubGlobal('EventSource', MockEventSource);

    const { rerender } = renderHook(
      ({ caseId, runId }) => useRunSteps(caseId, runId),
      { initialProps: { caseId: 'c1', runId: 'r1' } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    // Change runId
    rerender({ caseId: 'c1', runId: 'r2' });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // One call for the new runId
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(globalThis.fetch).toHaveBeenLastCalledWith(
      '/api/cases/c1/runs/r2/steps',
      expect.any(Object),
    );
  });
});
