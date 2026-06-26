/**
 * Layer classification for report findings (PRD2-T8).
 *
 * Mirrors engine/static_audit/_shared.py classify_finding() to keep
 * client-side grouping consistent with the backend layer model.
 *
 * Layer definitions (from PRD section 5):
 *   Layer 1 (高置信度发现): critical/high risk, except DRV and methodology.
 *   Layer 2 (需人工判断): medium risk, OR high-risk paperconan/numeric forensics.
 *   Layer 3 (其他信号): low/info risk, DRV, methodology review notes.
 */

const LAYER3_CATEGORIES = new Set([
  'duplicate_row_vector',
  'paperfraud.methodology_review',
]);

const PAPERCONAN_TOKENS = ['paperfraud', 'numeric_forensics', 'benford', 'digit'];

/**
 * Classify a finding into one of three report layers.
 *
 * @param {Object} finding - Finding object with risk_level, category/issue_category, source_artifact.
 * @returns {'layer_1'|'layer_2'|'layer_3'}
 */
export function classifyFinding(finding) {
  if (!finding || typeof finding !== 'object') return 'layer_3';

  const riskLevel = String(finding.risk_level || 'medium').toLowerCase();
  const category = String(finding.category || finding.issue_category || '').toLowerCase();
  const sourceArtifact = String(finding.source_artifact || '').toLowerCase();

  // DRV and methodology review are always Layer 3
  if (LAYER3_CATEGORIES.has(category)) return 'layer_3';

  // Check if this is a Paperconan/numeric-forensics finding
  const isPaperconan = PAPERCONAN_TOKENS.some(
    (token) => category.includes(token) || sourceArtifact.includes(token),
  );

  if (riskLevel === 'critical' || riskLevel === 'high') {
    return isPaperconan ? 'layer_2' : 'layer_1';
  }

  if (riskLevel === 'medium') return 'layer_2';

  // low, info, context
  return 'layer_3';
}

/**
 * Layer metadata: titles, descriptions, default open state.
 */
export const LAYER_METADATA = {
  layer_1: {
    title: '高置信度发现',
    label: 'Layer 1',
    description: '明确的数据完整性问题，需优先关注',
    defaultOpen: true,
  },
  layer_2: {
    title: '需人工判断',
    label: 'Layer 2',
    description: '需要人工复核以判断是否为真实问题',
    defaultOpen: true,
  },
  layer_3: {
    title: '其他信号',
    label: 'Layer 3',
    description: '信息性记录，默认折叠，可选择性查看',
    defaultOpen: false,
  },
};

/**
 * Group an array of findings by layer.
 *
 * @param {Array<Object>} findings
 * @returns {{ layer_1: Object[], layer_2: Object[], layer_3: Object[] }}
 */
export function groupFindingsByLayer(findings) {
  const result = { layer_1: [], layer_2: [], layer_3: [] };
  if (!Array.isArray(findings)) return result;

  for (const finding of findings) {
    const layer = classifyFinding(finding);
    result[layer].push(finding);
  }
  return result;
}
