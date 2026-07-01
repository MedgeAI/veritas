import { useEffect, useMemo, useRef, useState } from 'react';
import { FiInfo, FiArrowRight } from 'react-icons/fi';
import { useRunSteps } from '../../hooks/useRunSteps.js';
import { getRun } from '../../services/api.js';
import StepRow from '../../components/client/StepRow.jsx';
import ClientEmptyState from '../../components/client/ClientEmptyState.jsx';

const italicStyle = { fontStyle: 'italic' };

/**
 * ProgressPage — client-facing progress page.
 *
 * State machine:  loading → running → completed | failed
 *
 * Each state maps to a distinct Hero section and step display behavior.
 * Auto-navigates to report ONLY on first completion (user was watching).
 * Returning to the page after completion shows CompletedHero with CTA.
 */
export default function ProgressPage({ caseId, runId, onNavigate }) {
  const { steps, progress, loading, error } = useRunSteps(caseId, runId);
  const [runMeta, setRunMeta] = useState(null);

  // ── Derive page state from progress/error ──────────────────────────
  const pageState = useMemo(() => {
    if (loading) return 'loading';
    if (error) return 'failed';
    if (progress.timing_status === 'complete') return 'completed';
    if (['failed', 'cancelled'].includes(progress.timing_status)) return 'failed';
    if (['completed', 'completed_with_warnings', 'partial_available'].includes(progress.run_status)) {
      return 'completed';
    }
    if (progress.run_status?.startsWith('failed') || progress.run_status === 'interrupted') {
      return 'failed';
    }
    if (progress.progress_pct >= 100) return 'completed';
    return 'running';
  }, [loading, error, progress.progress_pct, progress.run_status, progress.timing_status]);

  // ── Run metadata ───────────────────────────────────────────────────
  useEffect(() => {
    if (!caseId || !runId) return;
    let cancelled = false;
    getRun(caseId, runId).then((data) => {
      if (!cancelled) setRunMeta(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [caseId, runId]);

  const paperTitle = runMeta?.paper_title || runMeta?.case?.paper_title || '—';

  // ── Auto-navigate on first completion ──────────────────────────────
  // Only redirect when user was watching (saw running → completed transition).
  // If user navigates back to ProgressPage after completion, show CompletedHero.
  const hasSeenRunning = useRef(false);
  const hasAutoNavigated = useRef(false);

  if (pageState === 'running') hasSeenRunning.current = true;

  useEffect(() => {
    if (pageState !== 'completed') return;
    if (!hasSeenRunning.current || hasAutoNavigated.current) return;
    hasAutoNavigated.current = true;
    const timer = setTimeout(() => {
      onNavigate?.('report', { case: caseId, run: runId });
    }, 3000);
    return () => clearTimeout(timer);
  }, [pageState, caseId, runId, onNavigate]);

  const runtimeStatus = useMemo(
    () => buildRuntimeStatus(progress, pageState),
    [progress, pageState],
  );

  // ── Completed steps count for summary ──────────────────────────────
  const completedCount = steps.filter((s) => s.status === 'done' || s.status === 'completed').length;
  const totalSteps = steps.length || progress.total || 0;

  if (!caseId || !runId) {
    return <ClientEmptyState type="progress" caseId={caseId} onNavigate={onNavigate} />;
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <div className="font-display text-2xl text-ink-500">加载中…</div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* ── Hero: state-driven ──────────────────────────────────────── */}
      {pageState === 'completed' && (
        <CompletedHero
          paperTitle={paperTitle}
          completedCount={completedCount}
          totalSteps={totalSteps}
          onNavigate={() => onNavigate?.('report', { case: caseId, run: runId })}
        />
      )}
      {pageState === 'failed' && (
        <FailedHero
          paperTitle={paperTitle}
          error={error?.message || '核查流水线异常终止'}
          onRetry={() => onNavigate?.('submit')}
        />
      )}
      {pageState === 'running' && (
        <RunningHero paperTitle={paperTitle} progress={progress} />
      )}

      {/* ── MetaGrid ────────────────────────────────────────────────── */}
      <div className="mb-16 grid grid-cols-1 gap-8 md:grid-cols-3">
        <MetaCol label="稿件" value={paperTitle} />
        <MetaCol label="核查编号" value={runId} mono />
        <MetaCol label={pageState === 'running' ? '运行状态' : '状态'} value={<RuntimeStatus status={runtimeStatus} />} />
      </div>

      <div className="my-16 h-px bg-ink-100" />

      {/* ── Vertical timeline ───────────────────────────────────────── */}
      <div>
        {steps.length === 0 ? (
          <div className="py-12 text-center text-ink-500">等待步骤…</div>
        ) : (
          steps.map((step, i) => {
            const num = String(i + 1).padStart(2, '0');
            const time = formatStepTime(step);
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

      {/* ── Bottom note (only during running) ───────────────────────── */}
      {pageState === 'running' && (
        <div className="mt-12 flex items-start gap-3 rounded-sm border border-ink-100 bg-paper-100/40 px-5 py-4">
          <FiInfo size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-500" aria-hidden="true" />
          <span className="text-[13px] leading-relaxed text-ink-700">
            Agent 驱动核查会分支、重试或等待外部工具，耗时波动较大；当前显示为运行事实，不做精确剩余时间承诺。
          </span>
        </div>
      )}
    </div>
  );
}

// ── Step time formatting ─────────────────────────────────────────────
function formatStepTime(step) {
  if (step.status === 'done' || step.status === 'completed') {
    if (step.duration_seconds != null) {
      const m = Math.floor(step.duration_seconds / 60);
      const s = step.duration_seconds % 60;
      return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`;
    }
    return '';
  }
  if (step.status === 'running') return '处理中…';
  if (step.status === 'warning') return '需复核';
  if (step.status === 'failed') return '失败';
  if (step.status === 'skipped') return '跳过';
  return '';
}

function buildRuntimeStatus(progress, pageState) {
  const elapsed = formatRuntimeDuration(progress.elapsed_seconds);
  const eventAge = formatEventAge(progress.seconds_since_last_event);
  const currentStep = progress.current_step;
  const latestStep = progress.latest_step;
  const commonDetail = [
    elapsed ? `已运行 ${elapsed}` : null,
    eventAge ? `最近事件 ${eventAge}` : null,
  ].filter(Boolean).join(' · ');

  if (pageState === 'completed') {
    return {
      tone: 'success',
      title: '已完成',
      detail: elapsed ? `总运行 ${elapsed}` : '报告已就绪',
    };
  }

  if (pageState === 'failed') {
    return {
      tone: 'danger',
      title: '已中止',
      detail: commonDetail || '流水线异常终止',
    };
  }

  if (progress.timing_status === 'stale') {
    return {
      tone: 'warning',
      title: '等待新事件',
      detail: commonDetail || '任务仍未进入终态',
    };
  }

  if (progress.timing_status === 'queued') {
    return {
      tone: 'muted',
      title: '排队中',
      detail: commonDetail || '等待执行资源',
    };
  }

  if (progress.timing_status === 'waiting') {
    const latest = latestStep?.title ? `上一阶段：${latestStep.title}` : null;
    return {
      tone: 'muted',
      title: '等待下一步',
      detail: [latest, commonDetail].filter(Boolean).join(' · ') || '任务仍在运行',
    };
  }

  if (currentStep?.title) {
    return {
      tone: 'active',
      title: `正在处理：${currentStep.title}`,
      detail: [currentStep.detail, currentStep.phase, commonDetail].filter(Boolean).join(' · '),
    };
  }

  return {
    tone: 'active',
    title: '运行中',
    detail: commonDetail || '正在接收运行事件',
  };
}

function RuntimeStatus({ status }) {
  const toneClass = {
    active: 'text-ink-900',
    success: 'text-[#5a6b46]',
    danger: 'text-risk-700',
    warning: 'text-[#8a5a00]',
    muted: 'text-ink-700',
  }[status.tone] || 'text-ink-900';

  return (
    <div className="space-y-1">
      <div className={`break-words font-medium leading-snug ${toneClass}`}>
        {status.title}
      </div>
      {status.detail && (
        <div className="break-words text-[12px] leading-relaxed text-ink-500">
          {status.detail}
        </div>
      )}
    </div>
  );
}

function formatRuntimeDuration(seconds) {
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
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const safeSeconds = Math.max(0, Math.floor(Number(seconds)));
  if (safeSeconds <= 5) return '刚刚';
  if (safeSeconds < 60) return `${safeSeconds} 秒前`;
  const minutes = Math.floor(safeSeconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours} 小时 ${remainingMinutes} 分钟前` : `${hours} 小时前`;
}

// ── Hero components (state-driven) ───────────────────────────────────

function RunningHero({ progress }) {
  return (
    <div className="mb-16">
      <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-ink-500">
        核查进行中 · Verification in progress
      </div>
      <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
        正在为您的稿件<br />
        <em className="font-normal text-accent-500" style={italicStyle}>出具独立核查报告</em>
      </h1>
      {/* Progress bar */}
      {progress.total > 0 && (
        <div className="mt-8">
          <div className="mb-2 flex items-center justify-between text-[11px] text-ink-500">
            <span>{progress.completed} / {progress.total} 步骤</span>
            <span>{progress.progress_pct}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-ink-100">
            <div
              className="h-full rounded-full bg-ink-900 transition-all duration-500"
              style={{ width: `${progress.progress_pct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function CompletedHero({ completedCount, totalSteps, onNavigate }) {
  return (
    <div className="mb-16">
      <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-[#5a6b46]">
        核查完成 · Verification complete
      </div>
      <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
        您的稿件<br />
        <em className="font-normal text-[#5a6b46]" style={italicStyle}>核查报告已就绪</em>
      </h1>
      <div className="mt-6 text-sm text-ink-500">
        {completedCount} / {totalSteps} 步骤已完成
      </div>
      {/* CTA */}
      <div className="mt-8">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-sm bg-ink-900 px-6 py-3 text-sm font-semibold text-paper-50 transition hover:-translate-y-0.5 hover:shadow-lg"
          onClick={onNavigate}
        >
          查看报告 <FiArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}

function FailedHero({ error, onRetry }) {
  return (
    <div className="mb-16">
      <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-risk-500">
        核查中止 · Verification failed
      </div>
      <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
        核查未能<br />
        <em className="font-normal text-risk-500" style={italicStyle}>完成</em>
      </h1>
      <div className="mt-6 max-w-lg rounded-sm border border-risk-200/50 bg-risk-50/50 px-5 py-4 text-sm text-risk-700">
        {error}
      </div>
      <button
        type="button"
        className="mt-8 inline-flex items-center gap-2 rounded-sm border border-ink-900 px-5 py-2.5 text-xs text-ink-900 hover:bg-paper-100"
        onClick={onRetry}
      >
        重新提交
      </button>
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
