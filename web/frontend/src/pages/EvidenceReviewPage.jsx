import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FiAlertTriangle,
  FiCheck,
  FiCircle,
  FiFlag,
  FiPlay,
  FiRefreshCw,
} from 'react-icons/fi';
import MetricCard from '../components/MetricCard.jsx';
import EmptyState from '../components/EmptyState.jsx';
import StatusPill from '../components/StatusPill.jsx';
import OverlapGraph from '../components/OverlapGraph.jsx';
import OverlapDetailDrawer from '../components/OverlapDetailDrawer.jsx';
import ProvenanceGraph from '../components/ProvenanceGraph.jsx';
import { visualImageUrl } from '../services/api.js';
import { useVisualArtifacts } from '../hooks/useVisualArtifacts.js';
import { useDenseInvestigation } from '../hooks/useDenseInvestigation.js';
import { translateStatus, translateRiskLevel } from '../utils/piLabels.js';

function readEvidenceWorkspaceFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    return {
      filterRisk: params.get('evidenceRisk') || 'all',
      filterCategory: params.get('evidenceCategory') || 'all',
      panelIds: (params.get('evidencePanels') || '').split(',').map((id) => id.trim()).filter(Boolean),
      overlapId: params.get('evidenceOverlap') || '',
      selectedFindingId: params.get('finding') || '',
      activeTab: params.get('tab') || 'evidence',
    };
  } catch {
    return {
      filterRisk: 'all',
      filterCategory: 'all',
      panelIds: [],
      overlapId: '',
      selectedFindingId: '',
      activeTab: 'evidence',
    };
  }
}

function writeEvidenceWorkspaceUrl({ filterRisk, filterCategory, panelIds, overlapId, selectedFindingId, activeTab }) {
  try {
    const url = new URL(window.location.href);
    if (filterRisk && filterRisk !== 'all') url.searchParams.set('evidenceRisk', filterRisk);
    else url.searchParams.delete('evidenceRisk');
    if (filterCategory && filterCategory !== 'all') url.searchParams.set('evidenceCategory', filterCategory);
    else url.searchParams.delete('evidenceCategory');
    if (panelIds.length) url.searchParams.set('evidencePanels', panelIds.join(','));
    else url.searchParams.delete('evidencePanels');
    if (overlapId) url.searchParams.set('evidenceOverlap', overlapId);
    else url.searchParams.delete('evidenceOverlap');
    if (selectedFindingId) url.searchParams.set('finding', selectedFindingId);
    else url.searchParams.delete('finding');
    if (activeTab && activeTab !== 'evidence') url.searchParams.set('tab', activeTab);
    else url.searchParams.delete('tab');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  } catch {
    // URL state is progressive enhancement for deep-linking.
  }
}

function EvidenceReviewPage({ selectedCase }) {
  const initialWorkspace = useMemo(() => readEvidenceWorkspaceFromUrl(), []);
  const previousCaseIdRef = useRef(selectedCase?.case_id || '');
  const [filterRisk, setFilterRisk] = useState(initialWorkspace.filterRisk);
  const [filterCategory, setFilterCategory] = useState(initialWorkspace.filterCategory);
  const [selectedPanelIds, setSelectedPanelIds] = useState(initialWorkspace.panelIds);
  const [selectedOverlapId, setSelectedOverlapId] = useState(initialWorkspace.overlapId);
  const [denseMaxPanels, setDenseMaxPanels] = useState(20);
  const [selectedFindingId, setSelectedFindingId] = useState(initialWorkspace.selectedFindingId || null);
  const [activeTab, setActiveTab] = useState(initialWorkspace.activeTab || 'evidence');
  const [decisions, setDecisions] = useState({});
  const [autoAdvanceId, setAutoAdvanceId] = useState(null);

  // Data fetching hook
  const {
    figures,
    panels,
    relationships,
    findings,
    overlapRelationships,
    provenanceGraph,
    investigationRecords,
    investigationResults,
    investigationArtifactErrors,
    loading,
    error,
    loadData,
    setInvestigationRecords,
    setInvestigationResults,
  } = useVisualArtifacts(selectedCase);

  // Dense investigation hook
  const { runDense, isRunning: runningInvestigation, denseError, setDenseError } = useDenseInvestigation(
    selectedCase,
    setInvestigationRecords,
    setInvestigationResults,
  );

  // Reset case-scoped UI state after the selected case changes.
  useEffect(() => {
    const nextCaseId = selectedCase?.case_id || '';
    if (previousCaseIdRef.current && previousCaseIdRef.current !== nextCaseId) {
      setSelectedPanelIds([]);
      setSelectedOverlapId('');
      setSelectedFindingId(null);
      setDecisions({});
      setAutoAdvanceId(null);
    }
    previousCaseIdRef.current = nextCaseId;
    setDenseError('');
  }, [selectedCase?.case_id, setDenseError]);

  useEffect(() => {
    writeEvidenceWorkspaceUrl({
      filterRisk,
      filterCategory,
      panelIds: selectedPanelIds,
      overlapId: selectedOverlapId,
      selectedFindingId: selectedFindingId || '',
      activeTab,
    });
  }, [filterRisk, filterCategory, selectedPanelIds, selectedOverlapId, selectedFindingId, activeTab]);

  useEffect(() => {
    function handlePopState() {
      const nextWorkspace = readEvidenceWorkspaceFromUrl();
      setFilterRisk(nextWorkspace.filterRisk);
      setFilterCategory(nextWorkspace.filterCategory);
      setSelectedPanelIds(nextWorkspace.panelIds);
      setSelectedOverlapId(nextWorkspace.overlapId);
      setSelectedFindingId(nextWorkspace.selectedFindingId || null);
      setActiveTab(nextWorkspace.activeTab || 'evidence');
    }
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // Auto-advance to next undecided finding after decision
  useEffect(() => {
    if (!autoAdvanceId) return undefined;
    const timeoutId = setTimeout(() => {
      setSelectedFindingId(autoAdvanceId);
      setAutoAdvanceId(null);
    }, 1500);
    return () => clearTimeout(timeoutId);
  }, [autoAdvanceId]);

  // Cancel auto-advance when user manually selects a finding
  useEffect(() => {
    if (selectedFindingId && autoAdvanceId && selectedFindingId !== autoAdvanceId) {
      setAutoAdvanceId(null);
    }
  }, [selectedFindingId, autoAdvanceId]);

  const clearPanelSelection = useCallback(() => {
    setSelectedPanelIds([]);
  }, []);

  // Select panels from a similar pair and immediately run dense investigation
  const handleSelectPair = useCallback(
    (pair) => {
      const panelIds = [pair.source_panel_id, pair.target_panel_id].filter(Boolean);
      setSelectedPanelIds(panelIds);
      runDense(panelIds, denseMaxPanels);
    },
    [runDense, denseMaxPanels],
  );

  const filteredFindings = useMemo(() => {
    return findings.filter((f) => {
      if (filterRisk !== 'all' && f.risk_level !== filterRisk) return false;
      if (filterCategory !== 'all' && f.category !== filterCategory) return false;
      return true;
    });
  }, [findings, filterRisk, filterCategory]);

  const categories = useMemo(() => {
    const cats = new Set(findings.map((f) => f.category));
    return ['all', ...Array.from(cats)];
  }, [findings]);

  const selectedOverlap = useMemo(
    () => overlapRelationships.find((rel) => rel.relationship_id === selectedOverlapId) || null,
    [overlapRelationships, selectedOverlapId],
  );

  const selectedFinding = useMemo(
    () => findings.find((f) => f.finding_id === selectedFindingId) || null,
    [findings, selectedFindingId],
  );

  const decidedCount = useMemo(
    () => filteredFindings.filter((f) => decisions[f.finding_id]).length,
    [filteredFindings, decisions],
  );

  const handleDecision = useCallback((findingId, status) => {
    setDecisions((prev) => ({
      ...prev,
      [findingId]: { status, note: '', timestamp: new Date().toISOString() },
    }));
    const idx = filteredFindings.findIndex((f) => f.finding_id === findingId);
    const remaining = filteredFindings.filter((f, i) => i > idx && !decisions[f.finding_id]);
    const nextFinding = remaining.length > 0 ? remaining[0] : filteredFindings.find((f, i) => i < idx && !decisions[f.finding_id]);
    if (nextFinding) {
      setAutoAdvanceId(nextFinding.finding_id);
    }
  }, [filteredFindings, decisions]);

  if (!selectedCase) {
    return (
      <EmptyState>
        <p className="font-display text-2xl font-semibold">请先选择审查项目</p>
        <p className="mt-3 text-sm text-ink-500">Visual Forensics Gallery 展示图像取证候选、panel 检测和相似关系。</p>
      </EmptyState>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Metrics */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="metric-label">Evidence Review</p>
            <h2 className="mt-2 font-display text-2xl font-semibold">证据审查</h2>
          </div>
          <button type="button" className="btn-ghost" onClick={loadData} disabled={loading}>
            <FiRefreshCw aria-hidden="true" />
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>

        {error ? (
          <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700" aria-live="polite" role="status">
            {error}
          </div>
        ) : null}

        <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-4">
          <MetricCard label="Figures" value={figures.length} />
          <MetricCard label="Panels" value={panels.length} />
          <MetricCard label="Relationships" value={relationships.length} />
          <MetricCard label="Visual Findings" value={findings.length} />
        </div>

        {/* 空状态提示 */}
        {!loading && !error && figures.length === 0 && panels.length === 0 && relationships.length === 0 && findings.length === 0 && (
          <div className="mt-5 rounded-2xl border border-dashed border-ink-900/20 bg-white/40 p-6 text-center">
            <p className="font-display text-lg font-semibold text-ink-700">暂无视觉取证数据</p>
            <p className="mt-2 text-sm text-ink-500">
              {selectedCase?.latest_run_status === 'running' || selectedCase?.latest_run_status === 'queued'
                ? '审查正在进行中，请稍后刷新查看结果。'
                : selectedCase?.latest_run_status === 'completed' || selectedCase?.latest_run_status === 'success'
                ? '本次审查未发现视觉证据，或视觉取证工具未运行。'
                : '请先在 Mission Control 中运行审查，或检查审查是否包含视觉取证步骤。'}
            </p>
          </div>
        )}
      </section>

      {/* Split View: Finding List + Evidence Detail */}
      {findings.length > 0 && (
        <section className="dossier-panel rounded-[2rem] p-6">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[380px_1fr]">
            {/* LEFT COLUMN - Finding List */}
            <div className="min-w-0">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <h3 className="section-title">视觉发现</h3>
                <FilterBar
                  filterRisk={filterRisk}
                  filterCategory={filterCategory}
                  categories={categories}
                  onRiskChange={setFilterRisk}
                  onCategoryChange={setFilterCategory}
                />
              </div>
              <div className="mt-3 flex items-center gap-2">
                <span className="text-xs text-ink-500">已审阅 {decidedCount}/{filteredFindings.length}</span>
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink-900/8">
                  <div
                    className="h-full rounded-full bg-signal-500 transition-all duration-300"
                    style={{ width: filteredFindings.length > 0 ? `${(decidedCount / filteredFindings.length) * 100}%` : '0%' }}
                  />
                </div>
              </div>
              <div className="mt-3">
                <FindingList
                  findings={filteredFindings}
                  decisions={decisions}
                  selectedFindingId={selectedFindingId}
                  onSelectFinding={setSelectedFindingId}
                />
              </div>
            </div>

            {/* RIGHT COLUMN - Evidence Detail */}
            <div className="min-w-0">
              <EvidenceDetailPanel
                finding={selectedFinding}
                panels={panels}
                caseId={selectedCase.case_id}
                activeTab={activeTab}
                onTabChange={setActiveTab}
                decisions={decisions}
                onDecision={handleDecision}
              />
            </div>
          </div>
        </section>
      )}

      <ManualInvestigationPanel
        selectedPanelList={selectedPanelIds}
        maxPanels={denseMaxPanels}
        onMaxPanelsChange={setDenseMaxPanels}
        onRunDense={() => runDense(selectedPanelIds, denseMaxPanels)}
        onClear={clearPanelSelection}
        running={runningInvestigation}
        error={denseError}
        artifactErrors={investigationArtifactErrors}
        records={investigationRecords}
      />

      {/* Overlap Reuse Graph */}
      {overlapRelationships.length > 0 && (
        <section className="dossier-panel rounded-[2rem] p-6">
          <h3 className="section-title">图像区域复用检测</h3>
          <p className="mt-2 text-sm text-ink-500">
            跨 panel 局部图像区域复用检测 — 点击 edge 查看详情。
          </p>
          <div className="mt-4">
            <OverlapGraph
              relationships={overlapRelationships}
              panels={panels}
              onSelectRelationship={(rel) => setSelectedOverlapId(rel.relationship_id)}
            />
          </div>
          <div className="mt-3 text-xs text-ink-500">
            共 {overlapRelationships.length} 个 overlap 关系
          </div>
        </section>
      )}

      {/* Overlap Detail Drawer */}
      {selectedOverlap && (
        <OverlapDetailDrawer
          relationship={selectedOverlap}
          caseId={selectedCase?.case_id}
          onClose={() => setSelectedOverlapId('')}
        />
      )}

      {/* Provenance Graph (MST) */}
      {provenanceGraph && provenanceGraph.nodes && provenanceGraph.nodes.length > 0 && (
        <section className="dossier-panel rounded-[2rem] p-6">
          <h3 className="section-title">溯源图 (MST)</h3>
          <p className="mt-2 text-sm text-ink-500">
            基于 RootSIFT 描述子递归 BFS 匹配的 figure 级溯源图。MST 边表示最小生成树，
            非 MST 边表示额外的匹配关系。点击节点查看连接详情。
          </p>
          <div className="mt-4">
            <ProvenanceGraph
              graph={provenanceGraph}
              caseId={selectedCase.case_id}
            />
          </div>
          {provenanceGraph.statistics && (
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-500">
              <span>节点：{provenanceGraph.statistics.node_count || 0}</span>
              <span>边：{provenanceGraph.statistics.edge_count || 0}</span>
              <span>连通分量：{provenanceGraph.statistics.component_count || 0}</span>
              {provenanceGraph.statistics.max_weight && (
                <span>Max Weight: {provenanceGraph.statistics.max_weight}</span>
              )}
              {provenanceGraph.processing_time_seconds && (
                <span>Time: {provenanceGraph.processing_time_seconds}s</span>
              )}
            </div>
          )}
        </section>
      )}

      <InvestigationResults results={investigationResults} caseId={selectedCase.case_id} />

      {/* Relationships Table */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <h3 className="section-title">图像关系</h3>
        <p className="mt-2 text-sm text-ink-500">Panel 之间的相似或复用关系，按 score 排序。</p>
        {relationships.length === 0 ? (
          <p className="mt-4 text-sm text-ink-500">未发现 panel 间相似关系。</p>
        ) : (
          <RelationshipTable relationships={relationships} />
        )}
      </section>
    </div>
  );
}

const TOOL_LABEL_MAP = {
  'visual.copy_move_dense': '定向Copy-move',
  'visual.overlap_reuse': '区域复用检测',
};
function toolLabel(toolId) {
  return TOOL_LABEL_MAP[toolId] || toolId;
}

function ManualInvestigationPanel({
  selectedPanelList,
  maxPanels,
  onMaxPanelsChange,
  onRunDense,
  onClear,
  running,
  error,
  artifactErrors,
  records,
}) {
  const disabled = selectedPanelList.length === 0 || running;
  const maxPanelsId = useId();
  return (
    <section className="dossier-panel rounded-[2rem] p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="metric-label">Targeted Analysis</p>
          <h3 className="mt-2 font-display text-2xl font-semibold">定向图像分析</h3>
          <p className="mt-2 max-w-3xl text-sm text-ink-500">
            已选择 {selectedPanelList.length} 个 panel。Dense copy-move 只会处理选中 panel，并按预算截断。
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label htmlFor={maxPanelsId} className="w-32 text-sm text-ink-500">
            Max panels
            <input
              id={maxPanelsId}
              name="dense_max_panels"
              type="number"
              min="1"
              max="50"
              inputMode="numeric"
              autoComplete="off"
              className="input-field mt-1 py-2"
              value={maxPanels}
              onChange={(event) => onMaxPanelsChange(event.target.value === '' ? '' : Number(event.target.value))}
            />
          </label>
          <button type="button" className="btn-secondary" onClick={onClear} disabled={selectedPanelList.length === 0 || running}>
            清空选择
          </button>
          <button type="button" className="btn-primary" onClick={onRunDense} disabled={disabled}>
            <FiPlay aria-hidden="true" />
            {running ? '运行中…' : 'Run SILA Dense'}
          </button>
        </div>
      </div>
      {error ? (
        <div className="mt-4 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700" aria-live="polite" role="status">
          {error}
        </div>
      ) : null}
      {artifactErrors.length > 0 ? (
        <div className="mt-4 rounded-2xl border border-amber-300/60 bg-amber-50/80 p-4 text-sm text-amber-800" aria-live="polite" role="status">
          {artifactErrors.slice(0, 3).map((entry) => (
            <p key={`${entry.action_id || 'action'}-${entry.artifact}`}>
              {entry.error}
            </p>
          ))}
        </div>
      ) : null}
      {records.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {records.slice(0, 6).map((record) => (
            <span key={`${record.action_id}-${record.created_at}`} className="mono-chip">
              {toolLabel(record.tool_id)}: {translateStatus(record.status)}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function InvestigationResults({ results, caseId }) {
  if (!results.length) {
    return null;
  }
  return (
    <section className="dossier-panel rounded-[2rem] p-6">
      <h3 className="section-title">定向分析结果</h3>
      <div className="mt-5 space-y-4">
        {results.slice(0, 6).map((entry, index) => {
          const result = entry.result || {};
          const record = entry.record || {};
          const relationships = result.relationships || [];
          const errors = result.errors || [];
          return (
            <article key={`${entry.artifact || index}`} className="rounded-2xl border border-ink-900/8 bg-paper-100/70 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill tone={result.status === 'ran' ? 'neutral' : 'warning'}>{result.status || record.status}</StatusPill>
                <span className="mono-chip">panels: {result.panel_count || 0}</span>
                <span className="mono-chip">relationships: {result.relationship_count || relationships.length}</span>
              </div>
              {errors.length > 0 ? (
                <p className="mt-3 text-sm text-risk-700">{errors.slice(0, 2).join(' | ')}</p>
              ) : null}
              {relationships.length === 0 ? (
                <p className="mt-3 text-sm text-ink-500">本次未产生高于阈值的 dense copy-move relationship。</p>
              ) : (
                <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                  {relationships.slice(0, 8).map((rel) => {
                    const maskPath = rel.metadata?.mask_path;
                    const overlayPath = rel.overlay_path || maskPath;
                    return (
                      <div key={rel.relationship_id} className="rounded-xl border border-ink-900/8 bg-white/55 p-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
                          <span className="font-mono text-[10px] text-ink-500">{rel.relationship_id}</span>
                          <span>score {(rel.score || 0).toFixed(3)}</span>
                          <span>{rel.match_method}</span>
                        </div>
                        <p className="mt-2 font-mono text-[11px] text-ink-500">
                          {rel.source_panel_id} &rarr; {rel.target_panel_id}
                        </p>
                        {overlayPath ? (
                          <img
                            src={visualImageUrl(caseId, overlayPath)}
                            alt={rel.relationship_id}
                            className="mt-3 h-[180px] w-full rounded-lg border border-ink-900/8 bg-ink-50 object-contain"
                            width="400"
                            height="180"
                            loading="lazy"
                            decoding="async"
                            onError={(event) => { event.target.style.display = 'none'; }}
                          />
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function RelationshipTable({ relationships }) {
  const sorted = useMemo(() => {
    return [...relationships].sort((a, b) => (b.score || 0) - (a.score || 0));
  }, [relationships]);

  return (
    <div className="mt-5 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-900/10 text-left">
            <th className="py-2 pr-4 font-semibold text-ink-500">Source Panel</th>
            <th className="py-2 pr-4 font-semibold text-ink-500">Target Panel</th>
            <th className="py-2 pr-4 font-semibold text-ink-500">Type</th>
            <th className="py-2 pr-4 font-semibold text-ink-500">Score</th>
            <th className="py-2 pr-4 font-semibold text-ink-500">Method</th>
            <th className="py-2 pr-4 font-semibold text-ink-500">Inliers</th>
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, 30).map((rel) => (
            <tr key={rel.relationship_id} className="border-b border-ink-900/5">
              <td className="py-2 pr-4 font-mono text-xs">{rel.source_panel_id}</td>
              <td className="py-2 pr-4 font-mono text-xs">{rel.target_panel_id}</td>
              <td className="py-2 pr-4">
                <StatusPill tone={rel.score >= 0.7 ? 'critical' : rel.score >= 0.4 ? 'warning' : 'neutral'}>
                  {rel.source_type}
                </StatusPill>
              </td>
              <td className="py-2 pr-4 font-mono">{(rel.score || 0).toFixed(3)}</td>
              <td className="py-2 pr-4 font-mono text-xs">{rel.match_method}</td>
              <td className="py-2 pr-4">{rel.inlier_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DecisionStatusIcon({ status }) {
  switch (status) {
    case 'follow_up':
      return <FiAlertTriangle className="text-amber-500" aria-hidden="true" />;
    case 'explained':
      return <FiCheck className="text-emerald-500" aria-hidden="true" />;
    case 'flagged':
      return <FiFlag className="text-risk-500" aria-hidden="true" />;
    default:
      return <FiCircle className="text-ink-500" aria-hidden="true" />;
  }
}

function FindingList({ findings, decisions, selectedFindingId, onSelectFinding }) {
  return (
    <div className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-240px)] lg:overflow-y-auto" style={{ overscrollBehavior: 'contain' }}>
      {findings.length === 0 ? (
        <p className="mt-2 text-sm text-ink-500">当前筛选无结果。</p>
      ) : (
        <div className="space-y-1">
          {findings.map((finding) => {
            const isSelected = finding.finding_id === selectedFindingId;
            const decision = decisions[finding.finding_id];
            const riskTone = finding.risk_level === 'critical' ? 'critical' : finding.risk_level === 'high' ? 'warning' : 'neutral';

            return (
              <button
                key={finding.finding_id}
                type="button"
                onClick={() => onSelectFinding(finding.finding_id)}
                className={`relative w-full rounded-xl border px-4 py-3 pr-10 text-left transition ${
                  isSelected
                    ? 'border-signal-500 ring-2 ring-signal-500 bg-signal-50/30'
                    : 'border-ink-900/8 hover:bg-ink-900/5'
                }`}
              >
                <div className="absolute right-3 top-3">
                  <DecisionStatusIcon status={decision?.status} />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusPill tone={riskTone}>{translateRiskLevel(finding.risk_level)}</StatusPill>
                  <span className="font-mono text-[10px] text-ink-500">{finding.finding_id}</span>
                  <span className="rounded-full border border-ink-900/10 bg-white/60 px-1.5 py-0.5 text-[10px]">{finding.category}</span>
                </div>
                <p className="mt-1.5 text-sm text-ink-700 line-clamp-2">
                  {finding.summary}
                </p>
                <div className="mt-1.5 flex items-center justify-between">
                  <span className="font-mono text-xs text-ink-500">score {(finding.score || 0).toFixed(3)}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EvidenceDetailPanel({ finding, panels, caseId, activeTab, onTabChange, decisions, onDecision }) {
  const panelsById = useMemo(() => {
    const map = {};
    for (const p of panels) {
      map[p.panel_id] = p;
    }
    return map;
  }, [panels]);

  const [noteInput, setNoteInput] = useState('');

  useEffect(() => {
    setNoteInput(decisions[finding?.finding_id]?.note || '');
  }, [finding?.finding_id, decisions]);

  const tabs = [
    { id: 'evidence', label: '证据' },
    { id: 'analysis', label: '分析' },
    { id: 'raw', label: '原始数据' },
  ];

  if (!finding) {
    return (
      <div className="flex min-h-[400px] items-center justify-center rounded-2xl border border-dashed border-ink-900/20 bg-white/40">
        <p className="text-sm text-ink-500">选择左侧发现查看详情</p>
      </div>
    );
  }

  const sourcePanel = panelsById[finding.source_panel_id] || {};
  const targetPanel = panelsById[finding.target_panel_id] || {};
  const isWithinPanel = finding.source_panel_id === finding.target_panel_id;
  const currentDecision = decisions[finding.finding_id];

  return (
    <div className="rounded-2xl border border-ink-900/8 bg-paper-100/50">
      {/* Tab bar */}
      <div className="flex border-b border-ink-900/10">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => onTabChange(tab.id)}
            className={`px-4 py-3 text-sm font-medium transition ${
              activeTab === tab.id
                ? 'border-b-2 border-signal-500 text-ink-900'
                : 'text-ink-500 hover:text-ink-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-6">
        {activeTab === 'evidence' && (
          <div>
            {isWithinPanel ? (
              <div className="rounded-xl border border-ink-900/8 bg-white/60 p-3">
                <p className="mb-2 text-xs font-semibold text-ink-500">
                  证据：同一 panel 内的复制区域（白色 mask）
                </p>
                <div className="relative inline-block">
                  <img
                    src={visualImageUrl(caseId, sourcePanel.crop_path || '')}
                    alt="panel with copy-move detection"
                    className="h-[200px] rounded-lg border border-ink-900/8 bg-ink-50 object-contain"
                    width="400"
                    height="200"
                    loading="lazy"
                    decoding="async"
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                  {finding.overlay_path && (
                    <img
                      src={visualImageUrl(caseId, finding.overlay_path)}
                      alt="overlay mask"
                      className="absolute inset-0 h-[200px] rounded-lg object-contain opacity-50 mix-blend-screen"
                      width="400"
                      height="200"
                      loading="lazy"
                      decoding="async"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                  )}
                </div>
                <p className="mt-2 text-xs text-ink-500">
                  白色区域表示检测到的复制区域。可能是复制粘贴的条带或图像内容。
                </p>
              </div>
            ) : (
              <div className="rounded-xl border border-ink-900/8 bg-white/60 p-3">
                <p className="mb-2 text-xs font-semibold text-ink-500">证据对比</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-ink-500">Source: {finding.source_panel_id}</p>
                    <img
                      src={visualImageUrl(caseId, sourcePanel.crop_path || '')}
                      alt="source"
                      className="mt-1 h-[140px] w-full rounded-lg border border-ink-900/8 bg-ink-50 object-cover"
                      width="400"
                      height="140"
                      loading="lazy"
                      decoding="async"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                  </div>
                  <div>
                    <p className="text-xs text-ink-500">Target: {finding.target_panel_id}</p>
                    <img
                      src={visualImageUrl(caseId, targetPanel.crop_path || '')}
                      alt="target"
                      className="mt-1 h-[140px] w-full rounded-lg border border-ink-900/8 bg-ink-50 object-cover"
                      width="400"
                      height="140"
                      loading="lazy"
                      decoding="async"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                  </div>
                </div>
                {finding.overlay_path && (
                  <div className="mt-2">
                    <p className="text-xs text-ink-500">Overlay: <span className="font-mono">{finding.overlay_path}</span></p>
                  </div>
                )}
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="mono-chip">score: {(finding.score || 0).toFixed(3)}</span>
              <span className="mono-chip">source: {finding.source_panel_id}</span>
              <span className="mono-chip">target: {finding.target_panel_id}</span>
            </div>
          </div>
        )}

        {activeTab === 'analysis' && (
          <div className="space-y-4">
            {finding.benign_explanations && finding.benign_explanations.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-ink-700">良性解释</h4>
                <ul className="mt-2 space-y-1 text-sm text-ink-500">
                  {finding.benign_explanations.map((exp, i) => (
                    <li key={i}>- {exp}</li>
                  ))}
                </ul>
              </div>
            )}
            {finding.manual_review_questions && finding.manual_review_questions.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-ink-700">人工复核问题</h4>
                <ul className="mt-2 space-y-1 text-sm text-ink-500">
                  {finding.manual_review_questions.map((q, i) => (
                    <li key={i}>- {q}</li>
                  ))}
                </ul>
              </div>
            )}
            {!finding.benign_explanations?.length && !finding.manual_review_questions?.length && (
              <p className="text-sm text-ink-500">暂无分析数据。</p>
            )}
          </div>
        )}

        {activeTab === 'raw' && (
          <div className="space-y-3">
            <div>
              <h4 className="text-xs font-semibold text-ink-500">Finding ID</h4>
              <p className="mt-1 font-mono text-sm text-ink-700">{finding.finding_id}</p>
            </div>
            <div>
              <h4 className="text-xs font-semibold text-ink-500">Category</h4>
              <p className="mt-1 text-sm text-ink-700">{finding.category}</p>
            </div>
            <div>
              <h4 className="text-xs font-semibold text-ink-500">Risk Level</h4>
              <p className="mt-1 text-sm text-ink-700">{finding.risk_level}</p>
            </div>
            <div>
              <h4 className="text-xs font-semibold text-ink-500">Source Panel</h4>
              <p className="mt-1 font-mono text-sm text-ink-700">{finding.source_panel_id}</p>
              {sourcePanel.crop_path && (
                <p className="font-mono text-xs text-ink-500">{sourcePanel.crop_path}</p>
              )}
            </div>
            <div>
              <h4 className="text-xs font-semibold text-ink-500">Target Panel</h4>
              <p className="mt-1 font-mono text-sm text-ink-700">{finding.target_panel_id}</p>
              {targetPanel.crop_path && (
                <p className="font-mono text-xs text-ink-500">{targetPanel.crop_path}</p>
              )}
            </div>
            {finding.overlay_path && (
              <div>
                <h4 className="text-xs font-semibold text-ink-500">Overlay Path</h4>
                <p className="mt-1 font-mono text-xs text-ink-700">{finding.overlay_path}</p>
              </div>
            )}
            {finding.evidence_refs && finding.evidence_refs.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-ink-500">Evidence Refs</h4>
                <ul className="mt-1 space-y-1">
                  {finding.evidence_refs.map((ref, i) => (
                    <li key={i} className="font-mono text-xs text-ink-700">
                      {typeof ref === 'string' ? ref : JSON.stringify(ref)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Decision bar */}
      <div className="border-t border-ink-900/10 p-6">
        <textarea
          value={noteInput}
          onChange={(e) => setNoteInput(e.target.value)}
          name="finding_note"
          aria-label="Finding 备注"
          autoComplete="off"
          placeholder="备注（可选）…"
          rows={2}
          className="mb-3 w-full rounded-lg border border-ink-900/10 bg-white/80 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onDecision(finding.finding_id, 'follow_up')}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
              currentDecision?.status === 'follow_up'
                ? 'border-amber-300 bg-amber-100 text-amber-800'
                : 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
            }`}
          >
            {currentDecision?.status === 'follow_up' && <FiCheck aria-hidden="true" />}
            <FiAlertTriangle aria-hidden="true" />
            需要跟进
          </button>
          <button
            type="button"
            onClick={() => onDecision(finding.finding_id, 'explained')}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
              currentDecision?.status === 'explained'
                ? 'border-emerald-300 bg-emerald-100 text-emerald-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
            }`}
          >
            {currentDecision?.status === 'explained' && <FiCheck aria-hidden="true" />}
            <FiCheck aria-hidden="true" />
            已解释
          </button>
          <button
            type="button"
            onClick={() => onDecision(finding.finding_id, 'flagged')}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
              currentDecision?.status === 'flagged'
                ? 'border-risk-300 bg-risk-100 text-risk-800'
                : 'border-risk-200 bg-risk-50 text-risk-700 hover:bg-risk-100'
            }`}
          >
            {currentDecision?.status === 'flagged' && <FiCheck aria-hidden="true" />}
            <FiFlag aria-hidden="true" />
            标记为风险
          </button>
          {currentDecision && (
            <span className="ml-2 text-xs text-ink-500">
              已决定
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterBar({ filterRisk, filterCategory, categories, onRiskChange, onCategoryChange }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-ink-500">风险：</span>
        <select
          className="input-field text-sm"
          name="visual_risk_filter"
          value={filterRisk}
          onChange={(e) => onRiskChange(e.target.value)}
        >
          <option value="all">全部</option>
          <option value="critical">极高</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <span className="text-ink-500">类别：</span>
        <select
          className="input-field text-sm"
          name="visual_category_filter"
          value={filterCategory}
          onChange={(e) => onCategoryChange(e.target.value)}
        >
          <option value="all">全部</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>{cat === 'all' ? '全部' : cat}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

export default EvidenceReviewPage;
