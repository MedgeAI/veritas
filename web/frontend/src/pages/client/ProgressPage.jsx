import { useEffect, useMemo, useState } from 'react';
import { FiInfo } from 'react-icons/fi';
import { useRunSteps } from '../../hooks/useRunSteps.js';
import { getRun } from '../../services/api.js';
import StepRow from '../../components/client/StepRow.jsx';

/**
 * ProgressPage — client-facing progress page.
 *
 * Uses useRunSteps hook for real-time step updates.
 * Visual layout matches prototype ProgressPage.
 */
export default function ProgressPage({ caseId, runId, onNavigate }) {
  const { steps, progress, loading, error } = useRunSteps(caseId, runId);
  const [runMeta, setRunMeta] = useState(null);

  useEffect(() => {
    if (!caseId || !runId) return;
    let cancelled = false;
    getRun(caseId, runId).then((data) => {
      if (!cancelled) setRunMeta(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [caseId, runId]);

  const paperTitle = runMeta?.paper_title || runMeta?.case?.paper_title || '—';
  const estimatedTime = useMemo(() => {
    if (!progress.total) return '—';
    const completed = progress.completed || 0;
    const remaining = progress.total - completed;
    if (remaining <= 0) return '即将完成';
    const mins = Math.max(5, remaining * 8);
    return `约 ${Math.ceil(mins / 60)} 小时 ${mins % 60} 分`;
  }, [progress]);

  if (!caseId || !runId) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <p className="font-display text-2xl text-ink-500">请选择一个项目以查看进度</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <div className="font-display text-2xl text-ink-500">加载中…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <div className="font-display text-xl text-risk-500">加载失败</div>
        <div className="mt-2 text-sm text-ink-500">{error.message}</div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* Hero block */}
      <div className="mb-16">
        <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-ink-500">
          核查进行中 · Verification in progress
        </div>
        <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
          正在为您的稿件出具<br />
          <em className="font-normal text-accent-500" style={{ fontStyle: 'italic' }}>独立核查报告</em>
        </h1>
      </div>

      {/* MetaGrid */}
      <div className="mb-16 grid grid-cols-1 gap-8 md:grid-cols-3">
        <MetaCol label="稿件" value={paperTitle} />
        <MetaCol label="核查编号" value={runId} mono />
        <MetaCol label="预计剩余" value={estimatedTime} />
      </div>

      <div className="my-16 h-px bg-ink-100" />

      {/* Vertical timeline */}
      <div>
        {steps.length === 0 ? (
          <div className="py-12 text-center text-ink-500">等待步骤…</div>
        ) : (
          steps.map((step, i) => {
            const num = String(i + 1).padStart(2, '0');
            const time = step.duration_seconds
              ? `${Math.floor(step.duration_seconds / 60)} 分 ${step.duration_seconds % 60} 秒`
              : step.status === 'running'
                ? '进行中'
                : null;
            const log = step.log ? (Array.isArray(step.log) ? step.log : [step.log]) : null;
            return (
              <StepRow
                key={step.key || step.step_id || i}
                number={num}
                label={step.title || step.name || '—'}
                labelEn={step.phase || ''}
                status={step.status || 'pending'}
                detail={step.detail || step.description || ''}
                time={time}
                log={log}
              />
            );
          })
        )}
      </div>

      {/* Bottom note */}
      <div className="mt-12 flex items-start gap-3 rounded-sm border border-ink-100 bg-paper-100/40 px-5 py-4">
        <FiInfo size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-500" aria-hidden="true" />
        <span className="text-[13px] leading-relaxed text-ink-700">
          核查需要数小时是设计的诚实承诺——我们真的在重跑您的代码，而不是仅扫描文本。
        </span>
      </div>

      {/* Completed: navigate to report */}
      {progress.progress_pct >= 100 && (
        <div className="mt-8 flex justify-center">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-full bg-ink-900 px-6 py-3 text-sm font-semibold text-paper-50 transition hover:-translate-y-0.5 hover:shadow-lg"
            onClick={() => onNavigate?.('report', { case: caseId, run: runId })}
          >
            查看报告
          </button>
        </div>
      )}
    </div>
  );
}

function MetaCol({ label, value, mono }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[2px] text-ink-500">{label}</div>
      <div className={`mt-2 text-[15px] text-ink-900 ${mono ? 'font-mono' : ''}`}>
        {value}
      </div>
    </div>
  );
}
