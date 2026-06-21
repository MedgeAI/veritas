const STATUS_MAP = {
  queued: '排队中',
  running: '审查中',
  completed: '已完成',
  failed: '已失败',
  interrupted: '已中断',
  planning: '规划中',
  'review needed': '需复核',
  'report ready': '报告就绪',
  archived: '已归档',
  success: '成功',
  ready: '已就绪',
  missing: '缺失',
  waiting: '等待中',
  indexed: '已索引',
  partial: '部分索引',
  no_panels: '无可索引panel',
  unavailable: '不可用',
  model_unavailable: '模型不可用',
  no_database: '数据库未就绪',
};

export function translateStatus(status) {
  if (!status || typeof status !== 'string') return status;
  return STATUS_MAP[status.toLowerCase()] ?? status;
}

export const TERMS = {
  case: '审查项目',
  agent: '审查助手',
  artifact: '审查产物',
  bundle: '审查产物包',
  claim: '论断',
  investigation: '审查调查',
  run: '运行',
};

const AGENT_MODE_MAP = {
  full: '完整审查',
  review: '复核模式',
  off: '关闭',
};

export function translateAgentMode(mode) {
  if (!mode || typeof mode !== 'string') return mode;
  return AGENT_MODE_MAP[mode.toLowerCase()] ?? mode;
}

const ERROR_REPLACEMENTS = [
  ['static_audit_bundle.json', '审查产物数据'],
  ['final_audit_report.html', '最终审查报告'],
  ['web_data', '审查数据目录'],
  ['localStorage', '本地缓存'],
  ['backend', '后端服务'],
];

export function friendlyError(message) {
  if (!message || typeof message !== 'string') return message;
  let result = message;
  for (const [from, to] of ERROR_REPLACEMENTS) {
    result = result.split(from).join(to);
  }
  return result;
}

const ARTIFACT_LABEL_MAP = {
  'Audit Run Manifest': '审查运行清单',
  'Static Audit Bundle': '审查产物包',
  'Investigation Rounds': '调查轮次记录',
  'Final Markdown Report': 'Markdown 审查报告',
  'Final HTML Report': 'HTML 审查报告',
  'Visual Evidence (Figures)': '视觉证据（图表）',
  'Panel Evidence': 'Panel 证据',
  'Image Relationships': '图像关联关系',
  'Visual Findings': '视觉发现',
  'SILA Dense Copy-Move': '密集 Copy-Move 检测',
  'Visual Overlap/Reuse': '图像复用检测',
  'Provenance Graph (MST)': '图像溯源图',
};

export function translateArtifactLabel(label) {
  if (!label || typeof label !== 'string') return label;
  return ARTIFACT_LABEL_MAP[label] ?? label;
}

const RISK_LEVEL_MAP = {
  critical: '极高',
  high: '高',
  medium: '中',
  low: '低',
};

export function translateRiskLevel(level) {
  if (!level || typeof level !== 'string') return level;
  return RISK_LEVEL_MAP[level.toLowerCase()] ?? level;
}

const ISSUE_CATEGORY_MAP = {
  consistency: '数据一致性',
  matching: '声明匹配',
  completeness: '材料完整性',
};

export function translateIssueCategory(category) {
  if (!category || typeof category !== 'string') return category;
  return ISSUE_CATEGORY_MAP[category.toLowerCase()] ?? category;
}
