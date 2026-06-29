import { useState } from 'react';
import { FiClock, FiEye, FiFileText, FiX } from 'react-icons/fi';

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

function truncateId(id) {
  if (!id) return '—';
  return id.length > 12 ? `${id.slice(0, 12)}…` : id;
}

function getActiveStage(job) {
  if (!job?.stages) return '—';
  const running = job.stages.find(s => s.status === 'running');
  if (running) return running.label || running.id || 'Running';
  const lastCompleted = job.stages.filter(s => s.status === 'completed').pop();
  if (lastCompleted) return lastCompleted.label || lastCompleted.id || 'Completed';
  return '—';
}

function AuditTaskList({ jobs, onRefresh, onView, onCancel, onViewReport }) {
  const [cancellingJobId, setCancellingJobId] = useState(null);

  if (!jobs || jobs.length === 0) {
    return (
      <div className="dossier-panel rounded-2xl border p-8 text-center">
        <p className="text-sm text-ink-500">No audit jobs found</p>
        {onRefresh && (
          <button type="button" className="btn-ghost mt-3" onClick={onRefresh}>
            Refresh
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="dossier-panel overflow-hidden rounded-2xl border">
      <div className="flex items-center justify-between border-b border-ink-900/10 bg-paper-100/60 px-5 py-3">
        <h3 className="text-sm font-semibold text-ink-900">Audit Tasks</h3>
        {onRefresh && (
          <button type="button" className="btn-ghost text-xs" onClick={onRefresh}>
            Refresh
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-ink-900/10 bg-paper-100/40 text-left text-xs font-semibold uppercase tracking-wide text-ink-500">
              <th className="px-5 py-3">Job ID</th>
              <th className="px-5 py-3">Case</th>
              <th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Stage</th>
              <th className="px-5 py-3">Duration</th>
              <th className="px-5 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const jobId = job.job_id || job.id;
              const status = job.status || 'queued';
              const canCancel = status === 'queued' || status === 'running';
              const badgeClass = STATUS_BADGE[status] || STATUS_BADGE.queued;

              return (
                <tr key={jobId} className="border-b border-ink-900/5 text-sm hover:bg-paper-100/30">
                  <td className="px-5 py-3 font-mono text-xs text-ink-500">
                    {truncateId(jobId)}
                  </td>
                  <td className="px-5 py-3 text-ink-700">
                    {job.case_id || '—'}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-bold ${badgeClass}`}>
                      {STATUS_LABEL[status] || status}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-sm text-ink-500">
                    {getActiveStage(job)}
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-ink-500">
                    <span className="flex items-center gap-1">
                      <FiClock aria-hidden="true" className="h-3 w-3" />
                      {formatDuration(job.duration)}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center justify-end gap-2">
                      {onView && (
                        <button
                          type="button"
                          className="btn-ghost inline-flex items-center gap-1 text-xs"
                          onClick={() => onView(job)}
                          title="View details"
                        >
                          <FiEye aria-hidden="true" className="h-3 w-3" />
                          View
                        </button>
                      )}
                      {canCancel && onCancel && (
                        cancellingJobId === jobId ? (
                          <div className="flex items-center gap-1.5 rounded-lg border border-risk-400/30 bg-risk-50 px-2 py-1 text-xs">
                            <span className="text-risk-700 whitespace-nowrap">确定取消？</span>
                            <button
                              type="button"
                              className="rounded-md bg-risk-600 px-2 py-0.5 font-semibold text-white hover:bg-risk-700"
                              onClick={() => { onCancel(job); setCancellingJobId(null); }}
                            >
                              确定
                            </button>
                            <button
                              type="button"
                              className="btn-ghost py-0.5 text-risk-600 hover:text-risk-700"
                              onClick={() => setCancellingJobId(null)}
                            >
                              返回
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="btn-ghost inline-flex items-center gap-1 text-xs text-risk-600 hover:text-risk-700"
                            onClick={() => setCancellingJobId(jobId)}
                            title="Cancel job"
                          >
                            <FiX aria-hidden="true" className="h-3 w-3" />
                            Cancel
                          </button>
                        )
                      )}
                      {status === 'completed' && onViewReport && (
                        <button
                          type="button"
                          className="btn-primary inline-flex items-center gap-1 text-xs"
                          onClick={() => onViewReport(job)}
                          title="View report"
                        >
                          <FiFileText aria-hidden="true" className="h-3 w-3" />
                          Report
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default AuditTaskList;
