import { useEffect, useState } from 'react';
import { FiArrowRight, FiChevronDown, FiChevronUp } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';
import RiskTrafficLight from '../components/RiskTrafficLight.jsx';
import FollowUpDisplay from '../components/FollowUpDisplay.jsx';
import LayerGroup from '../components/LayerGroup.jsx';
import EmptyState from '../components/EmptyState.jsx';
import { getRiskSummary, fetchVisualFindings, fetchCertaintyData } from '../services/api.js';
import { translateRiskLevel, translateIssueCategory } from '../utils/piLabels.js';
import { groupFindingsByLayer } from '../utils/layers.js';

const RISK_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };

function sortFindings(findings) {
  return [...findings].sort((a, b) => {
    const ra = RISK_ORDER[a.risk_level] ?? 4;
    const rb = RISK_ORDER[b.risk_level] ?? 4;
    return ra - rb;
  });
}

function FindingsPage({ selectedCase, onNavigate }) {
  const [riskSummary, setRiskSummary] = useState(null);
  const [visualFindings, setVisualFindings] = useState(null);
  const [certaintyById, setCertaintyById] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!selectedCase) return;
    setLoading(true);
    let cancelled = false;
    Promise.all([
      getRiskSummary(selectedCase.case_id).catch(() => null),
      fetchVisualFindings(selectedCase.case_id).catch(() => null),
      fetchCertaintyData(selectedCase.case_id).catch(() => null),
    ]).then(([rs, vf, cd]) => {
      if (!cancelled) {
        setRiskSummary(rs);
        setVisualFindings(vf);
        // Build certainty lookup by finding_id
        const lookup = {};
        if (Array.isArray(cd)) {
          for (const item of cd) {
            if (item.finding_id) lookup[item.finding_id] = item;
          }
        } else if (cd && typeof cd === 'object') {
          const items = cd.layers || cd.findings || [];
          for (const item of items) {
            if (item.finding_id) lookup[item.finding_id] = item;
          }
        }
        setCertaintyById(lookup);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [selectedCase]);

  if (!selectedCase) {
    return <EmptyState title="请先选择审查项目" message="选择审查项目后将展示审查发现。" />;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-ink-300 border-t-ink-700" aria-hidden="true" />
        <span className="ml-3 text-sm text-ink-500">加载中…</span>
      </div>
    );
  }

  const runCompleted = riskSummary && riskSummary.status !== 'unavailable';

  if (!runCompleted) {
    return (
      <EmptyState
        title="风险概览"
        message="审查完成后将在此展示风险概览。请先在运行监控中等待审查完成。"
      />
    );
  }

  const visualList = Array.isArray(visualFindings)
    ? visualFindings
    : (visualFindings?.findings || []);
  const topVisual = visualList.slice(0, 10);

  // Layer grouping (PRD2-T8): prefer backend-computed layers, fallback to client-side
  const findingsByLayer = riskSummary.findings_by_layer
    || groupFindingsByLayer(riskSummary.top_findings || []);
  const layerFindings = {
    layer_1: sortFindings(findingsByLayer.layer_1 || []),
    layer_2: sortFindings(findingsByLayer.layer_2 || []),
    layer_3: sortFindings(findingsByLayer.layer_3 || []),
  };
  const totalLayered = layerFindings.layer_1.length + layerFindings.layer_2.length + layerFindings.layer_3.length;

  return (
    <div className="space-y-6">
      {/* Section 1: Risk Overview */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <p className="metric-label">风险概览</p>
        <div className="mt-4">
          <RiskTrafficLight
            riskLevel={riskSummary.overall_risk}
            riskCounts={riskSummary.risk_counts}
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-6">
          <div>
            <p className="font-mono text-[11px] text-ink-500">发现总数</p>
            <p className="mt-1 text-2xl font-bold text-ink-900">{riskSummary.total_findings}</p>
          </div>
          <div>
            <p className="font-mono text-[11px] text-ink-500">中高风险</p>
            <p className="mt-1 text-2xl font-bold text-ink-900">{riskSummary.high_quality_count}</p>
          </div>
        </div>
      </section>

      {/* Section 2: Layered Findings (PRD2-T8) */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <p className="metric-label">分层发现</p>
        <p className="mt-1 font-mono text-[11px] text-ink-500">
          {totalLayered} 条发现，按置信度分为三层
        </p>
        <div className="mt-4 space-y-3">
          {['layer_1', 'layer_2', 'layer_3'].map((layerKey) => (
            <LayerGroup key={layerKey} layer={layerKey} findings={layerFindings[layerKey]}>
              {(items) => (
                <div className="space-y-3">
                  {items.map((finding, idx) => {
                    const fId = finding.finding_id || '';
                    const followUps = riskSummary.follow_ups?.[fId] || [];
                    const certainty = certaintyById[fId];
                    return (
                      <article key={fId || idx} className="rounded-xl border border-ink-900/8 bg-white/50 p-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[11px] text-ink-500">{fId}</span>
                          <StatusPill tone={finding.risk_level === 'critical' || finding.risk_level === 'high' ? 'risk' : 'warn'}>
                            {translateRiskLevel(finding.risk_level)}
                          </StatusPill>
                          {finding.issue_category ? (
                            <span className="font-mono text-[10px] text-ink-500">{translateIssueCategory(finding.issue_category)}</span>
                          ) : null}
                        </div>
                        <p className="mt-1.5 text-sm leading-6 text-ink-700">{finding.summary}</p>
                        {certainty ? (
                          <CertaintyLayers fact={certainty.fact} inference={certainty.inference} suggestion={certainty.suggestion} />
                        ) : null}
                        {followUps.length > 0 ? (
                          <div className="mt-3 border-t border-ink-900/5 pt-3">
                            <p className="mb-1.5 text-[11px] font-semibold text-ink-500">建议追问</p>
                            <FollowUpDisplay followUps={followUps} />
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              )}
            </LayerGroup>
          ))}
        </div>
      </section>

      {/* Section 3: Visual Findings */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="flex flex-col gap-3 border-b border-ink-900/10 pb-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="metric-label">视觉发现</p>
            <p className="mt-1 font-mono text-[11px] text-ink-500">
              {visualList.length} 个视觉发现
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => onNavigate('evidence')}
          >
            在证据审查中查看完整视觉证据
            <FiArrowRight aria-hidden="true" />
          </button>
        </div>
        {topVisual.length > 0 ? (
          <div className="mt-4 space-y-2">
            {topVisual.map((f, idx) => (
              <div
                key={f.finding_id || idx}
                className="flex items-center justify-between rounded-xl border border-ink-900/8 bg-white/45 px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <StatusPill tone={f.risk_level === 'critical' ? 'critical' : f.risk_level === 'high' ? 'risk' : 'neutral'}>
                    {translateRiskLevel(f.risk_level)}
                  </StatusPill>
                  <span className="font-mono text-xs text-ink-700">{f.finding_id}</span>
                  {f.category ? (
                    <span className="truncate text-xs text-ink-500">{f.category}</span>
                  ) : null}
                </div>
                <span className="shrink-0 font-mono text-xs text-ink-500">
                  score {(f.score || 0).toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-4 rounded-2xl bg-white/45 p-4 text-sm text-ink-500">
            暂无视觉发现。
          </p>
        )}
      </section>
    </div>
  );
}

export default FindingsPage;

/**
 * CertaintyLayers — Fact / Inference / Suggestion three-layer display.
 * Matches the prototype's core design: black for facts, purple for inferences, green for suggestions.
 */
function CertaintyLayers({ fact, inference, suggestion }) {
  const [expanded, setExpanded] = useState(false);
  if (!fact && !inference && !suggestion) return null;

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-[11px] font-semibold text-ink-500 transition hover:text-ink-700"
      >
        {expanded ? <FiChevronUp className="h-3 w-3" /> : <FiChevronDown className="h-3 w-3" />}
        三层确定性：事实 · 推断 · 建议
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {fact && (
            <div className="rounded-lg bg-ink-900 px-3 py-2 text-xs leading-5 text-paper-50 font-mono">
              <span className="mr-2 inline-block rounded bg-paper-50/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">事实</span>
              {fact}
            </div>
          )}
          {inference && (
            <div className="rounded-lg bg-purple-50 px-3 py-2 text-xs leading-5 text-purple-800 italic">
              <span className="mr-2 inline-block rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider not-italic">AI 推断</span>
              {inference}
            </div>
          )}
          {suggestion && (
            <div className="rounded-lg bg-signal-50 px-3 py-2 text-xs leading-5 text-signal-800">
              <span className="mr-2 inline-block rounded bg-signal-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">建议</span>
              {suggestion}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
