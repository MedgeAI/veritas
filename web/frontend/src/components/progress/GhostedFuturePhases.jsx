import PropTypes from 'prop-types';
import { FiCircle } from 'react-icons/fi';

export default function GhostedFuturePhases({ phases }) {
  if (!phases || phases.length === 0) return null;

  return (
    <div className="mt-4 opacity-50">
      {phases.map((phase) => (
        <div
          key={phase.id}
          className="h-9 flex items-center gap-3 px-4 rounded-xl"
        >
          <FiCircle className="w-4 h-4 text-ink-400" />
          <span className="text-sm text-ink-500">{phase.label}</span>
          <span className="text-xs text-ink-500 ml-auto">
            {phase.steps.length} 步
          </span>
        </div>
      ))}
    </div>
  );
}

GhostedFuturePhases.propTypes = {
  phases: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    icon: PropTypes.string.isRequired,
    steps: PropTypes.array.isRequired,
  })).isRequired,
};
