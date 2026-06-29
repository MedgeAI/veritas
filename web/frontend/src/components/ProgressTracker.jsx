import PropTypes from 'prop-types';
import { useMemo } from 'react';
import PhaseRail from './progress/PhaseRail.jsx';
import PhaseHeroCard from './progress/PhaseHeroCard.jsx';
import CollapsedPastPhases from './progress/CollapsedPastPhases.jsx';
import GhostedFuturePhases from './progress/GhostedFuturePhases.jsx';
import CompletionSummary from './progress/CompletionSummary.jsx';

/**
 * Group steps by phase and compute phase-level status
 */
function groupStepsByPhase(steps) {
  const phaseMap = new Map();

  for (const step of steps) {
    const phaseName = step.phase || 'Unknown';
    const phaseOrder = step.phase_order ?? 99;

    if (!phaseMap.has(phaseName)) {
      phaseMap.set(phaseName, {
        name: phaseName,
        order: phaseOrder,
        steps: [],
      });
    }
    phaseMap.get(phaseName).steps.push(step);
  }

  return Array.from(phaseMap.values()).sort((a, b) => a.order - b.order);
}

/**
 * Compute phase status from its steps
 */
function computePhaseStatus(phaseSteps) {
  const statuses = phaseSteps.map((s) => s.status);

  if (statuses.length === 0) return 'pending';
  if (statuses.every((s) => s === 'completed' || s === 'skipped')) return 'completed';
  if (statuses.some((s) => s === 'running')) return 'running';

  return 'pending';
}

function ProgressTracker({ steps = [], runStatus, caseId }) {
  // Group steps by phase
  const phases = useMemo(() => groupStepsByPhase(steps), [steps]);

  // Compute phase statuses
  const phaseStatuses = useMemo(() => {
    return Object.fromEntries(
      phases.map((p) => [p.name, computePhaseStatus(p.steps)]),
    );
  }, [phases]);

  // Compute step-level statuses (for backward compatibility)
  const stepStatuses = useMemo(() => {
    return Object.fromEntries(steps.map((s) => [s.key, s.status]));
  }, [steps]);

  // Compute step durations
  const stepDurations = useMemo(() => {
    return Object.fromEntries(
      steps.map((s) => [s.key, s.duration_seconds]),
    );
  }, [steps]);

  // Find current phase (first running or first pending)
  const currentPhase = useMemo(() => {
    const running = phases.find((p) => phaseStatuses[p.name] === 'running');
    if (running) return running;
    const pending = phases.find((p) => phaseStatuses[p.name] === 'pending');
    return pending;
  }, [phases, phaseStatuses]);

  // Completed phases
  const completedPhases = useMemo(() => {
    return phases.filter((p) => phaseStatuses[p.name] === 'completed');
  }, [phases, phaseStatuses]);

  // Pending phases (excluding current phase)
  const pendingPhases = useMemo(() => {
    return phases.filter(
      (p) => phaseStatuses[p.name] === 'pending' && p.name !== currentPhase?.name,
    );
  }, [phases, phaseStatuses, currentPhase]);

  // Compute total duration
  const totalDuration = useMemo(() => {
    if (runStatus !== 'completed') return 0;
    return steps.reduce((sum, s) => sum + (s.duration_seconds || 0), 0);
  }, [runStatus, steps]);

  // Count completed and failed steps
  const completedStepCount = useMemo(() => {
    return steps.filter((s) => s.status === 'completed').length;
  }, [steps]);

  const failedStepCount = useMemo(() => {
    return steps.filter((s) => s.status === 'failed').length;
  }, [steps]);

  const totalSteps = steps.length;

  // Edge case: empty steps
  if (!steps || steps.length === 0) {
    return (
      <div className="dossier-panel rounded-2xl p-6">
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

  // Compute progress percentage
  const progressPct = totalSteps > 0 ? Math.round((completedStepCount / totalSteps) * 100) : 0;

  // Running, queued, failed state
  return (
    <div className="dossier-panel rounded-2xl p-6">
      <p className="metric-label">审查进度</p>

      <PhaseRail phases={phases} phaseStatuses={phaseStatuses} />

      {/* Progress bar */}
      <div className="mt-6 mb-2">
        <div className="h-2 rounded-full bg-ink-900/5 overflow-hidden">
          <div
            className="h-full bg-signal-500 transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <p className="text-sm text-ink-600 mt-2">
          {progressPct}% · 步骤 {completedStepCount}/{totalSteps}
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

ProgressTracker.propTypes = {
  steps: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      title: PropTypes.string.isRequired,
      phase: PropTypes.string.isRequired,
      phase_order: PropTypes.number.isRequired,
      status: PropTypes.oneOf(['completed', 'running', 'failed', 'skipped', 'pending']).isRequired,
      duration_seconds: PropTypes.number,
      started_at: PropTypes.string,
    }),
  ).isRequired,
  runStatus: PropTypes.string.isRequired,
  caseId: PropTypes.string,
};

export default ProgressTracker;
