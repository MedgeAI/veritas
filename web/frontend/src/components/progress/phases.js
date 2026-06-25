/**
 * Phased Progress Stepper - 常量与工具函数
 *
 * 定义审计流水线的六个阶段、步骤、权重，以及状态计算工具。
 * 纯 JS 模块，无 React 依赖，无项目内部导入。
 */

// ============================================================================
// PHASES 定义
// ============================================================================

export const PHASES = [
  {
    id: 'prep',
    label: '准备',
    icon: '🔍',
    steps: [
      { key: 'discover', label: '发现输入材料' },
      { key: 'material_inventory', label: '材料清单扫描' },
      { key: 'agent_material_plan', label: 'Agent 材料计划' },
      { key: 'agent_plan', label: 'Agent 审查计划' },
    ],
  },
  {
    id: 'parse',
    label: '文档解析',
    icon: '📄',
    steps: [
      { key: 'mineru', label: 'MinerU PDF 解析' },
      { key: 'evidence_ledger', label: '构建 Evidence Ledger' },
    ],
  },
  {
    id: 'forensics',
    label: '数值取证',
    icon: '🔢',
    steps: [
      { key: 'numeric_forensics', label: 'PDF 数字取证' },
      { key: 'paperconan_scan', label: 'PaperConan 扫描' },
      { key: 'paperfraud_rule_match', label: 'PaperFraud 规则匹配' },
    ],
  },
  {
    id: 'analysis',
    label: '证据分析',
    icon: '🔬',
    steps: [
      { key: 'source_data_profile', label: 'Source Data Profile' },
      { key: 'source_data_findings', label: 'Source Data Findings' },
      { key: 'source_data_pair_forensics', label: '数值对取证' },
      { key: 'source_data_cross_sheet', label: '跨 Sheet 检测' },
      { key: 'source_data_sheet_briefing', label: 'Sheet Briefing' },
      { key: 'source_data_verdict', label: 'Source Data Verdict' },
    ],
  },
  {
    id: 'review',
    label: 'Agent 审查',
    icon: '🤖',
    steps: [
      { key: 'agent_review', label: 'Agent 审查' },
      { key: 'agent_role_claim_extractor', label: 'Claim Extractor' },
      { key: 'agent_role_source_data_auditor', label: 'Source Data Auditor' },
      { key: 'agent_role_judge', label: 'Judge Agent' },
    ],
  },
  {
    id: 'report',
    label: '报告生成',
    icon: '📊',
    steps: [
      { key: 'static_audit_bundle', label: '生成 Audit Bundle' },
      { key: 'html_report', label: '生成 HTML 报告' },
      { key: 'final_report', label: '最终报告整合' },
    ],
  },
];

// ============================================================================
// PHASE_WEIGHTS 定义
// ============================================================================

export const PHASE_WEIGHTS = {
  prep: 0.05,
  parse: 0.25,
  forensics: 0.15,
  analysis: 0.20,
  review: 0.25,
  report: 0.10,
};

// ============================================================================
// 工具函数
// ============================================================================

/**
 * 获取所有阶段的总步骤数
 * @returns {number}
 */
export function getTotalSteps() {
  return PHASES.reduce((sum, phase) => sum + phase.steps.length, 0);
}

/**
 * 根据 stepKey 查找所属阶段
 * @param {string} stepKey
 * @returns {object|undefined} phase 对象
 */
export function findPhaseForStep(stepKey) {
  return PHASES.find((phase) => phase.steps.some((step) => step.key === stepKey));
}

/**
 * 将 event.key 归一化为基础 stepKey
 * investigation_01_ir_01_a001 → investigation_01
 * 其他 key 原样返回
 * @param {string} eventKey
 * @returns {string|null}
 */
export function getBaseStepKey(eventKey) {
  if (!eventKey) return null;
  const match = eventKey.match(/^investigation_\d{2}_/);
  if (match) {
    return eventKey.split('_').slice(0, 2).join('_');
  }
  return eventKey;
}

/**
 * 从 events 数组计算每个 stepKey 的状态
 * 规则:
 * - event.status in ['ran','reused','skipped'] → 'completed'
 * - event.status === 'running' → 'running'
 * - event.status === 'failed' → 'failed'
 * - 否则 → 'pending'
 * - 同一 stepKey 多条 event 取最新时间戳的 status
 *
 * @param {Array} events - [{ key, status, timestamp }, ...]
 * @returns {Object} { [stepKey]: 'completed'|'running'|'failed'|'pending' }
 */
export function getStepStatuses(events) {
  const statusMap = new Map();

  for (const event of events) {
    const stepKey = getBaseStepKey(event.key);
    if (!stepKey) continue;

    let status = 'pending';
    if (['ran', 'reused', 'skipped'].includes(event.status)) {
      status = 'completed';
    } else if (event.status === 'running') {
      status = 'running';
    } else if (event.status === 'failed') {
      status = 'failed';
    }

    const existing = statusMap.get(stepKey);
    const eventTime = new Date(event.timestamp).getTime();
    if (!existing || eventTime > new Date(existing.timestamp).getTime()) {
      statusMap.set(stepKey, { status, timestamp: event.timestamp });
    }
  }

  const result = {};
  for (const [stepKey, { status }] of statusMap) {
    result[stepKey] = status;
  }

  return result;
}

/**
 * 计算阶段状态
 * - 所有步骤 completed/skipped → 'completed'
 * - 任意步骤 running 或任意步骤 completed → 'running'
 * - 否则 → 'pending'
 *
 * @param {object} phase - PHASES 中的阶段对象
 * @param {Object} stepStatuses - getStepStatuses() 的返回值
 * @returns {'completed'|'running'|'pending'}
 */
export function getPhaseStatus(phase, stepStatuses) {
  const stepKeys = phase.steps.map((s) => s.key);
  const statuses = stepKeys.map((key) => stepStatuses[key] || 'pending');

  const allCompletedOrSkipped = statuses.every(
    (s) => s === 'completed' || s === 'skipped'
  );
  if (allCompletedOrSkipped && statuses.length > 0) return 'completed';

  const anyRunningOrCompleted = statuses.some(
    (s) => s === 'running' || s === 'completed'
  );
  if (anyRunningOrCompleted) return 'running';

  return 'pending';
}

/**
 * 计算加权进度百分比 (0-100)
 * 对每个阶段:
 * - completed → 贡献 1 * weight
 * - running → 计算内部进度 (completed steps / total steps, running 算 0.5) * weight
 * - pending → 贡献 0
 *
 * @param {Object} phaseStatuses - { [phaseId]: 'completed'|'running'|'pending' }
 * @param {Object} [stepStatuses={}] - 可选，用于更精确的 running 阶段内部进度计算
 * @returns {number} 0-100
 */
export function computeWeightedProgress(phaseStatuses, stepStatuses = {}) {
  let total = 0;

  for (const phase of PHASES) {
    const phaseStatus = phaseStatuses[phase.id] || 'pending';
    const weight = PHASE_WEIGHTS[phase.id];

    let phaseProgress = 0;

    if (phaseStatus === 'completed') {
      phaseProgress = 1;
    } else if (phaseStatus === 'running') {
      if (Object.keys(stepStatuses).length > 0) {
        // 计算内部进度
        const stepKeys = phase.steps.map((s) => s.key);
        let completedCount = 0;
        for (const key of stepKeys) {
          const s = stepStatuses[key] || 'pending';
          if (s === 'completed' || s === 'skipped') {
            completedCount++;
          } else if (s === 'running') {
            completedCount += 0.5;
          }
        }
        phaseProgress = completedCount / phase.steps.length;
      } else {
        // 无 step 级别数据时，running 阶段算 0.5
        phaseProgress = 0.5;
      }
    }

    total += phaseProgress * weight;
  }

  return Math.round(total * 100);
}
