import { useEffect, useMemo, useRef, useState } from 'react';
import {
  FiAlertCircle,
  FiAlertTriangle,
  FiArrowRight,
  FiCheck,
  FiChevronDown,
  FiChevronRight,
  FiCircle,
  FiLoader,
  FiMinusCircle,
  FiX,
} from 'react-icons/fi';
import { useRunSteps } from '../../hooks/useRunSteps.js';
import { getRun } from '../../services/api.js';
import StepRow from '../../components/client/StepRow.jsx';
import ClientEmptyState from '../../components/client/ClientEmptyState.jsx';
import {
  buildPhaseStatuses,
  findCurrentPhase,
  groupStepsByPhase,
} from '../../utils/progressPhases.js';

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
    return 'running';
  }, [loading, error, progress.run_status, progress.timing_status]);

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

  // ── Phase grouping ─────────────────────────────────────────────────
  const phases = useMemo(() => groupStepsByPhase(steps), [steps]);
  const phaseStatuses = useMemo(() => buildPhaseStatuses(phases), [phases]);
  const currentPhase = useMemo(
    () => findCurrentPhase(phases, phaseStatuses),
    [phases, phaseStatuses],
  );
  const stepNumbers = useMemo(() => {
    return new Map(
      steps.map((step, index) => [
        step.key || step.step_id || `step-${index}`,
        String(index + 1).padStart(2, '0'),
      ]),
    );
  }, [steps]);

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
          <div className="space-y-6">
            {phases.map((phase) => (
              <PhaseGroup
                key={phase.name}
                phase={phase}
                status={phaseStatuses[phase.name] || 'pending'}
                current={phase.name === currentPhase?.name}
              >
                {phase.steps.map((step, i) => {
                  const stepKey = step.key || step.step_id || `step-${i}`;
                  const time = formatStepTime(step);
                  const log = step.log ? (Array.isArray(step.log) ? step.log : [step.log]) : null;
                  return (
                    <StepRow
                      key={stepKey}
                      number={stepNumbers.get(stepKey) || String(i + 1).padStart(2, '0')}
                      label={step.title || step.name || '—'}
                      labelEn={step.phase || ''}
                      status={step.status || 'pending'}
                      detail={step.detail || step.description || ''}
                      time={time}
                      log={log}
                    />
                  );
                })}
              </PhaseGroup>
            ))}
          </div>
        )}
      </div>

      {/* ── Bottom note (only during running) ───────────────────────── */}
      {pageState === 'running' && (
        <RunNote progress={progress} />
      )}
    </div>
  );
}

const PHASE_STATUS_LABEL = {
  completed: '完成',
  failed: '失败',
  pending: '等待中',
  running: '运行中',
  skipped: '已跳过',
  warning: '需复核',
};

const PHASE_STATUS_ICON = {
  completed: FiCheck,
  failed: FiX,
  pending: FiCircle,
  running: FiLoader,
  skipped: FiMinusCircle,
  warning: FiAlertTriangle,
};

function PhaseGroup({ phase, status, current, children }) {
  const [expanded, setExpanded] = useState(current || status === 'failed' || status === 'warning');

  useEffect(() => {
    if (current || status === 'failed' || status === 'warning') {
      setExpanded(true);
    }
  }, [current, status]);

  const StatusIcon = PHASE_STATUS_ICON[status] || FiCircle;
  const toneClass = {
    completed: 'text-[#5a6b46]',
    failed: 'text-risk-700',
    pending: 'text-ink-500',
    running: 'text-accent-500',
    skipped: 'text-ink-500',
    warning: 'text-[#8a5a00]',
  }[status] || 'text-ink-500';

  return (
    <section className="border-t border-ink-100 pt-5">
      <button
        type="button"
        className="flex w-full items-center gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        {expanded ? (
          <FiChevronDown className="h-4 w-4 shrink-0 text-ink-500" aria-hidden="true" />
        ) : (
          <FiChevronRight className="h-4 w-4 shrink-0 text-ink-500" aria-hidden="true" />
        )}
        <StatusIcon
          className={`h-4 w-4 shrink-0 ${toneClass} ${status === 'running' ? 'animate-spin' : ''}`}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 text-[15px] font-medium text-ink-900">
          {phase.name}
        </span>
        <span className={`shrink-0 text-[12px] ${toneClass}`}>
          {PHASE_STATUS_LABEL[status] || PHASE_STATUS_LABEL.pending}
        </span>
      </button>

      {expanded && (
        <div className="mt-5">
          {children}
        </div>
      )}
    </section>
  );
}

function RunNote({ progress }) {
  if (progress.is_stale) {
    const eventAge = formatEventAge(progress.seconds_since_last_event);
    return (
      <div className="mt-12 flex items-start gap-3 rounded-sm border border-[#d69a2d]/30 bg-[#fff7e6] px-5 py-4">
        <FiAlertCircle size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-[#8a5a00]" aria-hidden="true" />
        <span className="text-[13px] leading-relaxed text-[#7a4e00]">
          等待外部服务响应，可能正在处理 MinerU PDF 解析、视觉取证或模型调用。
          {eventAge ? ` 最后事件: ${eventAge}` : ''}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-12 flex items-start gap-3 rounded-sm border border-ink-100 bg-paper-100/40 px-5 py-4">
      <FiCircle size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-500" aria-hidden="true" />
      <span className="text-[13px] leading-relaxed text-ink-700">
        Agent 驱动核查会分支、重试或等待外部工具，耗时波动较大；当前显示为运行事实，不做精确剩余时间承诺。
      </span>
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
  const elapsed = formatRuntimeDuration(progress.elapsed_seconds);
  const currentStep = progress.current_step?.title || progress.current_step?.key;
  const currentPhase = progress.current_step?.phase;

  return (
    <div className="mb-16">
      <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-ink-500">
        核查进行中 · Verification in progress
      </div>
      <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
        正在为您的稿件<br />
        <em className="font-normal text-accent-500" style={italicStyle}>出具独立核查报告</em>
      </h1>
      {(elapsed || currentStep || currentPhase) && (
        <div className="mt-8 max-w-2xl text-[15px] leading-7 text-ink-600">
          {currentPhase ? `当前阶段：${currentPhase}` : '正在初始化阶段'}
          {elapsed ? ` · 已用时 ${elapsed}` : ''}
          {currentStep ? ` · 当前：${currentStep}` : ''}
        </div>
      )}
    </div>
  );
}

function CompletedHero({ onNavigate }) {
  return (
    <div className="mb-16">
      <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-[#5a6b46]">
        核查完成 · Verification complete
      </div>
      <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
        您的稿件<br />
        <em className="font-normal text-[#5a6b46]" style={italicStyle}>核查报告已就绪</em>
      </h1>
      <div className="mt-6 text-sm text-ink-500">报告已生成，可查看完整证据与复核建议。</div>
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
