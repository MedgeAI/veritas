import { useCallback, useEffect, useMemo, useState } from 'react';
import { FiCheckCircle, FiXCircle, FiClipboard, FiCheck, FiMail } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';
import EmptyState from '../components/EmptyState.jsx';
import { translateStatus, translateRiskLevel, translateIssueCategory } from '../utils/piLabels.js';
import { checkMaterials, fetchReviewItems, getRiskSummary } from '../services/api.js';

const MATERIAL_CONFIG = [
  { key: 'pdf', label: '论文 PDF', okStatus: 'ok', weight: 30 },
  { key: 'source_data', label: 'Source Data', okStatus: 'ok', weight: 30 },
  { key: 'code', label: '代码', okStatus: 'provided', weight: 20 },
  { key: 'environment', label: '环境文件', okStatus: 'provided', weight: 20 },
];

const RISK_TONE = {
  critical: 'risk',
  high: 'risk',
  medium: 'warn',
  low: 'neutral',
  info: 'neutral',
};

const STATUS_OPTIONS = [
  { value: 'open', label: '待处理', color: 'bg-gray-100 text-gray-700' },
  { value: 'resolved', label: '已解决', color: 'bg-emerald-100 text-emerald-800' },
  { value: 'dismissed', label: '已忽略', color: 'bg-gray-100 text-gray-500' },
  { value: 'needs_author_response', label: '需作者回复', color: 'bg-orange-100 text-orange-800' },
];

function readActionsWorkspaceFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    return {
      filterStatus: params.get('actionStatus') || 'all',
      filterRisk: params.get('actionRisk') || 'all',
      selectedItemRef: params.get('actionItem') || '',
    };
  } catch {
    return {
      filterStatus: 'all',
      filterRisk: 'all',
      selectedItemRef: '',
    };
  }
}

function writeActionsWorkspaceUrl({ filterStatus, filterRisk, selectedItemRef }) {
  try {
    const url = new URL(window.location.href);
    if (filterStatus && filterStatus !== 'all') url.searchParams.set('actionStatus', filterStatus);
    else url.searchParams.delete('actionStatus');
    if (filterRisk && filterRisk !== 'all') url.searchParams.set('actionRisk', filterRisk);
    else url.searchParams.delete('actionRisk');
    if (selectedItemRef) url.searchParams.set('actionItem', selectedItemRef);
    else url.searchParams.delete('actionItem');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  } catch {
    // URL state is progressive enhancement for deep-linking.
  }
}

function buildEmailTemplate(caseId, missingItems) {
  const lines = missingItems.map(item => `- ${item.label}（${item.status}：${item.detail}）`);
  return `同学你好，\n\n在投稿前自查过程中，发现以下材料尚未提供完整，请尽快补充：\n\n${lines.join('\n')}\n\n请提供上述材料后，我将重新运行审查流程。\n\n谢谢！`;
}

function ScoreRing({ score }) {
  const radius = 32;
  const circumference = 2 * Math.PI * radius;
  const dashoffset = circumference - (score / 100) * circumference;
  const color = score >= 80 ? 'text-emerald-600' : score >= 50 ? 'text-amber-500' : 'text-risk-600';
  return (
    <div className="relative grid h-20 w-20 place-items-center">
      <svg className="absolute inset-0 h-full w-full -rotate-90" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r={radius} fill="none" stroke="currentColor" strokeWidth="6" className="text-ink-900/8" />
        <circle
          cx="40"
          cy="40"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={dashoffset}
          strokeLinecap="round"
          className={`transition-[stroke-dashoffset] duration-500 ${color}`}
        />
      </svg>
      <span className={`font-display text-xl font-bold tabular-nums ${color}`}>{score}</span>
    </div>
  );
}

function ActionsPage({ selectedCase }) {
  const initialWorkspace = useMemo(() => readActionsWorkspaceFromUrl(), []);
  const [materials, setMaterials] = useState(null);
  const [reviewItems, setReviewItems] = useState([]);
  const [riskSummary, setRiskSummary] = useState(null);
  const [selectedItemRef, setSelectedItemRef] = useState(initialWorkspace.selectedItemRef);
  const [noteInput, setNoteInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [filterStatus, setFilterStatus] = useState(initialWorkspace.filterStatus);
  const [filterRisk, setFilterRisk] = useState(initialWorkspace.filterRisk);
  const [copiedKey, setCopiedKey] = useState(null);
  const [loadingMaterials, setLoadingMaterials] = useState(false);
  const [loadingReviews, setLoadingReviews] = useState(false);
  const [loadingFollowUps, setLoadingFollowUps] = useState(false);
  const [error, setError] = useState('');

  const caseId = selectedCase?.case_id || '';

  // Material completeness fetch
  useEffect(() => {
    if (!caseId) { setMaterials(null); return; }
    let cancelled = false;
    setLoadingMaterials(true);
    checkMaterials(caseId)
      .then(data => { if (!cancelled) setMaterials(data); })
      .catch(() => { /* non-critical */ })
      .finally(() => { if (!cancelled) setLoadingMaterials(false); });
    return () => { cancelled = true; };
  }, [caseId]);

  // Review items fetch
  const loadReviews = useCallback(async () => {
    if (!caseId) return;
    setLoadingReviews(true);
    setError('');
    try {
      const data = await fetchReviewItems(caseId);
      setReviewItems(data.items || []);
    } catch (err) {
      setError(err.message || '加载复核项失败');
    } finally {
      setLoadingReviews(false);
    }
  }, [caseId]);

  useEffect(() => { loadReviews(); }, [loadReviews]);

  const selectedItem = useMemo(
    () => reviewItems.find(item => item.source_ref === selectedItemRef) || null,
    [reviewItems, selectedItemRef],
  );

  useEffect(() => {
    writeActionsWorkspaceUrl({ filterStatus, filterRisk, selectedItemRef });
  }, [filterStatus, filterRisk, selectedItemRef]);

  useEffect(() => {
    function handlePopState() {
      const nextWorkspace = readActionsWorkspaceFromUrl();
      setFilterStatus(nextWorkspace.filterStatus);
      setFilterRisk(nextWorkspace.filterRisk);
      setSelectedItemRef(nextWorkspace.selectedItemRef);
    }
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    if (selectedItem) setNoteInput(selectedItem.decision?.note || '');
  }, [selectedItem]);

  // Risk summary fetch (for follow-ups)
  useEffect(() => {
    if (!caseId) { setRiskSummary(null); return; }
    let cancelled = false;
    setLoadingFollowUps(true);
    getRiskSummary(caseId)
      .then(data => { if (!cancelled) setRiskSummary(data); })
      .catch(() => { /* non-critical */ })
      .finally(() => { if (!cancelled) setLoadingFollowUps(false); });
    return () => { cancelled = true; };
  }, [caseId]);

  // beforeunload for unsaved note
  useEffect(() => {
    if (!noteInput) return undefined;
    function handleBeforeUnload(e) {
      e.preventDefault();
      e.returnValue = '';
    }
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [noteInput]);

  // Copy to clipboard helper
  const copyToClipboard = useCallback(async (text, key) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch {
      // Clipboard API unavailable
    }
  }, []);

  // Copy email template for a single missing material
  const copyEmailTemplate = useCallback(item => {
    const template = buildEmailTemplate(caseId, [item]);
    copyToClipboard(template, `material:${item.key}`);
  }, [caseId, copyToClipboard]);

  // Copy follow-up question
  const copyFollowUp = useCallback(question => {
    copyToClipboard(question, `followup:${question}`);
  }, [copyToClipboard]);

  // Review decision handler
  const handleDecision = useCallback(async (status) => {
    if (!selectedItem || !caseId) return;
    setSaving(true);
    try {
      const { saveReviewDecision } = await import('../services/api.js');
      await saveReviewDecision(caseId, selectedItem.source_ref, {
        status,
        note: noteInput,
      });
      setNoteInput('');
      await loadReviews();
    } catch (err) {
      setError(err.message || '保存决定失败');
    } finally {
      setSaving(false);
    }
  }, [selectedItem, caseId, noteInput, loadReviews]);

  // Derived data
  const missingMaterials = useMemo(() => {
    if (!materials) return [];
    return MATERIAL_CONFIG
      .filter(config => {
        const data = materials[config.key];
        return data && data.status !== config.okStatus;
      })
      .map(config => ({
        key: config.key,
        label: config.label,
        status: materials[config.key]?.status || '未知',
        detail: materials[config.key]?.detail || '',
        isOk: false,
      }));
  }, [materials]);

  const allMaterialsComplete = materials && missingMaterials.length === 0;

  const filteredItems = useMemo(() => {
    return reviewItems.filter(item => {
      if (filterStatus !== 'all') {
        const itemStatus = item.decision?.status || 'open';
        if (itemStatus !== filterStatus) return false;
      }
      if (filterRisk !== 'all' && item.risk_level !== filterRisk) return false;
      return true;
    });
  }, [reviewItems, filterStatus, filterRisk]);

  const openCount = useMemo(() => reviewItems.filter(i => !i.decision || i.decision.status === 'open').length, [reviewItems]);
  const resolvedCount = useMemo(() => reviewItems.filter(i => i.decision?.status === 'resolved').length, [reviewItems]);
  const dismissedCount = useMemo(() => reviewItems.filter(i => i.decision?.status === 'dismissed').length, [reviewItems]);

  const allFollowUps = useMemo(() => {
    if (!riskSummary?.follow_ups) return [];
    const result = [];
    for (const [findingId, questions] of Object.entries(riskSummary.follow_ups)) {
      for (const question of questions) {
        result.push({ findingId, question });
      }
    }
    return result;
  }, [riskSummary]);

  // Empty state
  if (!selectedCase) return <EmptyState title="请先选择审查项目" message="选择审查项目后将展示需要您行动的事项。" />;

  return (
    <div className="space-y-6">
      {error && (
        <div role="alert" aria-live="polite" className="rounded-xl border border-risk-200 bg-risk-50 px-4 py-3 text-sm text-risk-700">
          {error}
        </div>
      )}

      {copiedKey && (
        <div className="rounded-xl bg-signal-100 px-3 py-2 text-xs text-signal-700" role="status" aria-live="polite">
          <FiCheck className="mr-1 inline" aria-hidden="true" />
          已复制到剪贴板
        </div>
      )}

      {/* SECTION 1: Material Follow-up */}
      <section className="dossier-panel rounded-2xl p-6">
        <div className="flex items-center justify-between border-b border-ink-900/10 pb-4">
          <div>
            <h2 className="font-display text-lg font-semibold text-ink-900">材料补交</h2>
            <p className="mt-1 text-xs text-ink-500">
              {loadingMaterials
                ? '加载中…'
                : allMaterialsComplete
                  ? '所有必要材料已提供'
                  : `${missingMaterials.length} 项材料待补充`}
            </p>
          </div>
          {materials && !allMaterialsComplete && (
            <ScoreRing score={materials.completeness_score ?? 0} />
          )}
        </div>

        {allMaterialsComplete ? (
          <div className="mt-4 flex items-center gap-2 rounded-2xl bg-signal-100/50 px-4 py-3 text-sm text-signal-700">
            <FiCheckCircle aria-hidden="true" />
            所有材料已提供
          </div>
        ) : (
          <div className="mt-4 space-y-2">
            {MATERIAL_CONFIG.map(config => {
              const data = materials?.[config.key];
              if (!data) return null;
              const isOk = data.status === config.okStatus;
              return (
                <div key={config.key} className="flex items-center justify-between rounded-xl bg-white/50 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-ink-900">{config.label}</span>
                      <StatusPill tone={isOk ? 'ok' : 'risk'}>
                        {isOk ? '已提供' : '缺失'}
                      </StatusPill>
                    </div>
                    <p className="mt-1 break-words font-mono text-xs text-ink-500">{data.detail}</p>
                  </div>
                  {!isOk && (
                    <button
                      type="button"
                      className="btn-ghost shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
                      onClick={() => copyEmailTemplate({
                        key: config.key,
                        label: config.label,
                        status: data.status,
                        detail: data.detail,
                      })}
                      aria-label={`复制 ${config.label} 补交通知`}
                    >
                      <FiMail aria-hidden="true" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Batch copy button when there are missing items */}
        {missingMaterials.length > 1 && (
          <div className="mt-3 border-t border-ink-900/8 pt-3">
            <button
              type="button"
              className="btn-ghost w-full text-sm"
              onClick={() => copyToClipboard(
                buildEmailTemplate(caseId, missingMaterials),
                'material:batch',
              )}
              aria-label="复制全部材料补交通知"
            >
              <FiMail aria-hidden="true" />
              复制全部补交通知
            </button>
          </div>
        )}
      </section>

      {/* SECTION 2: Review Items */}
      <section className="dossier-panel rounded-2xl p-6">
        <header className="flex items-center justify-between border-b border-ink-900/10 pb-4">
          <div>
            <h2 className="font-display text-lg font-semibold text-ink-900">待复核发现</h2>
            <p className="mt-1 text-xs text-ink-500">
              {loadingReviews
                ? '加载中…'
                : `${reviewItems.length} 项 · ${openCount} 待处理 · ${resolvedCount} 已解决 · ${dismissedCount} 已忽略`}
            </p>
          </div>
        </header>

        {/* Filters */}
        <div className="mt-4 flex flex-wrap gap-3">
          <label className="text-sm">
            <span className="sr-only">按状态筛选</span>
            <select
              value={filterStatus}
              onChange={e => setFilterStatus(e.target.value)}
              name="review_status_filter"
              className="rounded-lg border border-ink-900/10 bg-white/60 px-3 py-1.5 text-sm text-ink-900"
            >
              <option value="all">全部状态</option>
              {STATUS_OPTIONS.map(s => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="sr-only">按风险等级筛选</span>
            <select
              value={filterRisk}
              onChange={e => setFilterRisk(e.target.value)}
              name="review_risk_filter"
              className="rounded-lg border border-ink-900/10 bg-white/60 px-3 py-1.5 text-sm text-ink-900"
            >
              <option value="all">全部风险等级</option>
              <option value="critical">极高</option>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </label>
        </div>

        {filteredItems.length === 0 && !loadingReviews ? (
          <div className="mt-4 rounded-2xl border border-dashed border-ink-900/20 bg-white/40 p-8 text-center">
            <p className="text-sm text-ink-500">
              {reviewItems.length === 0 ? '暂无待复核发现。' : '当前筛选条件下没有匹配项。'}
            </p>
          </div>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {/* Left: Item list */}
            <div style={{ overscrollBehavior: 'contain' }} className="max-h-[500px] space-y-2 overflow-y-auto">
              {filteredItems.map(item => {
                const isSelected = selectedItem?.source_ref === item.source_ref;
                const status = item.decision?.status || 'open';
                const statusOpt = STATUS_OPTIONS.find(s => s.value === status) || STATUS_OPTIONS[0];
                return (
                  <button
                    key={item.source_ref}
                    type="button"
                    onClick={() => { setSelectedItemRef(item.source_ref); setNoteInput(item.decision?.note || ''); }}
                    className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                      isSelected ? 'border-ink-900/30 bg-ink-900/5' : 'border-ink-900/10 bg-white/60 hover:bg-white'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-ink-900 line-clamp-1">
                        {item.title || '未命名项目'}
                      </span>
                      <div className="flex items-center gap-2">
                        <StatusPill tone={RISK_TONE[item.risk_level] || 'neutral'}>
                          {translateRiskLevel(item.risk_level)}
                        </StatusPill>
                      </div>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-ink-500">
                      <span className="rounded bg-ink-900/5 px-1.5 py-0.5 font-mono">{item.source}</span>
                      {item.issue_category && <span>{translateIssueCategory(item.issue_category)}</span>}
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusOpt.color}`}>
                        {statusOpt.label}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Right: Detail + Decision */}
            <div>
              {!selectedItem ? (
                <div className="rounded-2xl border border-dashed border-ink-900/20 bg-white/40 p-8 text-center">
                  <p className="text-sm text-ink-500">选择一项查看详情并作出决定。</p>
                </div>
              ) : (
                <div className="space-y-4 rounded-xl border border-ink-900/10 bg-white/60 p-4">
                  <div>
                    <h4 className="text-sm font-semibold text-ink-900">
                      {selectedItem.title || '未命名项目'}
                    </h4>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <span className="font-medium text-ink-500">风险等级</span>
                      <div className="mt-1">
                        <StatusPill tone={RISK_TONE[selectedItem.risk_level] || 'neutral'}>
                          {translateRiskLevel(selectedItem.risk_level)}
                        </StatusPill>
                      </div>
                    </div>
                    <div>
                      <span className="font-medium text-ink-500">分类</span>
                      <p className="mt-1 text-ink-900">{translateIssueCategory(selectedItem.issue_category) || '—'}</p>
                    </div>
                  </div>

                  {selectedItem.recommended_action && (
                    <div>
                      <p className="text-xs font-medium text-ink-500">建议行动</p>
                      <p className="text-sm text-ink-900">{selectedItem.recommended_action}</p>
                    </div>
                  )}

                  {selectedItem.benign_explanation && (
                    <div>
                      <p className="text-xs font-medium text-ink-500">良性解释</p>
                      <p className="text-sm text-ink-700">{selectedItem.benign_explanation}</p>
                    </div>
                  )}

                  {selectedItem.evidence_refs?.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-ink-500">证据引用</p>
                      <ul className="mt-1 space-y-1">
                        {selectedItem.evidence_refs.map((ref, i) => (
                          <li key={i} className="font-mono text-xs text-ink-700">
                            {typeof ref === 'string' ? ref : JSON.stringify(ref)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Decision controls */}
                  <div className="border-t border-ink-900/10 pt-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-500">决定</p>
                    <textarea
                      value={noteInput}
                      onChange={e => setNoteInput(e.target.value)}
                      name="review_note"
                      aria-label="复核备注"
                      autoComplete="off"
                      placeholder="备注（可选）…"
                      rows={2}
                      className="mb-3 w-full rounded-lg border border-ink-900/10 bg-white/80 px-3 py-2 text-sm"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => handleDecision('resolved')}
                        disabled={saving}
                        aria-label="标记为已解决"
                        className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
                      >
                        <FiCheckCircle aria-hidden="true" /> 已解决
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDecision('dismissed')}
                        disabled={saving}
                        aria-label="标记为忽略"
                        className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
                      >
                        <FiXCircle aria-hidden="true" /> 忽略
                      </button>
                    </div>
                    {selectedItem.decision?.status && (
                      <p className="mt-2 text-xs text-ink-500">
                        当前状态：<strong>{translateStatus(selectedItem.decision.status)}</strong>
                        {selectedItem.decision.note && <> · 备注：{selectedItem.decision.note}</>}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* SECTION 3: Follow-up Questions */}
      <section className="dossier-panel rounded-2xl p-6">
        <div className="border-b border-ink-900/10 pb-4">
          <h2 className="font-display text-lg font-semibold text-ink-900">追问清单</h2>
          <p className="mt-1 text-xs text-ink-500">
            {loadingFollowUps
              ? '加载中…'
              : allFollowUps.length === 0
                ? '暂无追问建议。'
                : `共 ${allFollowUps.length} 条追问`}
          </p>
        </div>

        {allFollowUps.length === 0 && !loadingFollowUps ? (
          <div className="mt-4 rounded-2xl border border-dashed border-ink-900/20 bg-white/40 p-6 text-center">
            <p className="text-sm text-ink-500">审查完成后将生成追问建议。</p>
          </div>
        ) : (
          <ul className="mt-4 space-y-2">
            {allFollowUps.map(({ findingId, question }) => (
              <li key={findingId + question} className="flex items-start gap-2 text-sm text-ink-700">
                <span className="mt-0.5 shrink-0 rounded-full bg-ink-900/5 px-1.5 py-0.5 font-mono text-[10px] text-ink-500">
                  {findingId}
                </span>
                <span className="min-w-0 flex-1">{question}</span>
                <button
                  type="button"
                  onClick={() => copyFollowUp(question)}
                  aria-label="复制追问"
                  className="shrink-0 rounded p-0.5 text-ink-300 hover:bg-ink-900/5 hover:text-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
                >
                  <FiClipboard size={12} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export default ActionsPage;
