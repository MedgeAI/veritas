/**
 * SSE event schema for real-time audit progress streaming.
 *
 * Canonical reference: docs/PRD_progress-refactor_0626.md (SSE section).
 *
 * The SSE endpoint (`GET /api/cases/{id}/runs/{run_id}/stream`) streams
 * frames whose `event` field is one of the SSEEventType union members
 * and whose `data` payload matches the corresponding interface.
 */

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

/** Outer envelope wrapping every SSE frame. */
export interface SSEEnvelope<T extends SSEEventType = SSEEventType> {
  /** Event ID, used for Last-Event-ID reconnection. */
  id: string;
  /** Event type discriminator. */
  type: T;
  /** ISO 8601 timestamp. */
  timestamp: string;
  /** Event-specific payload, shape determined by `type`. */
  data: SSEEventDataMap[T];
}

// ---------------------------------------------------------------------------
// Event type union
// ---------------------------------------------------------------------------

export type SSEEventType =
  // Pipeline lifecycle
  | 'pipeline.start'
  | 'pipeline.complete'
  | 'pipeline.failed'
  // Step lifecycle
  | 'step.start'
  | 'step.progress'
  | 'step.complete'
  | 'step.failed'
  | 'step.skipped'
  // Agent reasoning
  | 'agent.thinking'
  | 'agent.tool_call'
  | 'agent.tool_result'
  // Progress aggregation
  | 'progress.update'
  // Log stream
  | 'log';

// ---------------------------------------------------------------------------
// Pipeline lifecycle events
// ---------------------------------------------------------------------------

export interface PipelineStartEvent {
  run_id: string;
  paper_title: string;
  phases: Array<{ key: string; title: string; order: number }>;
  total_steps: number;
}

export interface PipelineCompleteEvent {
  duration_seconds: number;
  summary: {
    total: number;
    completed: number;
    failed: number;
    skipped: number;
  };
  artifacts: string[];
}

export interface PipelineFailedEvent {
  error: string;
  failed_step: string;
  retry_hint?: string;
}

// ---------------------------------------------------------------------------
// Step lifecycle events
// ---------------------------------------------------------------------------

export interface StepStartEvent {
  step_key: string;
  title: string;
  phase: string;
  estimated_seconds?: number;
}

export interface StepProgressEvent {
  step_key: string;
  /** 0-100 */
  percent: number;
  current: number;
  total: number;
  message: string;
}

export interface StepCompleteEvent {
  step_key: string;
  status: 'success' | 'warning' | 'skipped';
  duration_seconds: number;
  artifacts: string[];
  summary: string;
  findings_count?: number;
}

export interface StepFailedEvent {
  step_key: string;
  error: string;
  can_retry: boolean;
}

export interface StepSkippedEvent {
  step_key: string;
  reason: string;
}

// ---------------------------------------------------------------------------
// Agent reasoning events
// ---------------------------------------------------------------------------

export interface AgentThinkingEvent {
  step_key: string;
  /** "judge" | "investigator" | "planner" */
  role: string;
  /** Streaming text content. */
  content: string;
  is_streaming: boolean;
}

export interface AgentToolCallEvent {
  step_key: string;
  call_id: string;
  tool_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface AgentToolResultEvent {
  step_key: string;
  call_id: string;
  status: 'success' | 'error';
  summary: string;
  duration_ms: number;
  /**
   * Full result via REST:
   * GET /api/cases/{case_id}/runs/{run_id}/tool-results/{call_id}
   */
}

// ---------------------------------------------------------------------------
// Progress aggregation event
// ---------------------------------------------------------------------------

export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface ProgressUpdateEvent {
  overall_percent: number;
  phases: Array<{
    phase: string;
    order: number;
    total_steps: number;
    completed_steps: number;
    current_step?: string;
    status: StepStatus;
  }>;
  estimated_remaining_seconds?: number;
}

// ---------------------------------------------------------------------------
// Log event
// ---------------------------------------------------------------------------

export type LogLevel = 'debug' | 'info' | 'warning' | 'error';

export interface LogEvent {
  level: LogLevel;
  step_key?: string;
  message: string;
  context?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Event-type → data-type map (used by SSEEnvelope generic)
// ---------------------------------------------------------------------------

export interface SSEEventDataMap {
  'pipeline.start': PipelineStartEvent;
  'pipeline.complete': PipelineCompleteEvent;
  'pipeline.failed': PipelineFailedEvent;
  'step.start': StepStartEvent;
  'step.progress': StepProgressEvent;
  'step.complete': StepCompleteEvent;
  'step.failed': StepFailedEvent;
  'step.skipped': StepSkippedEvent;
  'agent.thinking': AgentThinkingEvent;
  'agent.tool_call': AgentToolCallEvent;
  'agent.tool_result': AgentToolResultEvent;
  'progress.update': ProgressUpdateEvent;
  'log': LogEvent;
}

// ---------------------------------------------------------------------------
// Convenience: discriminated union of all concrete events
// ---------------------------------------------------------------------------

/** A concrete SSE event — the union of all possible envelope instantiations. */
export type SSEEvent = {
  [K in SSEEventType]: SSEEnvelope<K>;
}[SSEEventType];
