import PropTypes from 'prop-types';
import {
  FiAlertTriangle,
  FiCheck,
  FiCircle,
  FiLoader,
  FiMinusCircle,
  FiX,
} from 'react-icons/fi';
import { PHASE_STATUS_VALUES } from '../../utils/progressPhases.js';

const STATUS_LABEL = {
  completed: '完成',
  failed: '失败',
  pending: '等待中',
  running: '运行中',
  skipped: '已跳过',
  warning: '需复核',
};

const STATUS_ICON = {
  completed: FiCheck,
  failed: FiX,
  pending: FiCircle,
  running: FiLoader,
  skipped: FiMinusCircle,
  warning: FiAlertTriangle,
};

function PhaseRail({ phases, phaseStatuses, currentPhaseName }) {
  return (
    <div className="flex w-full flex-col gap-3 px-2 sm:flex-row sm:items-start sm:justify-between">
      {phases.map((phase, idx) => {
        const status = phaseStatuses[phase.name] || 'pending';
        const nextStatus = idx < phases.length - 1
          ? phaseStatuses[phases[idx + 1].name] || 'pending'
          : null;

        const isLast = idx === phases.length - 1;
        const isCurrent = phase.name === currentPhaseName;
        const Icon = STATUS_ICON[status] || FiCircle;

        // Dot styling
        const dotBase = [
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all duration-300',
          isCurrent ? 'ring-4 ring-signal-500/20' : '',
        ].filter(Boolean).join(' ');
        const dotClass = status === 'completed'
          ? `${dotBase} bg-signal-500 text-white`
          : status === 'running'
            ? `${dotBase} bg-signal-50 text-signal-600 animate-pulse`
            : status === 'failed'
              ? `${dotBase} bg-risk-500 text-white`
              : status === 'warning'
                ? `${dotBase} bg-[#fff7e6] text-[#8a5a00] border border-[#d69a2d]/40`
                : status === 'skipped'
                  ? `${dotBase} border-2 border-ink-200 bg-white text-ink-400`
                  : `${dotBase} border-2 border-ink-200 bg-white text-ink-400`;

        // Line styling
        let lineClass = 'hidden sm:block sm:mx-1 sm:mt-4 sm:h-0.5 sm:flex-1';
        if (status === 'completed' && nextStatus === 'completed') {
          lineClass += ' bg-signal-500';
        } else if (status === 'completed' && nextStatus === 'running') {
          lineClass += ' bg-gradient-to-r from-signal-500 to-signal-200';
        } else if (status === 'failed') {
          lineClass += ' bg-risk-200';
        } else if (status === 'warning') {
          lineClass += ' bg-[#d69a2d]/40';
        } else {
          lineClass += ' bg-ink-200 opacity-50';
        }

        // Label styling
        const labelClass = status === 'completed'
          ? 'mt-1.5 text-center text-[11px] font-medium text-signal-600'
          : status === 'running'
            ? 'mt-1.5 text-center text-[11px] font-semibold text-signal-700'
            : status === 'failed'
              ? 'mt-1.5 text-center text-[11px] font-semibold text-risk-600'
              : status === 'warning'
                ? 'mt-1.5 text-center text-[11px] font-semibold text-[#8a5a00]'
                : 'mt-1.5 text-center text-[11px] font-medium text-ink-500';

        return (
          <div key={phase.name} className="flex flex-1 items-start sm:min-w-0">
            <div className="flex flex-row items-center gap-3 sm:flex-col sm:gap-0">
              <div className={dotClass}>
                <Icon className={`h-4 w-4 ${status === 'running' ? 'animate-spin' : ''}`} />
              </div>
              <span className={labelClass}>
                {phase.name}
                <span className="block text-[10px] opacity-70">
                  {STATUS_LABEL[status] || STATUS_LABEL.pending}
                </span>
              </span>
            </div>

            {!isLast && <div className={lineClass} />}
          </div>
        );
      })}
    </div>
  );
}

PhaseRail.propTypes = {
  phases: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string.isRequired,
      steps: PropTypes.array.isRequired,
    }),
  ).isRequired,
  phaseStatuses: PropTypes.objectOf(PropTypes.oneOf(PHASE_STATUS_VALUES)).isRequired,
  currentPhaseName: PropTypes.string,
};

export default PhaseRail;
