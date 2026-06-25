import { useMemo } from 'react';
import {
  PHASES,
  getStepStatuses,
  getPhaseStatus,
  computeWeightedProgress,
  getTotalSteps,
} from './progress/phases.js';
import PhaseRail from './progress/PhaseRail.jsx';
import PhaseHeroCard from './progress/PhaseHeroCard.jsx';
import CollapsedPastPhases from './progress/CollapsedPastPhases.jsx';
import GhostedFuturePhases from './progress/GhostedFuturePhases.jsx';
import CompletionSummary from './progress/CompletionSummary.jsx';

/**
 * Compute step durations from events
 * For each stepKey, find step_start and step_result timestamps, compute delta in seconds
 */
function computeStepDurations(events) {
  const durations = {};
  const startTimes = {};

  for (const event of events) {
    const key = event.key;
    if (!key) continue;

    // Normalize key for investigation steps
    let stepKey = key;
    if (key.match(/^investigation_\d{2}_/)) {
      stepKey = key.split('_').slice(0, 2).join('_');
    }

    if (event.event === 'step_start') {
      startTimes[stepKey] = new Date(event.timestamp).getTime();
    } else if (event.event === 'step_result' && startTimes[stepKey]) {
      const endTime = new Date(event.timestamp).getTime();
      const startTime = startTimes[stepKey];
      const durationSec = (endTime - startTime) / 1000;
      if (durationSec >= 0) {
        durations[stepKey] = durationSec;
      }
    }
  }

  return durations;
}

/**
 * Compute total duration from first to last event timestamp
 */
function computeTotalDuration(events) {
  if (!events || events.length === 0) return 0;

  const timestamps = events
    .map((e) => new Date(e.timestamp).getTime())
    .filter((t) => !isNaN(t));

  if (timestamps.length === 0) return 0;

  const minTime = Math.min(...timestamps);
  const maxTime = Math.max(...timestamps);

  return (maxTime - minTime) / 1000;
}

function ProgressTracker({ events, runStatus, _startedAt, caseId }) {
  // Compute step statuses from events
  const stepStatuses = useMemo(() => {
    if (!events || events.length === 0) return {};
    return getStepStatuses(events);
  }, [events]);

  // Compute phase statuses
  const phaseStatuses = useMemo(() => {
    return Object.fromEntries(PHASES.map((p) => [p.id, getPhaseStatus(p, stepStatuses)]));
  }, [stepStatuses]);

  // Compute weighted progress
  const progress = useMemo(() => {
    return computeWeightedProgress(phaseStatuses);
  }, [phaseStatuses]);

  // Find current phase (first running or first pending)
  const currentPhase = useMemo(() => {
    const running = PHASES.find((p) => phaseStatuses[p.id] === 'running');
    if (running) return running;
    const pending = PHASES.find((p) => phaseStatuses[p.id] === 'pending');
    return pending;
  }, [phaseStatuses]);

  // Completed phases
  const completedPhases = useMemo(() => {
    return PHASES.filter((p) => phaseStatuses[p.id] === 'completed');
  }, [phaseStatuses]);

  // Pending phases (excluding current phase)
  const pendingPhases = useMemo(() => {
    return PHASES.filter(
      (p) => phaseStatuses[p.id] === 'pending' && p.id !== currentPhase?.id,
    );
  }, [phaseStatuses, currentPhase]);

  // Compute step durations
  const stepDurations = useMemo(() => {
    if (!events || events.length === 0) return {};
    return computeStepDurations(events);
  }, [events]);

  // Compute total duration
  const totalDuration = useMemo(() => {
    if (runStatus !== 'completed') return 0;
    return computeTotalDuration(events);
  }, [runStatus, events]);

  // Count completed and failed steps
  const completedStepCount = useMemo(() => {
    return Object.values(stepStatuses).filter((s) => s === 'completed').length;
  }, [stepStatuses]);

  const failedStepCount = useMemo(() => {
    return Object.values(stepStatuses).filter((s) => s === 'failed').length;
  }, [stepStatuses]);

  const totalSteps = getTotalSteps();

  // Edge case: empty events
  if (!events || events.length === 0) {
    return (
      <div className="dossier-panel rounded-[2rem] p-6">
        <p className="metric-label">审查进度</p>
        <p className="text-sm text-ink-500 mt-4">等待审查开始…</p>
      </div>
    );
  }

  // Completed state
  if (runStatus === 'completed') {
    const handleViewReport = () => {
      if (caseId) {
        const reportUrl = `/cases/${caseId}/report.html`;
        window.open(reportUrl, '_blank');
      }
    };

    return (
      <CompletionSummary
        totalDuration={totalDuration}
        totalSteps={totalSteps}
        completedSteps={completedStepCount}
        failedSteps={failedStepCount}
        caseId={caseId}
        onViewReport={handleViewReport}
      />
    );
  }

  // Running, queued, failed state
  return (
    <div className="dossier-panel rounded-[2rem] p-6">
      <p className="metric-label">审查进度</p>

      <PhaseRail phases={PHASES} phaseStatuses={phaseStatuses} />

      {/* Progress bar */}
      <div className="mt-6 mb-2">
        <div className="h-2 rounded-full bg-ink-900/5 overflow-hidden">
          <div
            className="h-full bg-signal-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-sm text-ink-600 mt-2">
          {progress}% · 步骤 {completedStepCount}/{totalSteps}
        </p>
      </div>

      {/* Current phase hero card */}
      {currentPhase && (
        <div className="mt-6">
          <PhaseHeroCard
            phase={currentPhase}
            stepStatuses={stepStatuses}
            stepDurations={stepDurations}
          />
        </div>
      )}

      {/* Collapsed past phases */}
      {completedPhases.length > 0 && (
        <div className="mt-4">
          <CollapsedPastPhases
            phases={completedPhases}
            stepStatuses={stepStatuses}
            stepDurations={stepDurations}
          />
        </div>
      )}

      {/* Ghosted future phases */}
      {pendingPhases.length > 0 && (
        <GhostedFuturePhases phases={pendingPhases} />
      )}
    </div>
  );
}

export default ProgressTracker;
