import PropTypes from 'prop-types';
import { useMemo } from 'react';
import { FiAlertCircle } from 'react-icons/fi';
import PhaseRail from './progress/PhaseRail.jsx';
import PhaseHeroCard from './progress/PhaseHeroCard.jsx';
import CollapsedPastPhases from './progress/CollapsedPastPhases.jsx';
import GhostedFuturePhases from './progress/GhostedFuturePhases.jsx';
import CompletionSummary from './progress/CompletionSummary.jsx';
import {
  buildPhaseStatuses,
  findCurrentPhase,
  groupStepsByPhase,
  PHASE_STATUS,
  PHASE_STATUS_VALUES,
} from '../utils/progressPhases.js';

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const safeSeconds = Math.max(0, Math.floor(Number(seconds)));
  if (safeSeconds < 60) return `${safeSeconds} 秒`;
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  if (minutes < 60) {
    return remainingSeconds > 0 ? `${minutes} 分 ${remainingSeconds} 秒` : `${minutes} 分`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours} 小时 ${remainingMinutes} 分` : `${hours} 小时`;
}

function formatEventAge(seconds) {
  const duration = formatDuration(seconds);
  return duration ? `${duration}前` : null;
}

function ProgressTracker({ steps = [], progress = {}, runStatus, caseId }) {
  // Group steps by phase
  const phases = useMemo(() => groupStepsByPhase(steps), [steps]);

  // Compute phase statuses
  const phaseStatuses = useMemo(() => buildPhaseStatuses(phases), [phases]);

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

  // Find current phase (running step first, then first pending phase)
  const currentPhase = useMemo(() => {
    return findCurrentPhase(phases, phaseStatuses);
  }, [phases, phaseStatuses]);

  // Completed phases
  const completedPhases = useMemo(() => {
    return phases.filter((p) => (
      phaseStatuses[p.name] === PHASE_STATUS.COMPLETED
      || phaseStatuses[p.name] === PHASE_STATUS.SKIPPED
    ));
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
  const currentPhaseIndex = currentPhase
    ? phases.findIndex((phase) => phase.name === currentPhase.name) + 1
    : 0;
  const elapsedLabel = formatDuration(progress.elapsed_seconds);
  const eventAgeLabel = formatEventAge(progress.seconds_since_last_event);
  const currentStepTitle = progress.current_step?.title || progress.current_step?.key;

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
        onViewReport={handleViewReport}
      />
    );
  }

  // Running, queued, failed state
  return (
    <div className="dossier-panel rounded-2xl p-6">
      <p className="metric-label">审查进度</p>

      <PhaseRail
        phases={phases}
        phaseStatuses={phaseStatuses}
        currentPhaseName={currentPhase?.name}
      />

      {/* Factual phase and timing summary */}
      <div className="mt-6 border-t border-ink-900/10 pt-4">
        <p className="text-sm text-ink-700">
          {currentPhase && phases.length > 0
            ? `阶段 ${currentPhaseIndex}/${phases.length}: ${currentPhase.name}`
            : '等待阶段'}
          {elapsedLabel ? ` · 已用时 ${elapsedLabel}` : ''}
          {currentStepTitle ? ` · 当前: ${currentStepTitle}` : ''}
        </p>
      </div>

      {progress.is_stale && (
        <div
          className="mt-4 flex items-start gap-3 rounded-xl border border-[#d69a2d]/30 bg-[#fff7e6] px-4 py-3 text-sm leading-6 text-[#7a4e00]"
          role="status"
        >
          <FiAlertCircle size={16} strokeWidth={1.8} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            等待外部服务响应，可能正在处理 PDF 解析、视觉取证或模型调用。
            {eventAgeLabel ? ` 最后事件: ${eventAgeLabel}` : ''}
          </span>
        </div>
      )}

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
      status: PropTypes.oneOf([...PHASE_STATUS_VALUES, 'done']).isRequired,
      duration_seconds: PropTypes.number,
      started_at: PropTypes.string,
    }),
  ).isRequired,
  progress: PropTypes.shape({
    current_step: PropTypes.shape({
      key: PropTypes.string,
      title: PropTypes.string,
      phase: PropTypes.string,
      status: PropTypes.string,
      started_at: PropTypes.string,
    }),
    elapsed_seconds: PropTypes.number,
    seconds_since_last_event: PropTypes.number,
    is_stale: PropTypes.bool,
  }),
  runStatus: PropTypes.string.isRequired,
  caseId: PropTypes.string,
};

export default ProgressTracker;
