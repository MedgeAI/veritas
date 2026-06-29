import { useEffect, useMemo, useState } from 'react';
import { FiCheck, FiCircle, FiClock, FiLoader, FiMinus, FiX } from 'react-icons/fi';

const STATUS_STYLES = {
  queued: 'border-caution-400/40 bg-caution-50 text-caution-700',
  running: 'border-signal-400/40 bg-signal-50 text-signal-700',
  completed: 'border-green-400/40 bg-green-50 text-green-700',
  failed: 'border-risk-400/40 bg-risk-50 text-risk-700',
  cancelled: 'border-ink-900/10 bg-ink-100/40 text-ink-500',
};

const STATUS_BADGE = {
  queued: 'border-caution-500/30 bg-caution-100 text-caution-700',
  running: 'border-signal-500/30 bg-signal-100 text-signal-700',
  completed: 'border-green-500/30 bg-green-100 text-green-700',
  failed: 'border-risk-500/30 bg-risk-100 text-risk-700',
  cancelled: 'border-ink-900/10 bg-ink-100/60 text-ink-500',
};

const STATUS_LABEL = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

function StageIcon({ status }) {
  switch (status) {
    case 'completed':
      return <FiCheck aria-hidden="true" className="h-4 w-4 text-green-600" />;
    case 'running':
      return <FiLoader aria-hidden="true" className="h-4 w-4 animate-spin text-signal-600" />;
    case 'skipped':
      return <FiMinus aria-hidden="true" className="h-4 w-4 text-ink-500" />;
    default:
      return <FiCircle aria-hidden="true" className="h-4 w-4 text-ink-300" />;
  }
}

function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return '—';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${rem}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function AuditProgressBar({ job, onCancel }) {
  const [elapsed, setElapsed] = useState(() => computeElapsed(job));
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const status = job?.status || 'queued';
  const stages = useMemo(() => (Array.isArray(job?.stages) ? job.stages : []), [job]);
  const canCancel = status === 'queued' || status === 'running';

  useEffect(() => {
    if (!job?.started_at && status !== 'running' && status !== 'queued') return;
    setElapsed(computeElapsed(job));
    const timer = setInterval(() => setElapsed(computeElapsed(job)), 1000);
    return () => clearInterval(timer);
  }, [job?.started_at, job?.finished_at, status]);

  const completedCount = stages.filter(s => s.status === 'completed' || s.status === 'skipped').length;
  const totalCount = stages.length;
  const progress = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
  const badgeClass = STATUS_BADGE[status] || STATUS_BADGE.queued;

  return (
    <div className={`dossier-panel rounded-2xl border p-5 ${STATUS_STYLES[status] || STATUS_STYLES.queued}`} role="status" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-bold ${badgeClass}`}>
            {STATUS_LABEL[status] || status}
          </span>
          {job?.case_id && (
            <span className="font-mono text-xs text-ink-500">
              case {job.case_id}
            </span>
          )}
          <span className="flex items-center gap-1 text-xs text-ink-500">
            <FiClock aria-hidden="true" className="h-3 w-3" />
            {formatDuration(elapsed)}
          </span>
        </div>

        {canCancel && onCancel && (
          showCancelConfirm ? (
            <div className="flex items-center gap-2 rounded-xl border border-risk-400/30 bg-risk-50 px-3 py-2 text-xs">
              <span className="text-risk-700">确定要取消此审计任务吗？</span>
              <button
                type="button"
                className="rounded-lg bg-risk-600 px-2.5 py-1 font-semibold text-white hover:bg-risk-700"
                onClick={() => { onCancel(job); setShowCancelConfirm(false); }}
              >
                确定取消
              </button>
              <button
                type="button"
                className="btn-ghost text-risk-600 hover:text-risk-700"
                onClick={() => setShowCancelConfirm(false)}
              >
                返回
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn-ghost inline-flex items-center gap-1.5 text-risk-600 hover:text-risk-700"
              onClick={() => setShowCancelConfirm(true)}
            >
              <FiX aria-hidden="true" className="h-3.5 w-3.5" />
              Cancel
            </button>
          )
        )}
      </div>

      {/* Progress bar */}
      <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-ink-900/5" role="progressbar" aria-label="审计任务进度" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            status === 'completed' ? 'bg-green-500'
              : status === 'failed' ? 'bg-risk-500'
                : status === 'cancelled' ? 'bg-ink-500'
                  : 'bg-signal-500'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Stages */}
      {totalCount > 0 && (
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5">
          {stages.map((stage, idx) => (
            <div key={stage.id || idx} className="flex items-center gap-1.5 text-xs">
              <StageIcon status={stage.status} />
              <span className={
                stage.status === 'completed' ? 'text-ink-500'
                  : stage.status === 'running' ? 'font-semibold text-ink-900'
                    : 'text-ink-500'
              }>
                {stage.label || stage.id || `Stage ${idx + 1}`}
              </span>
            </div>
          ))}
        </div>
      )}

      {totalCount > 0 && (
        <p className="mt-2 font-mono text-[11px] text-ink-500">
          {completedCount} / {totalCount} stages — {progress}%
        </p>
      )}
    </div>
  );
}

function computeElapsed(job) {
  if (!job) return null;
  const start = job.started_at ? new Date(job.started_at).getTime() : null;
  if (!start) return null;
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  return Math.max(0, (end - start) / 1000);
}

export default AuditProgressBar;
