import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { FiCheck, FiCpu, FiLink, FiPlay, FiRefreshCw, FiShuffle } from 'react-icons/fi';
import MetricCard from '../components/MetricCard.jsx';
import EmptyState from '../components/EmptyState.jsx';
import StatusPill from '../components/StatusPill.jsx';
import OverlapGraph from '../components/OverlapGraph.jsx';
import OverlapDetailDrawer from '../components/OverlapDetailDrawer.jsx';
import ProvenanceGraph from '../components/ProvenanceGraph.jsx';
import { visualImageUrl } from '../services/api.js';
import { useVisualArtifacts } from '../hooks/useVisualArtifacts.js';
import { useEmbeddingIndex } from '../hooks/useEmbeddingIndex.js';
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
    };
  } catch {
    return {
      filterRisk: 'all',
      filterCategory: 'all',
      panelIds: [],
      overlapId: '',
    };
  }
}

function writeEvidenceWorkspaceUrl({ filterRisk, filterCategory, panelIds, overlapId }) {
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
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  } catch {
    // URL state is progressive enhancement for deep-linking.
  }
}

function EvidenceReviewPage({ selectedCase }) {
  const initialWorkspace = useMemo(() => readEvidenceWorkspaceFromUrl(), []);
  const similarityThresholdId = useId();
  const previousCaseIdRef = useRef(selectedCase?.case_id || '');
  const [filterRisk, setFilterRisk] = useState(initialWorkspace.filterRisk);
  const [filterCategory, setFilterCategory] = useState(initialWorkspace.filterCategory);
  const [selectedPanelIds, setSelectedPanelIds] = useState(initialWorkspace.panelIds);
  const [selectedOverlapId, setSelectedOverlapId] = useState(initialWorkspace.overlapId);
  const [denseMaxPanels, setDenseMaxPanels] = useState(20);

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

  // Embedding index hook
  const {
    embeddingStatus,
    similarPairs,
    similarityThreshold,
    setSimilarityThreshold,
    isIndexing,
    similarityError,
    canFindSimilarPairs,
    indexedPanelCount,
    embeddingStatusBlocked,
    handleIndexPanels,
    handleLoadSimilarPairs,
  } = useEmbeddingIndex(selectedCase);

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
    });
  }, [filterRisk, filterCategory, selectedPanelIds, selectedOverlapId]);

  useEffect(() => {
    function handlePopState() {
      const nextWorkspace = readEvidenceWorkspaceFromUrl();
      setFilterRisk(nextWorkspace.filterRisk);
      setFilterCategory(nextWorkspace.filterCategory);
      setSelectedPanelIds(nextWorkspace.panelIds);
      setSelectedOverlapId(nextWorkspace.overlapId);
    }
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

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
          <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700">
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

      {/* SSCD Pre-filter: Two-step flow */}
      {embeddingStatusBlocked ? (
        <section className="dossier-panel rounded-[2rem] p-6">
          <h3 className="section-title flex items-center gap-2">
            <FiCpu className="text-ink-500" aria-hidden="true" />
            SSCD 相似 Panel 预筛
          </h3>
          <p className="mt-3 text-sm text-ink-400">
            SSCD embedding 模型未部署，此功能暂不可用。当前使用 copy-move / overlap-reuse / exact duplicate 作为主要视觉取证手段。
          </p>
        </section>
      ) : (
      <section className="dossier-panel rounded-[2rem] p-6">
        <h3 className="section-title flex items-center gap-2">
          <FiCpu className="text-ink-500" aria-hidden="true" />
          相似 Panel 预筛
        </h3>
        <p className="mt-2 text-sm text-ink-500">
          用 SSCD 神经网络提取 panel 向量，快速筛出可疑相似 panel 对（纯 CPU，不跑 Docker）。
          然后在 Step 2 中对筛出的子集跑 SILA Dense 精确检测。
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-4">
          {/* Embedding status */}
          <div className="text-sm">
            {embeddingStatus?.status === 'partial' ? (
              <span className="text-amber-700">
                部分索引 {indexedPanelCount}
                {embeddingStatus.expected_count ? ` / ${embeddingStatus.expected_count}` : ''} 个 panel
                {embeddingStatus.detail ? <span className="ml-2 text-ink-400">{embeddingStatus.detail}</span> : null}
              </span>
            ) : indexedPanelCount > 0 ? (
              <span className="text-emerald-700 inline-flex items-center gap-1">
                <FiCheck className="shrink-0" aria-hidden="true" />
                已索引 {indexedPanelCount} 个 panel
                {embeddingStatus.last_indexed_at && (
                  <span className="text-ink-400 ml-2">({embeddingStatus.last_indexed_at})</span>
                )}
              </span>
            ) : embeddingStatus?.status === 'queued' || embeddingStatus?.status === 'running' ? (
              <span className="text-ink-500">索引任务 {translateStatus(embeddingStatus.status)}</span>
            ) : embeddingStatus?.status === 'no_panels' ? (
              <span className="text-amber-700">没有可索引的 panel</span>
            ) : (
              <span className="text-ink-400">未索引</span>
            )}
          </div>

          {/* Index button */}
          <button
            type="button"
            onClick={handleIndexPanels}
            disabled={isIndexing || !selectedCase}
            className="flex items-center gap-2 rounded-xl border border-ink-900/10 bg-white/60 px-4 py-2 text-sm text-ink-900/70 transition hover:bg-white disabled:opacity-50"
          >
            <FiCpu className={isIndexing ? 'animate-spin' : ''} aria-hidden="true" />
            {isIndexing ? '索引中…' : indexedPanelCount > 0 ? '重新索引' : '索引 Panels'}
          </button>

          {/* Threshold slider */}
          <div className="flex items-center gap-2">
            <label htmlFor={similarityThresholdId} className="text-xs text-ink-500">相似度阈值:</label>
            <input
              id={similarityThresholdId}
              name="similarity_threshold"
              type="range"
              min="0.5"
              max="0.99"
              step="0.01"
              value={similarityThreshold}
              onChange={(e) => setSimilarityThreshold(Number(e.target.value))}
              aria-valuetext={similarityThreshold.toFixed(2)}
              className="w-24"
            />
            <span className="text-sm font-mono text-ink-700">{similarityThreshold.toFixed(2)}</span>
          </div>

          {/* Load pairs button */}
          <button
            type="button"
            onClick={handleLoadSimilarPairs}
            disabled={!canFindSimilarPairs}
            className="flex items-center gap-2 rounded-xl bg-ink-900/5 px-4 py-2 text-sm text-ink-900/70 transition hover:bg-ink-900/10 disabled:opacity-50"
          >
            <FiLink aria-hidden="true" />
            查找相似 Panel 对
          </button>
        </div>

        {similarityError && (
          <p className="mt-2 text-sm text-red-600">{similarityError}</p>
        )}

        {/* Similar pairs list */}
        {similarPairs.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-semibold text-ink-900/70">
              发现 {similarPairs.length} 对相似 Panel
              <span className="ml-2 text-xs text-ink-400">(threshold ≥ {similarityThreshold})</span>
            </h4>
            <div className="mt-2 max-h-48 overflow-y-auto space-y-1" style={{ overscrollBehavior: 'contain' }}>
              {similarPairs.map((pair, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border border-ink-900/5 bg-white/40 px-3 py-2">
                  <div className="flex items-center gap-3 text-sm">
                    <span className="font-mono text-ink-700">{pair.source_panel_id}</span>
                    <FiShuffle className="text-ink-300 shrink-0" aria-hidden="true" />
                    <span className="font-mono text-ink-700">{pair.target_panel_id}</span>
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                      {(pair.similarity * 100).toFixed(1)}%
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleSelectPair(pair)}
                    disabled={runningInvestigation}
                    className="rounded-lg bg-ink-900/5 px-3 py-1 text-xs text-ink-900/70 transition hover:bg-ink-900/10"
                  >
                    {runningInvestigation ? '运行中…' : '选中并跑 Dense'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {canFindSimilarPairs && similarPairs.length === 0 && !similarityError && (
          <p className="mt-3 text-sm text-ink-400">
            点击「查找相似 Panel 对」在已索引的 panel 中搜索相似对。
          </p>
        )}
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
              onSelectRelationship={(rel) => setSelectedOverlapId(rel.relationship_id || '')}
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
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-400">
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

      {/* Findings with Filter */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h3 className="section-title">视觉发现</h3>
            <p className="mt-2 text-sm text-ink-500">基于 relationship 生成的 visual finding cards。</p>
          </div>
          <FilterBar
            filterRisk={filterRisk}
            filterCategory={filterCategory}
            categories={categories}
            onRiskChange={setFilterRisk}
            onCategoryChange={setFilterCategory}
          />
        </div>

        {filteredFindings.length === 0 ? (
          <p className="mt-4 text-sm text-ink-500">未生成 visual finding 或当前筛选无结果。</p>
        ) : (
          <FindingCards findings={filteredFindings} panels={panels} caseId={selectedCase.case_id} />
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
        <div className="mt-4 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700">
          {error}
        </div>
      ) : null}
      {artifactErrors.length > 0 ? (
        <div className="mt-4 rounded-2xl border border-amber-300/60 bg-amber-50/80 p-4 text-sm text-amber-800">
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
                          <span className="font-mono text-[10px] text-ink-400">{rel.relationship_id}</span>
                          <span>score {(rel.score || 0).toFixed(3)}</span>
                          <span>{rel.match_method}</span>
                        </div>
                        <p className="mt-2 font-mono text-[11px] text-ink-400">
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

function FindingCards({ findings, panels, caseId }) {
  const panelsById = useMemo(() => {
    const map = {};
    for (const p of panels) {
      map[p.panel_id] = p;
    }
    return map;
  }, [panels]);

  return (
    <div className="mt-5 space-y-4">
      {findings.map((finding) => {
        const sourcePanel = panelsById[finding.source_panel_id] || {};
        const targetPanel = panelsById[finding.target_panel_id] || {};
        const riskTone = finding.risk_level === 'critical' ? 'critical' : finding.risk_level === 'high' ? 'warning' : 'neutral';
        const isWithinPanel = finding.source_panel_id === finding.target_panel_id;

        return (
          <article key={finding.finding_id} className="rounded-2xl border border-ink-900/8 bg-gradient-to-br from-paper-100/80 to-paper-200/60 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill tone={riskTone}>{translateRiskLevel(finding.risk_level)}</StatusPill>
              <span className="font-mono text-[10px] text-ink-400">{finding.finding_id}</span>
              <span className="rounded-full border border-ink-900/10 bg-white/60 px-2 py-0.5 text-xs">{finding.category}</span>
              {isWithinPanel && (
                <span className="rounded-full border border-signal-500/30 bg-signal-100/40 px-2 py-0.5 text-xs text-signal-700">
                  单图内检测
                </span>
              )}
            </div>

            <p className="mt-3 text-sm text-ink-700">
              {isWithinPanel
                ? `Panel ${finding.source_panel_id} 内部存在复制区域`
                : finding.summary}
            </p>
            <p className="mt-2 font-mono text-xs text-ink-400">
              score: {(finding.score || 0).toFixed(3)} | source: {finding.source_panel_id} | target: {finding.target_panel_id}
            </p>

            {/* Evidence visualization */}
            {isWithinPanel ? (
              // Single-panel copy-move: show one image with overlay mask
              <div className="mt-4 rounded-xl border border-ink-900/8 bg-white/60 p-3">
                <p className="mb-2 text-xs font-semibold text-ink-600">
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
              // Cross-panel copy-move: show side-by-side comparison
              <div className="mt-4 rounded-xl border border-ink-900/8 bg-white/60 p-3">
                <p className="mb-2 text-xs font-semibold text-ink-600">证据对比</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-ink-400">Source: {finding.source_panel_id}</p>
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
                    <p className="text-xs text-ink-400">Target: {finding.target_panel_id}</p>
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
                    <p className="text-xs text-ink-400">Overlay: <span className="font-mono">{finding.overlay_path}</span></p>
                  </div>
                )}
              </div>
            )}

            {/* Benign explanations */}
            {finding.benign_explanations && finding.benign_explanations.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-sm font-semibold text-ink-700">良性解释</summary>
                <ul className="mt-2 space-y-1 text-sm text-ink-600">
                  {finding.benign_explanations.map((exp, i) => (
                    <li key={i}>- {exp}</li>
                  ))}
                </ul>
              </details>
            )}

            {/* Manual review questions */}
            {finding.manual_review_questions && finding.manual_review_questions.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-sm font-semibold text-ink-700">人工复核问题</summary>
                <ul className="mt-2 space-y-1 text-sm text-ink-600">
                  {finding.manual_review_questions.map((q, i) => (
                    <li key={i}>- {q}</li>
                  ))}
                </ul>
              </details>
            )}
          </article>
        );
      })}
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
