import PropTypes from 'prop-types';
import { FiCheck } from 'react-icons/fi';

function PhaseRail({ phases, phaseStatuses }) {
  return (
    <div className="flex w-full items-start justify-between px-2">
      {phases.map((phase, idx) => {
        const status = phaseStatuses[phase.name] || 'pending';
        const nextStatus = idx < phases.length - 1
          ? phaseStatuses[phases[idx + 1].name] || 'pending'
          : null;

        const isLast = idx === phases.length - 1;

        // Compute progress for this phase
        const completedSteps = phase.steps.filter((s) => s.status === 'completed').length;
        const totalSteps = phase.steps.length;

        // Dot styling
        const dotBase = 'flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all duration-300';
        const dotClass = status === 'completed'
          ? `${dotBase} bg-signal-500 text-white`
          : status === 'running'
            ? `${dotBase} bg-signal-50 text-signal-600 animate-pulse ring-4 ring-signal-500/20`
            : `${dotBase} border-2 border-ink-200 bg-white text-ink-400`;

        // Line styling
        let lineClass = 'mx-1 h-0.5 flex-1';
        if (status === 'completed' && nextStatus === 'completed') {
          lineClass += ' bg-signal-500';
        } else if (status === 'completed' && nextStatus === 'running') {
          lineClass += ' bg-gradient-to-r from-signal-500 to-signal-200';
        } else {
          lineClass += ' bg-ink-200 opacity-50';
        }

        // Label styling
        const labelClass = status === 'completed'
          ? 'mt-1.5 text-center text-[11px] font-medium text-signal-600'
          : status === 'running'
            ? 'mt-1.5 text-center text-[11px] font-semibold text-signal-700'
            : 'mt-1.5 text-center text-[11px] font-medium text-ink-500';

        return (
          <div key={phase.name} className="flex flex-1 items-start">
            <div className="flex flex-col items-center">
              <div className={dotClass}>
                {status === 'completed' ? <FiCheck className="h-4 w-4" /> : null}
              </div>
              <span className={labelClass}>
                {phase.name}
                {totalSteps > 0 && (
                  <span className="block text-[10px] opacity-70">
                    {completedSteps}/{totalSteps}
                  </span>
                )}
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
  phaseStatuses: PropTypes.objectOf(PropTypes.oneOf(['completed', 'running', 'pending'])).isRequired,
};

export default PhaseRail;
