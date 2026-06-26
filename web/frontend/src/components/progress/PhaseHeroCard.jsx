import PropTypes from 'prop-types';
import { FiCheck, FiLoader, FiCircle, FiX } from 'react-icons/fi';

/**
 * Format duration in seconds to human-readable string.
 * < 60s  → "Ns"
 * < 3600s → "Nm Ns"
 * else   → "Nh Nm"
 */
function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

const STATUS_ICON = {
  completed: { Icon: FiCheck, className: 'text-signal-500' },
  running:   { Icon: FiLoader, className: 'text-signal-500 animate-spin' },
  failed:    { Icon: FiX,     className: 'text-risk-500' },
  skipped:   { Icon: FiCheck, className: 'text-ink-400' },
  pending:   { Icon: FiCircle, className: 'text-ink-300' },
};

const LABEL_CLASS = {
  completed: 'text-ink-700',
  running:   'text-ink-900 font-medium',
  failed:    'text-risk-600',
  skipped:   'text-ink-500',
  pending:   'text-ink-500',
};

function PhaseHeroCard({ phase, stepDurations = {} }) {
  const steps = phase.steps ?? [];
  const completedCount = steps.filter(s => s.status === 'completed').length;
  const totalCount = steps.length;

  return (
    <div className="dossier-panel rounded-[2rem] p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold text-ink-900">{phase.name}</span>
        </div>
        <span className="mono-chip px-2.5 py-0.5">
          {completedCount}/{totalCount}
        </span>
      </div>

      {/* Step list */}
      <ul className="space-y-1">
        {steps.map(step => {
          const status = step.status ?? 'pending';
          const { Icon, className: iconClass } = STATUS_ICON[status] ?? STATUS_ICON.pending;
          const labelClass = LABEL_CLASS[status] ?? LABEL_CLASS.pending;
          const isRunning = status === 'running';

          // Right-side content
          let rightContent;
          if (status === 'completed') {
            rightContent = formatDuration(stepDurations[step.key] ?? step.duration_seconds);
          } else if (status === 'running') {
            rightContent = <span className="text-signal-600">运行中…</span>;
          } else if (status === 'failed') {
            rightContent = <span className="text-risk-500">失败</span>;
          } else if (status === 'skipped') {
            rightContent = <span className="text-ink-400">已跳过</span>;
          } else {
            rightContent = <span className="text-ink-400">—</span>;
          }

          return (
            <li
              key={step.key}
              className={[
                'h-11 flex items-center gap-3 rounded-xl transition-colors duration-150',
                isRunning
                  ? 'border-l-2 border-signal-500 bg-signal-50/40 pl-3 pr-3'
                  : 'px-3 hover:bg-ink-900/5',
              ].join(' ')}
            >
              {/* Status icon */}
              <span className={`flex-shrink-0 w-5 h-5 flex items-center justify-center ${iconClass}`}>
                <Icon className="w-full h-full" />
              </span>

              {/* Step label */}
              <span className={`flex-1 text-sm truncate ${labelClass}`}>
                {step.title}
              </span>

              {/* Right: duration or status text */}
              <span className="flex-shrink-0 text-xs font-mono">
                {rightContent}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

PhaseHeroCard.propTypes = {
  phase: PropTypes.shape({
    name:  PropTypes.string.isRequired,
    steps: PropTypes.arrayOf(PropTypes.shape({
      key:   PropTypes.string.isRequired,
      title: PropTypes.string.isRequired,
      status: PropTypes.string.isRequired,
      duration_seconds: PropTypes.number,
    })).isRequired,
  }).isRequired,
  stepDurations: PropTypes.object,
};

export default PhaseHeroCard;
