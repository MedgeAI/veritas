import PropTypes from 'prop-types';
import { FiCheck, FiX } from 'react-icons/fi';

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m} 分 ${s} 秒`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h} 时 ${m} 分`;
}

export default function CompletionSummary({
  totalDuration,
  failedSteps,
  onViewReport,
}) {
  const hasFailures = failedSteps > 0;

  return (
    <div className="dossier-panel rounded-2xl p-8 text-center" role="status" aria-live="polite">
      <div className="flex flex-col items-center space-y-4">
        {/* Success / failure icon */}
        <div
          className={`w-16 h-16 mx-auto rounded-full flex items-center justify-center ${
            hasFailures ? 'bg-risk-100' : 'bg-signal-100'
          }`}
        >
          {hasFailures ? (
            <FiX className="w-8 h-8 text-risk-600" aria-hidden="true" />
          ) : (
            <FiCheck className="w-8 h-8 text-signal-600" aria-hidden="true" />
          )}
        </div>

        {/* Title */}
        <h2 className="text-xl font-semibold text-ink-900">
          {hasFailures ? '审查完成（部分步骤失败）' : '审查完成'}
        </h2>

        {/* Stats row */}
        <div className="flex justify-center gap-6">
          <span className="text-sm text-ink-600">
            耗时 {formatDuration(totalDuration)}
          </span>
          {hasFailures ? (
            <span className="text-sm text-risk-600">
              {failedSteps} 个步骤需要复核
            </span>
          ) : (
            <span className="text-sm text-ink-600">报告已就绪</span>
          )}
        </div>

        {/* Action button */}
        {onViewReport && (
          <button className="btn-primary mt-2" onClick={onViewReport}>
            查看报告
          </button>
        )}
      </div>
    </div>
  );
}

CompletionSummary.propTypes = {
  totalDuration: PropTypes.number,
  failedSteps: PropTypes.number,
  onViewReport: PropTypes.func,
};
