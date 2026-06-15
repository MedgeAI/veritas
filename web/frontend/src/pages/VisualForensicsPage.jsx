import { useCallback, useEffect, useMemo, useState } from 'react';
import StatusPill from '../components/StatusPill.jsx';
import {
  fetchVisualFigures,
  fetchVisualPanels,
  fetchVisualRelationships,
  fetchVisualFindings,
  visualImageUrl,
} from '../services/api.js';

function VisualForensicsPage({ selectedCase }) {
  const [figures, setFigures] = useState([]);
  const [panels, setPanels] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [findings, setFindings] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [filterRisk, setFilterRisk] = useState('all');
  const [filterCategory, setFilterCategory] = useState('all');

  const loadData = useCallback(async () => {
    if (!selectedCase) return;
    setLoading(true);
    setError('');
    try {
      const [figData, panelData, relData, findData] = await Promise.all([
        fetchVisualFigures(selectedCase.case_id).catch(() => ({ figures: [] })),
        fetchVisualPanels(selectedCase.case_id).catch(() => ({ panels: [] })),
        fetchVisualRelationships(selectedCase.case_id).catch(() => ({ relationships: [] })),
        fetchVisualFindings(selectedCase.case_id).catch(() => ({ findings: [] })),
      ]);
      setFigures(figData.figures || []);
      setPanels(panelData.panels || []);
      setRelationships(relData.relationships || []);
      setFindings(findData.findings || []);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, [selectedCase]);

  useEffect(() => {
    loadData();
  }, [loadData]);

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

  if (!selectedCase) {
    return <EmptyVisual />;
  }

  return (
    <div className="space-y-6">
      {/* Summary Metrics */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="metric-label">Visual Evidence Summary</p>
            <h2 className="mt-2 font-display text-2xl font-semibold">视觉取证概览</h2>
          </div>
          <button type="button" className="btn-ghost" onClick={loadData} disabled={loading}>
            {loading ? '加载中...' : '刷新'}
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
      </section>

      {/* Figures Grid */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <h3 className="section-title">Figures &amp; Panels</h3>
        <p className="mt-2 text-sm text-ink-500">PDF 提取的 figure 和检测到的 panel。</p>
        {figures.length === 0 ? (
          <p className="mt-4 text-sm text-ink-500">未提取到 figure 级图像证据。</p>
        ) : (
          <FigureGrid figures={figures} panels={panels} caseId={selectedCase.case_id} />
        )}
      </section>

      {/* Relationships Table */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <h3 className="section-title">Relationships</h3>
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
            <h3 className="section-title">Visual Findings</h3>
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

function MetricCard({ label, value }) {
  return (
    <div className="rounded-2xl border border-ink-900/8 bg-paper-100/60 p-4">
      <p className="metric-label">{label}</p>
      <p className="mt-2 font-display text-3xl font-bold text-ink-900">{value}</p>
    </div>
  );
}

function FigureGrid({ figures, panels, caseId }) {
  const panelsByFigure = useMemo(() => {
    const map = {};
    for (const panel of panels) {
      const parent = panel.parent_figure_id;
      if (!map[parent]) map[parent] = [];
      map[parent].push(panel);
    }
    return map;
  }, [panels]);

  return (
    <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
      {figures.map((figure) => {
        const figurePanels = panelsByFigure[figure.figure_id] || [];
        return (
          <div key={figure.figure_id} className="rounded-2xl border border-ink-900/8 bg-paper-100/70 p-4">
            <img
              src={visualImageUrl(caseId, figure.source_image_path)}
              alt={figure.label}
              className="h-[180px] w-full rounded-xl object-cover border border-ink-900/8 bg-ink-50"
              loading="lazy"
              onError={(e) => { e.target.style.display = 'none'; }}
            />
            <h4 className="mt-3 font-semibold text-ink-900">{figure.label}</h4>
            <p className="mt-1 text-xs text-ink-500 line-clamp-2">{figure.caption}</p>
            <p className="mt-2 font-mono text-[10px] text-ink-300">
              {figure.figure_id} | panels: {figure.panel_count}
            </p>
            {figurePanels.length > 0 && (
              <div className="mt-3 grid grid-cols-3 gap-2">
                {figurePanels.slice(0, 9).map((panel) => (
                  <div key={panel.panel_id} className="rounded-lg border border-ink-900/8 bg-paper-100/50 p-1">
                    <img
                      src={visualImageUrl(caseId, panel.crop_path)}
                      alt={panel.label}
                      className="h-[60px] w-full rounded object-cover bg-ink-50"
                      loading="lazy"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                    <p className="mt-1 text-center text-[10px] font-semibold">{panel.label}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
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

        return (
          <article key={finding.finding_id} className="rounded-2xl border border-ink-900/8 bg-gradient-to-br from-paper-100/80 to-paper-200/60 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill tone={riskTone}>{finding.risk_level}</StatusPill>
              <span className="rounded-full border border-ink-900/10 bg-white/60 px-2 py-0.5 text-xs">{finding.category}</span>
              <h4 className="font-semibold text-ink-900">{finding.finding_id}</h4>
            </div>

            <p className="mt-3 text-sm text-ink-700">{finding.summary}</p>
            <p className="mt-2 font-mono text-xs text-ink-400">
              score: {(finding.score || 0).toFixed(3)} | source: {finding.source_panel_id} | target: {finding.target_panel_id}
            </p>

            {/* Panel comparison */}
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-semibold text-ink-700">Panel 比较</summary>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs text-ink-400">Source: {finding.source_panel_id}</p>
                  <img
                    src={visualImageUrl(caseId, sourcePanel.crop_path || '')}
                    alt="source"
                    className="mt-1 h-[140px] w-full rounded-lg border border-ink-900/8 bg-ink-50 object-cover"
                    loading="lazy"
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                </div>
                <div>
                  <p className="text-xs text-ink-400">Target: {finding.target_panel_id}</p>
                  <img
                    src={visualImageUrl(caseId, targetPanel.crop_path || '')}
                    alt="target"
                    className="mt-1 h-[140px] w-full rounded-lg border border-ink-900/8 bg-ink-50 object-cover"
                    loading="lazy"
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                </div>
              </div>
              {finding.overlay_path && (
                <div className="mt-2">
                  <p className="text-xs text-ink-400">Overlay: <span className="font-mono">{finding.overlay_path}</span></p>
                </div>
              )}
            </details>

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
        <span className="text-ink-500">Risk:</span>
        <select
          className="input-field text-sm"
          value={filterRisk}
          onChange={(e) => onRiskChange(e.target.value)}
        >
          <option value="all">All</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <span className="text-ink-500">Category:</span>
        <select
          className="input-field text-sm"
          value={filterCategory}
          onChange={(e) => onCategoryChange(e.target.value)}
        >
          {categories.map((cat) => (
            <option key={cat} value={cat}>{cat === 'all' ? 'All' : cat}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

function EmptyVisual() {
  return (
    <section className="dossier-panel rounded-[2rem] p-8 text-center">
      <p className="font-display text-2xl font-semibold">请先选择 Case</p>
      <p className="mt-3 text-sm text-ink-500">Visual Forensics Gallery 展示图像取证候选、panel 检测和相似关系。</p>
    </section>
  );
}

export default VisualForensicsPage;
