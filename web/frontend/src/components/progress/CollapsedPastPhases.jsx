import PropTypes from 'prop-types';
import { useState } from 'react';
import { FiChevronRight, FiChevronDown } from 'react-icons/fi';

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

export default function CollapsedPastPhases({ phases, stepDurations = {} }) {
  const [expanded, setExpanded] = useState(false);

  if (!phases || phases.length === 0) return null;

  const totalDuration = phases.reduce((sum, phase) => {
    const phaseDuration = phase.steps.reduce((s, step) => {
      return s + (stepDurations[step.key] || step.duration_seconds || 0);
    }, 0);
    return sum + phaseDuration;
  }, 0);

  return (
    <div className="mt-4">
      <div
        className="h-11 flex items-center gap-2 px-4 rounded-xl hover:bg-ink-900/5 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <FiChevronDown className="w-4 h-4 text-ink-600 transition-transform duration-200" />
        ) : (
          <FiChevronRight className="w-4 h-4 text-ink-600 transition-transform duration-200" />
        )}
        <span className="text-sm font-medium text-ink-600">
          已完成阶段 ({phases.length})
        </span>
        {totalDuration > 0 && (
          <div className="ml-auto">
            <span className="rounded-full border bg-white/55 font-mono text-[11px] px-2 py-0.5 text-ink-600">
              {formatDuration(totalDuration)}
            </span>
          </div>
        )}
      </div>

      {expanded && (
        <div className="space-y-1 mt-1">
          {phases.map((phase) => {
            const phaseDuration = phase.steps.reduce((sum, step) => {
              return sum + (stepDurations[step.key] || step.duration_seconds || 0);
            }, 0);

            return (
              <div
                key={phase.name}
                className="h-9 flex items-center gap-3 px-3 pl-8 rounded-lg"
              >
                <span className="text-sm text-ink-600">{phase.name}</span>
                <span className="text-xs text-ink-500">· {phase.steps.length} 步</span>
                {phaseDuration > 0 && (
                  <span className="text-xs font-mono text-ink-500 ml-auto">
                    {formatDuration(phaseDuration)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

CollapsedPastPhases.propTypes = {
  phases: PropTypes.arrayOf(PropTypes.shape({
    name: PropTypes.string.isRequired,
    steps: PropTypes.array.isRequired,
  })).isRequired,
  stepDurations: PropTypes.object,
};
