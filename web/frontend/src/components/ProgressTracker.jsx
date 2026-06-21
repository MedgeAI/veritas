import { FiCheck, FiFileText, FiImage, FiCpu, FiBookOpen, FiFile } from 'react-icons/fi';
import { reportHtmlUrl } from '../services/api.js';

const STEPS = [
  { id: 1, label: 'PDF 解析', description: '解析论文 PDF，提取图表与文本', icon: FiFileText, prefixes: ['mineru', 'evidence_ledger', 'numeric_forensics', 'paperfraud_rule_match'] },
  { id: 2, label: 'Source Data', description: '检测数据内部一致性与统计异常', icon: FiFile, prefixes: ['source_data_'] },
  { id: 3, label: '图像检测', description: 'Panel 提取、Copy-move、伪造检测', icon: FiImage, prefixes: ['image_', 'visual_', 'visual.', 'panel_', 'copy_move', 'trufor'] },
  { id: 4, label: '审查助手', description: '论断映射与结构化调查', icon: FiCpu, prefixes: ['agent_', 'claim_', 'investigation'] },
  { id: 5, label: '报告生成', description: '生成结构化证据与审查报告', icon: FiBookOpen, prefixes: ['static_audit_bundle', 'bundle', 'legacy_report', 'html_report', 'report'] },
];

const EVENT_TRANSLATIONS = {
  // PDF parsing
  mineru_parse_started: { label: '开始解析 PDF', tone: 'info' },
  mineru_parse_completed: { label: 'PDF 解析完成', tone: 'ok' },
  evidence_ledger_built: { label: (e) => `提取 ${e.figure_count || '?'} 个图表`, tone: 'ok' },
  numeric_forensics_completed: { label: (e) => `数值取证完成，${e.finding_count || '?'} 个发现`, tone: 'ok' },
  paperfraud_rule_match_completed: { label: 'PaperFraud 规则匹配完成', tone: 'ok' },

  // Source Data
  source_data_scan_started: { label: '开始检查 Source Data', tone: 'info' },
  source_data_scan_completed: { label: 'Source Data 检查完成', tone: 'ok' },
  source_data_duplicate_columns: { label: (e) => `重复列检出: ${(e.columns || []).join(', ')} (sheet: ${e.sheet || '?'})`, tone: 'warn' },
  source_data_fixed_ratio: { label: (e) => `固定比例: ${(e.columns || []).join(' / ')} 在 ${e.row_count || '?'} 行满足`, tone: 'warn' },
  source_data_fixed_difference: { label: (e) => `固定差值: ${(e.columns || []).join(' / ')} 在 ${e.row_count || '?'} 行满足`, tone: 'warn' },
  source_data_pair_forensics: { label: (e) => `数值对取证: ${e.finding_count || '?'} 个发现`, tone: (e) => e.finding_count > 0 ? 'warn' : 'ok' },
  source_data_cross_sheet: { label: '跨 sheet 重复检测完成', tone: 'ok' },

  // Image detection
  visual_panel_extraction_started: { label: '正在提取 panel…', tone: 'info' },
  visual_panel_extraction_completed: { label: (e) => `提取 ${e.panel_count || '?'} 个 panel`, tone: 'ok' },
  visual_exact_duplicate_completed: { label: '精确重复检测完成', tone: 'ok' },
  copy_move_detected: { label: (e) => `Copy-move: ${e.source_panel_id || '?'} → ${e.target_panel_id || '?'} (score ${(e.score || 0).toFixed(2)})`, tone: 'warn' },
  'visual.copy_move_completed': { label: 'Copy-move 检测完成', tone: 'ok' },
  trufor_completed: { label: 'TruFor 伪造检测完成', tone: 'ok' },

  // Agent
  agent_plan_started: { label: '审查助手正在规划审查策略', tone: 'info' },
  agent_plan_completed: { label: '审查策略规划完成', tone: 'ok' },
  agent_investigation_started: { label: '审查助手开始调查', tone: 'info' },
  agent_investigation_completed: { label: (e) => `调查完成，${e.finding_count || '?'} 个发现`, tone: 'ok' },
  agent_review_completed: { label: (e) => `审查助手审查完成，${e.finding_count || '?'} 个发现`, tone: 'ok' },
  claim_extraction_completed: { label: '论断提取完成', tone: 'ok' },

  // Report
  bundle_started: { label: '正在生成审查报告', tone: 'info' },
  bundle_completed: { label: '报告生成完成', tone: 'ok' },
  html_report_ready: { label: 'HTML 报告就绪', tone: 'ok' },
  static_audit_bundle_started: { label: '正在打包审查产物', tone: 'info' },
  static_audit_bundle_completed: { label: '审查产物打包完成', tone: 'ok' },
};

function translateEvent(event) {
  const eventType = event?.event || '';
  const translation = EVENT_TRANSLATIONS[eventType];
  if (!translation) {
    const humanized = eventType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    return { label: humanized || '事件', tone: 'neutral' };
  }
  const label = typeof translation.label === 'function' ? translation.label(event) : translation.label;
  const tone = typeof translation.tone === 'function' ? translation.tone(event) : translation.tone;
  return { label, tone };
}

function toneDotColor(tone) {
  switch (tone) {
    case 'ok': return 'bg-signal-500';
    case 'warn': return 'bg-caution-500';
    case 'risk': return 'bg-risk-500';
    case 'info': return 'bg-ink-900/20';
    default: return 'bg-ink-900/10';
  }
}

function eventSignal(event) {
  if (!event) return '';
  if (typeof event === 'string') return event;
  return event.key || event.step_key || event.step || event.title || event.event || '';
}

function eventToStepId(event) {
  const lower = String(eventSignal(event)).toLowerCase();
  if (!lower) return null;
  for (const step of STEPS) {
    if (step.prefixes.some((prefix) => lower.startsWith(prefix) || lower.includes(prefix))) {
      return step.id;
    }
  }
  return null;
}

function getStepEvents(stepId, events) {
  return events
    .filter((e) => eventToStepId(e) === stepId)
    .map(translateEvent)
    .filter((e) => e.tone !== 'neutral');
}

function computeStepProgress(stepId, events, currentStepId) {
  if (stepId < currentStepId) return 100;
  if (stepId > currentStepId) return 0;
  const stepEvents = events.filter((e) => eventToStepId(e) === stepId);
  return Math.min(90, stepEvents.length * 15);
}

function deriveCurrentStep(events) {
  let max = 0;
  for (const event of events) {
    const id = eventToStepId(event);
    if (id && id > max) max = id;
  }
  return max || 0;
}

function formatElapsed(startedAt) {
  if (!startedAt) return '';
  const start = new Date(startedAt).getTime();
  if (!Number.isFinite(start)) return '';
  const seconds = Math.max(0, Math.round((Date.now() - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}m ${remaining}s`;
}

function ProgressTracker({ events, runStatus, startedAt, caseId }) {
  const currentStepId = runStatus === 'completed' ? 5 : deriveCurrentStep(events || []);
  const isDone = runStatus === 'completed';
  const isFailed = runStatus === 'failed';
  const elapsed = formatElapsed(startedAt);

  return (
    <section className="dossier-panel rounded-[2rem] p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="metric-label">审查进度</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <span className="font-mono text-xs text-ink-300">
              {isDone ? '已完成' : isFailed ? '已失败' : currentStepId
                ? `步骤 ${currentStepId} / 5 · ${STEPS.find(s => s.id === currentStepId)?.label || ''}`
                : '等待启动'}
            </span>
            {elapsed ? (
              <span className="font-mono text-[11px] text-ink-300">已耗时 {elapsed}</span>
            ) : null}
          </div>
        </div>
        {isDone && caseId ? (
          <a className="btn-primary" href={reportHtmlUrl(caseId)} target="_blank" rel="noreferrer">
            查看结果
          </a>
        ) : null}
      </div>

      <ol className="mt-5 space-y-4">
        {STEPS.map((step) => {
          const progress = isDone
            ? 100
            : isFailed && step.id > currentStepId
              ? 0
              : computeStepProgress(step.id, events || [], currentStepId);
          const isActive = !isDone && !isFailed && step.id === currentStepId;
          const isComplete = progress >= 100;
          const Icon = step.icon;
          const stepEvents = getStepEvents(step.id, events || []);

          return (
            <li
              key={step.id}
              className={`rounded-2xl border px-4 py-3 transition-colors ${
                isActive
                  ? 'border-signal-500/40 bg-signal-100/50'
                  : isComplete
                    ? 'border-signal-500/20 bg-signal-100/25'
                    : 'border-ink-900/8 bg-white/45'
              }`}
            >
              <div className="flex items-center gap-3">
                <span
                  className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm transition-colors ${
                    isComplete
                      ? 'bg-signal-500 text-paper-50'
                      : isActive
                        ? 'bg-signal-500/20 text-signal-700'
                        : 'bg-ink-900/8 text-ink-300'
                  }`}
                >
                  {isComplete ? <FiCheck aria-hidden="true" /> : <Icon aria-hidden="true" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <p className={`text-sm font-semibold ${isActive ? 'text-signal-700' : isComplete ? 'text-ink-900' : 'text-ink-500'}`}>
                      {step.label}
                    </p>
                    <span className="shrink-0 font-mono text-[11px] text-ink-300">
                      {Math.round(progress)}%
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-ink-300">{step.description}</p>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-ink-900/5">
                    <div
                      className={`h-full rounded-full transition-[width] duration-500 ${
                        isComplete
                          ? 'bg-signal-500'
                          : isActive
                            ? 'bg-signal-500/70'
                            : 'bg-ink-900/15'
                      }`}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  {(isComplete || isActive) && stepEvents.length > 0 && (
                    <div className="mt-2 ml-11 space-y-1">
                      {stepEvents.slice(-3).map((se, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${toneDotColor(se.tone)}`} aria-hidden="true" />
                          <span className="text-ink-500 truncate">{se.label}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default ProgressTracker;
