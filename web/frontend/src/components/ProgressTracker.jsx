import { useCallback, useMemo, useState } from 'react';
import { FiCheck, FiChevronDown, FiChevronRight, FiClock, FiXCircle } from 'react-icons/fi';
import { reportHtmlUrl } from '../services/api.js';

// Step icon mapping
const STEP_ICONS = {
  discover: '',
  material_inventory: '📋',
  agent_material_plan: '🤖',
  agent_plan: '🤖',
  mineru: '📄',
  evidence_ledger: '📚',
  numeric_forensics: '🔢',
  paperfraud_rule_match: '📏',
  source_data_profile: '📊',
  source_data_findings: '🔎',
  source_data_pair_forensics: '',
  source_data_cross_sheet: '📑',
  source_data_sheet_briefing: '📝',
  source_data_verdict: '⚖️',
  paperconan_scan: '🔬',
  agent_review: '🤖',
  agent_role_claim_extractor: '🎯',
  agent_role_source_data_auditor: '🔍',
  agent_role_judge: '⚖️',
  static_audit_bundle: '📦',
  html_report: '',
  final_report: '📄',
  investigation_01: '🔬',
  investigation_02: '🔬',
  investigation_03: '🔬',
};

const STEP_LABELS = {
  discover: '发现输入材料',
  material_inventory: '材料清单扫描',
  agent_material_plan: 'Agent 材料计划',
  agent_plan: 'Agent 审查计划',
  mineru: 'MinerU PDF 解析',
  evidence_ledger: '构建 Evidence Ledger',
  numeric_forensics: 'PDF 数字取证',
  paperfraud_rule_match: 'PaperFraud 规则匹配',
  source_data_profile: 'Source Data Profile',
  source_data_findings: 'Source Data Findings',
  source_data_pair_forensics: '数值对取证',
  source_data_cross_sheet: '跨 Sheet 检测',
  source_data_sheet_briefing: 'Sheet Briefing',
  source_data_verdict: 'Source Data Verdict',
  paperconan_scan: 'PaperConan 扫描',
  agent_review: 'Agent 审查',
  agent_role_claim_extractor: 'Claim Extractor',
  agent_role_source_data_auditor: 'Source Data Auditor',
  agent_role_judge: 'Judge Agent',
  static_audit_bundle: '生成 Audit Bundle',
  html_report: '生成 HTML 报告',
  final_report: '最终报告整合',
  investigation_01: 'Agent 调查轮次 1',
  investigation_02: 'Agent 调查轮次 2',
  investigation_03: 'Agent 调查轮次 3',
};

const STEP_DESCRIPTIONS = {
  discover: '识别输入文件类型和路径',
  material_inventory: '扫描并分类所有提交材料',
  agent_material_plan: 'LLM 决定需要运行哪些检测工具',
  agent_plan: 'LLM 生成具体审查计划和参数',
  mineru: '解析 PDF，提取文本、图表、公式',
  evidence_ledger: '构建结构化证据清单',
  numeric_forensics: 'PDF 内数值统计取证',
  paperfraud_rule_match: '匹配 PaperFraud 规则库',
  source_data_profile: '分析 Source Data 结构和统计特征',
  source_data_findings: '检测固定差值/比例等异常模式',
  source_data_pair_forensics: '数值对关联取证',
  source_data_cross_sheet: '跨 Sheet 重复检测',
  source_data_sheet_briefing: '生成 Sheet 结构化摘要',
  source_data_verdict: 'LLM 裁决 Source Data 发现',
  paperconan_scan: 'PaperConan 工具扫描',
  agent_review: 'LLM 审查所有发现并生成建议',
  agent_role_claim_extractor: '提取论文核心论断',
  agent_role_source_data_auditor: '审计 Source Data 与论断映射',
  agent_role_judge: '综合判断风险等级',
  static_audit_bundle: '打包所有结构化产物',
  html_report: '生成可视化 HTML 报告',
  final_report: '整合最终审查报告',
  investigation_01: '第 1 轮 Agent 驱动深入调查',
  investigation_02: '第 2 轮 Agent 驱动深入调查',
  investigation_03: '第 3 轮 Agent 驱动深入调查',
};

// Get base step key (group parent)
function getBaseStepKey(key) {
  if (!key) return null;
  // investigation_01_ir_01_a001 → investigation_01
  const match = key.match(/^(investigation_\d+)_/);
  if (match) return match[1];
  return key;
}

// Get step status from events
function getStepStatus(events, stepKey) {
  const stepEvents = events.filter(e => e.key === stepKey || getBaseStepKey(e.key) === stepKey);
  if (stepEvents.length === 0) return 'pending';

  const hasResult = stepEvents.some(e => e.event === 'step_result');
  const hasStart = stepEvents.some(e => e.event === 'step_start');
  const hasAttempt = stepEvents.some(e => e.event === 'step_attempt');

  if (hasResult) {
    const lastResult = stepEvents.filter(e => e.event === 'step_result').pop();
    if (lastResult.status === 'failed') return 'failed';
    if (lastResult.status === 'skipped') return 'skipped';
    return 'completed';
  }
  if (hasAttempt && !hasResult) return 'running';
  if (hasStart && !hasResult) return 'running';
  return 'pending';
}

// Get step duration
function getStepDuration(events, stepKey) {
  const stepEvents = events.filter(e => e.key === stepKey || getBaseStepKey(e.key) === stepKey);
  if (stepEvents.length === 0) return null;

  const startEvent = stepEvents.find(e => e.event === 'step_start');
  const resultEvent = stepEvents.filter(e => e.event === 'step_result').pop();

  if (!startEvent || !resultEvent) return null;

  const start = new Date(startEvent.timestamp).getTime();
  const end = new Date(resultEvent.timestamp).getTime();
  const duration = Math.round((end - start) / 1000);

  if (duration < 1) return '<1s';
  if (duration < 60) return `${duration}s`;
  const minutes = Math.floor(duration / 60);
  const seconds = duration % 60;
  return `${minutes}m ${seconds}s`;
}

// Format timestamp
function formatTimestamp(ts) {
  if (!ts) return '';
  const date = new Date(ts);
  return new Intl.DateTimeFormat(navigator.languages ?? ['zh-CN'], { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}

// Status icon
function StatusIcon({ status }) {
  switch (status) {
    case 'completed':
      return <FiCheck className="text-green-600" />;
    case 'running':
      return <div aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />;
    case 'failed':
      return <FiXCircle className="text-red-600" />;
    case 'skipped':
      return <div className="text-gray-400">○</div>;
    default:
      return <div className="text-gray-300">○</div>;
  }
}

// Status color
function getStatusColor(status) {
  switch (status) {
    case 'completed': return 'bg-green-100 border-green-200';
    case 'running': return 'bg-blue-50 border-blue-200';
    case 'failed': return 'bg-red-50 border-red-200';
    case 'skipped': return 'bg-gray-50 border-gray-200';
    default: return 'bg-gray-50 border-gray-200';
  }
}

function ProgressTracker({ events, runStatus, _startedAt, caseId }) {
  const [expandedSteps, setExpandedSteps] = useState({});

  // Extract unique step keys and group them
  const stepGroups = useMemo(() => {
    const groups = {};
    events.forEach(e => {
      const baseKey = getBaseStepKey(e.key);
      if (!baseKey) return;
      if (!groups[baseKey]) {
        groups[baseKey] = {
          key: baseKey,
          status: 'pending',
          duration: null,
          events: [],
        };
      }
      groups[baseKey].events.push(e);
    });

    // Compute status and duration for each group
    Object.values(groups).forEach(group => {
      group.status = getStepStatus(events, group.key);
      group.duration = getStepDuration(events, group.key);
    });

    return Object.values(groups);
  }, [events]);

  // Calculate progress
  const progress = useMemo(() => {
    if (runStatus === 'completed') return 100;
    if (stepGroups.length === 0) return 0;
    const completed = stepGroups.filter(g => g.status === 'completed' || g.status === 'skipped').length;
    const running = stepGroups.filter(g => g.status === 'running').length;
    return Math.round(((completed + running * 0.5) / stepGroups.length) * 100);
  }, [stepGroups, runStatus]);

  const toggleStep = useCallback((key) => {
    setExpandedSteps(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const isDone = runStatus === 'completed';
  const isFailed = runStatus === 'failed';

  return (
    <section className="dossier-panel rounded-[2rem] p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <p className="metric-label">审查进度</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <span className="font-mono text-xs text-ink-300">
              {isDone ? '已完成' : isFailed ? '已失败' : `步骤 ${stepGroups.filter(g => g.status === 'completed' || g.status === 'skipped').length} / ${stepGroups.length}`}
            </span>
            <span className="font-mono text-[11px] text-ink-300">{progress}%</span>
          </div>
        </div>
        {isDone && caseId ? (
          <a className="btn-primary" href={reportHtmlUrl(caseId)} target="_blank" rel="noreferrer">
            查看结果
          </a>
        ) : null}
      </div>

      {/* Progress Bar */}
      <div className="mb-6 h-2 w-full overflow-hidden rounded-full bg-ink-900/5">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            isDone ? 'bg-green-500' : isFailed ? 'bg-red-500' : 'bg-blue-500'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Step Groups */}
      <div className="space-y-2">
        {stepGroups.map((group) => {
          const isExpanded = expandedSteps[group.key] || false;
          const hasDetails = group.events.some(e => e.event === 'command_output' || e.event === 'step_attempt');

          return (
            <div
              key={group.key}
              className={`rounded-xl border transition-colors ${getStatusColor(group.status)}`}
            >
              {/* Step Header */}
              <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
                onClick={() => hasDetails && toggleStep(group.key)}
                disabled={!hasDetails}
              >
                <div role="status" className="shrink-0">
                  <StatusIcon status={group.status} />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-base">{STEP_ICONS[group.key] || '📋'}</span>
                    <span className="text-sm font-semibold text-ink-900 truncate">
                      {STEP_LABELS[group.key] || group.key}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-ink-500 truncate">
                    {STEP_DESCRIPTIONS[group.key] || ''}
                  </p>
                </div>

                {group.duration && (
                  <span className="flex items-center gap-1 text-xs text-ink-400 font-mono">
                    <FiClock className="h-3 w-3" />
                    {group.duration}
                  </span>
                )}

                {hasDetails && (
                  <span className="text-ink-400">
                    {isExpanded ? <FiChevronDown /> : <FiChevronRight />}
                  </span>
                )}
              </button>

              {/* Expanded Details */}
              {isExpanded && hasDetails && (
                <div className="border-t border-ink-900/10 px-4 py-3 bg-white/50">
                  <div className="space-y-2">
                    {group.events.map((e, idx) => {
                      if (e.event === 'command_output') {
                        return (
                          <div key={idx} className="flex items-start gap-2 text-xs">
                            <span className="font-mono text-ink-400">{formatTimestamp(e.timestamp)}</span>
                            <span className="text-ink-600 font-mono">{e.line || e.detail}</span>
                          </div>
                        );
                      }
                      if (e.event === 'step_attempt') {
                        return (
                          <div key={idx} className="flex items-center gap-2 text-xs">
                            <span className="font-mono text-ink-400">{formatTimestamp(e.timestamp)}</span>
                            <span className="text-blue-600">尝试 {e.attempt}/{e.attempts}</span>
                          </div>
                        );
                      }
                      return null;
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default ProgressTracker;
