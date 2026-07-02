/**
 * IssuePage.jsx — Finding detail with three certainty layers (PRD Phase 5).
 *
 * Single-page queue: PI processes findings one by one without returning to
 * the report. Prev/next buttons + keyboard shortcuts (← →).
 *
 * Two modes:
 *   1. With findingId: show finding detail + queue navigation
 *   2. Without findingId: show findings list grouped by layer for selection
 */

import { ViewTransition, useState, useEffect, useCallback, useMemo } from 'react';
import { FiChevronLeft, FiChevronRight, FiCheckCircle as CheckCircle2, FiEdit3 as Edit3, FiPlay as Play, FiMessageSquare as MessageSquare } from 'react-icons/fi';
import { fetchClientReport, saveReviewDecision } from '../../services/api';
import CertaintyLayer from '../../components/client/CertaintyLayer';
import ResolutionChoice from '../../components/client/ResolutionChoice';
import ClientEmptyState from '../../components/client/ClientEmptyState';
import { viewTransitionName } from '../../utils/viewTransitions';

const RISK_CONFIG = {
  critical: { label: '严重', en: 'Critical', color: 'text-risk-500' },
  high:     { label: '高',    en: 'High',    color: 'text-risk-500' },
  warning:  { label: '警告', en: 'Warning', color: 'text-accent-500' },
  medium:   { label: '警告', en: 'Warning', color: 'text-accent-500' },
  info:     { label: '注意', en: 'Info',    color: 'text-ink-500' },
  low:      { label: '低',    en: 'Low',     color: 'text-ink-500' },
};

const RESOLUTION_CHOICES = [
  {
    id: 'apply_suggestion',
    icon: CheckCircle2,
    title: '接受 AI 建议并修改',
    sub: 'Apply suggestion',
    desc: '按建议直接修改论文相关内容。无需重跑代码。',
    decision_type: 'apply_suggestion',
    status: 'resolved',
  },
  {
    id: 'manual_edit',
    icon: Edit3,
    title: '我自己修改',
    sub: 'Manual edit',
    desc: '下载建议补丁，自行决定如何修改。完成后上传新版本。',
    decision_type: 'manual_edit',
    status: 'resolved',
  },
  {
    id: 're_execute',
    icon: Play,
    title: '重跑代码',
    sub: 'Re-execute',
    desc: '如怀疑数据已更新，重跑相关实验并以新结果为准。',
    decision_type: 're_execute',
    status: 'open',
  },
  {
    id: 'appeal',
    icon: MessageSquare,
    title: '申诉说明',
    sub: 'Appeal',
    desc: '此差异属合理范围，提交说明纳入报告，把关者可见。',
    decision_type: 'appeal',
    status: 'needs_author_response',
  },
];

export default function IssuePage({ caseId, findingId, onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Hook MUST be called unconditionally at the top — early returns BEFORE a
  // hook break React's rule-of-hooks (hook ordering).  The guards go INSIDE
  // the effect body instead; the effect becomes a no-op when context is missing.
  useEffect(() => {
    if (!caseId) return;
    // Fetch report even without findingId — needed for the findings list
    setLoading(true);
    fetchClientReport(caseId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [caseId]);

  if (!caseId) {
    return <ClientEmptyState type="issue" onNavigate={onNavigate} />;
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16">
        <div className="py-24 text-center">
          <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-ink-200 border-t-ink-900" />
          <div className="mt-4 text-sm text-ink-500">加载中…</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16">
        <div className="py-24 text-center text-sm text-risk-500">
          加载失败：{error}
        </div>
      </div>
    );
  }

  if (!data || data.status !== 'ready') {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <p className="font-display text-2xl text-ink-500">报告尚未就绪</p>
      </div>
    );
  }

  if (!findingId) {
    return <IssueListView data={data} onNavigate={onNavigate} />;
  }

  return (
    <IssueDetailView
      caseId={caseId}
      data={data}
      findingId={findingId}
      onNavigate={onNavigate}
    />
  );
}

function allFindingsFromReport(data) {
  return [
    ...(data.risk?.findings_by_layer?.layer_1 || []),
    ...(data.risk?.findings_by_layer?.layer_2 || []),
    ...(data.risk?.findings_by_layer?.layer_3 || []),
  ];
}

function IssueListView({ data, onNavigate }) {
  const findingsWithLayer = useMemo(() => {
    const layer1 = (data.risk?.findings_by_layer?.layer_1 || []).map((f) => ({ ...f, _layer: 1 }));
    const layer2 = (data.risk?.findings_by_layer?.layer_2 || []).map((f) => ({ ...f, _layer: 2 }));
    const layer3 = (data.risk?.findings_by_layer?.layer_3 || []).map((f) => ({ ...f, _layer: 3 }));
    return [...layer1, ...layer2, ...layer3];
  }, [data]);
  const layerLabels = { 1: '确定性高', 2: '需人工复核', 3: '信息补充' };

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      <h1 className="font-display text-[32px] font-normal text-ink-900">
        选择需要复核的发现
      </h1>
      <p className="mt-3 text-sm text-ink-500">
        共 {findingsWithLayer.length} 项发现，点击查看详情并选择处理方式
      </p>
      {findingsWithLayer.length === 0 ? (
        <div className="mt-16 py-12 text-center text-sm text-ink-400">
          暂无发现项
        </div>
      ) : (
        [1, 2, 3].map((layer) => {
          const layerFindings = findingsWithLayer.filter((f) => f._layer === layer);
          if (layerFindings.length === 0) return null;
          return (
            <div key={layer} className="mt-10">
              <div className="mb-4 flex items-baseline gap-3 border-b border-ink-900/10 pb-2">
                <span className="font-mono text-[10px] tracking-[0.2em] text-paper-300">Layer {layer}</span>
                <span className="text-xs text-ink-500">{layerLabels[layer]}</span>
                <span className="ml-auto text-xs text-ink-400">{layerFindings.length} 项</span>
              </div>
              <ul className="space-y-2">
                {layerFindings.map((f) => {
                  const fCfg = RISK_CONFIG[f.risk_level] || RISK_CONFIG.info;
                  return (
                    <li key={f.finding_id}>
                      <button
                        type="button"
                        className="w-full rounded-sm border border-ink-900/8 bg-paper-50 px-5 py-4 text-left transition-colors hover:border-ink-900/20 hover:bg-paper-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
                        onClick={() => onNavigate?.('issue', { finding: f.finding_id })}
                      >
                        <div className="flex items-start gap-3">
                          <span className={`mt-0.5 shrink-0 text-[10px] font-medium uppercase tracking-wider ${fCfg.color}`}>
                            {fCfg.label}
                          </span>
                          <span className="min-w-0 flex-1 text-sm text-ink-800">
                            {f.summary || f.finding_id}
                          </span>
                          <span className="shrink-0 font-mono text-[10px] text-ink-400">
                            {f.finding_id}
                          </span>
                        </div>
                        {f.location && (
                          <div className="mt-1.5 pl-12 font-mono text-[11px] text-ink-400">
                            {f.location}
                          </div>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })
      )}
    </div>
  );
}

function DetailValue({ label, value }) {
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return null;
  }
  const display = Array.isArray(value) ? value.join(', ') : String(value);
  return (
    <div className="grid grid-cols-[132px_1fr] gap-4 border-b border-paper-200 py-2.5 last:border-b-0">
      <div className="font-mono text-[11px] text-ink-400">{label}</div>
      <div className="min-w-0 break-words text-sm text-ink-800">{display}</div>
    </div>
  );
}

function FindingDetailCard({ detail }) {
  if (!detail) {
    return (
      <div className="mt-10 border-t border-ink-900/10 pt-6">
        <div className="mb-4 flex items-baseline gap-3">
          <span className="font-display text-[20px] text-ink-900">证据细节</span>
        </div>
        <p className="text-sm text-ink-400">
          该发现的详细证据数据暂不可用。可能原因：原始 artifact 缺失或解析失败。
        </p>
      </div>
    );
  }
  const samples = Array.isArray(detail.sample_values) ? detail.sample_values.slice(0, 5) : [];
  return (
    <div className="mt-10 border-t border-ink-900/10 pt-6">
      <div className="mb-4 flex items-baseline gap-3">
        <span className="font-display text-[20px] text-ink-900">证据细节</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-400">{detail.type}</span>
      </div>

      {detail.type === 'source_data' && (
        <div>
          <DetailValue label="Workbook" value={detail.workbook} />
          <DetailValue label="Sheet" value={detail.sheet} />
          <DetailValue label="Columns" value={detail.columns} />
          <DetailValue label="Rows" value={detail.support_rows} />
          <DetailValue label="Pattern" value={detail.pattern_description} />
          <DetailValue label="Benign" value={detail.benign_explanations} />
          {samples.length > 0 && (
            <pre className="mt-4 max-h-52 overflow-auto rounded-sm bg-paper-100 p-3 text-[11px] leading-relaxed text-ink-700">
              {JSON.stringify(samples, null, 2)}
            </pre>
          )}
        </div>
      )}

      {detail.type === 'visual_relationship' && (
        <div>
          <DetailValue label="Source" value={detail.source_figure} />
          <DetailValue label="Target" value={detail.target_figure} />
          <DetailValue label="Score" value={detail.score} />
          <DetailValue label="Type" value={detail.relationship_type} />
          <DetailValue label="Benign" value={detail.benign_explanations} />
        </div>
      )}

      {detail.type === 'visual_copy_move' && (
        <div>
          <DetailValue label="Source" value={detail.source_panel} />
          <DetailValue label="Target" value={detail.target_panel} />
          <DetailValue label="Score" value={detail.score || detail.overlap_ratio} />
          <DetailValue label="Overlay" value={detail.overlay_path} />
          <DetailValue label="Benign" value={detail.benign_explanations} />
        </div>
      )}
    </div>
  );
}

function IssueDetailView({ caseId, data, findingId, onNavigate }) {
  const [selectedChoice, setSelectedChoice] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState(false);
  const [decisionError, setDecisionError] = useState(null);

  const allFindings = useMemo(() => allFindingsFromReport(data), [data]);
  const finding = useMemo(
    () => allFindings.find((f) => f.finding_id === findingId),
    [allFindings, findingId],
  );

  const currentIndex = allFindings.findIndex((f) => f.finding_id === findingId);
  const prevFinding = currentIndex > 0 ? allFindings[currentIndex - 1] : null;
  const nextFinding = currentIndex >= 0 && currentIndex < allFindings.length - 1
    ? allFindings[currentIndex + 1]
    : null;
  const totalFindings = allFindings.length;

  const goPrev = useCallback(() => {
    if (prevFinding) onNavigate?.('issue', { finding: prevFinding.finding_id });
  }, [prevFinding, onNavigate]);

  const goNext = useCallback(() => {
    if (nextFinding) onNavigate?.('issue', { finding: nextFinding.finding_id });
  }, [nextFinding, onNavigate]);

  useEffect(() => {
    setSelectedChoice(null);
    setSubmitSuccess(false);
    setDecisionError(null);
  }, [findingId]);

  useEffect(() => {
    if (!finding) return undefined;
    const handler = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft') goPrev();
      if (e.key === 'ArrowRight') goNext();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [finding, goPrev, goNext]);

  if (!finding) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16">
        <div className="py-24 text-center text-sm text-ink-500">
          未找到该发现 (ID: {findingId})
        </div>
      </div>
    );
  }

  const certainty = finding.certainty || {};
  const cfg = RISK_CONFIG[finding.risk_level] || RISK_CONFIG.info;
  const canDecide = finding.review_decision_allowed && finding.source_ref;

  const handleSubmitDecision = async () => {
    if (!selectedChoice || !canDecide) return;
    setSubmitting(true);
    setDecisionError(null);
    try {
      await saveReviewDecision(caseId, finding.source_ref, {
        status: selectedChoice.status,
        decision_type: selectedChoice.decision_type,
        note: '',
      });
      setSubmitSuccess(true);
    } catch (e) {
      setDecisionError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* Queue navigation bar */}
      <div className="flex items-center gap-3 border-b border-ink-900/10 pb-4">
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs text-ink-700 hover:text-ink-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 rounded-sm"
          onClick={() => onNavigate?.('report')}
        >
          <FiChevronLeft size={13} strokeWidth={1.5} /> 返回报告
        </button>
        <span className="text-ink-900/20">|</span>
        <span className="font-mono text-[11px] text-ink-400">
          {currentIndex + 1} / {totalFindings}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            disabled={!prevFinding}
            className="inline-flex items-center gap-1 rounded-sm border border-paper-300 px-3 py-1.5 text-xs text-ink-700 transition-colors hover:bg-paper-100 disabled:opacity-30 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
            onClick={goPrev}
          >
            <FiChevronLeft size={13} strokeWidth={1.5} /> 上一项
          </button>
          <button
            type="button"
            disabled={!nextFinding}
            className="inline-flex items-center gap-1 rounded-sm border border-paper-300 px-3 py-1.5 text-xs text-ink-700 transition-colors hover:bg-paper-100 disabled:opacity-30 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
            onClick={goNext}
          >
            下一项 <FiChevronRight size={13} strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {/* Header */}
      <div className="mt-8">
        <div className={`text-[10px] font-medium uppercase tracking-[0.25em] ${cfg.color}`}>
          {cfg.label} · {cfg.en} · {finding.finding_id}
        </div>
        <ViewTransition name={viewTransitionName('client-finding-title', finding.finding_id)} share="text-morph" default="none">
          <h1 className="mt-3.5 font-display text-[38px] font-normal leading-tight text-ink-900">
            {finding.summary}
          </h1>
        </ViewTransition>
        {finding.location && (
          <div className="mt-4 font-mono text-xs text-ink-500">
            {finding.location}
          </div>
        )}
      </div>

      {/* Three certainty layers */}
      <div className="mt-12">
        <CertaintyLayer
          fact={certainty.fact}
          inference={certainty.inference}
          suggestion={certainty.suggestion}
        />
      </div>

      <FindingDetailCard detail={finding.detail} />

      {/* Resolution section */}
      {canDecide && (
        <div className="mt-16">
          <div className="mb-5 flex items-baseline gap-4 border-b border-paper-200 pb-3.5">
            <span className="font-mono text-[11px] tracking-[0.15em] text-paper-300">
              —
            </span>
            <span className="font-display text-[22px] text-ink-900">
              请选择处理方式
            </span>
            <span className="ml-auto font-display text-[11px] italic text-ink-500">
              Resolution
            </span>
          </div>

          <div className="flex flex-col">
            {RESOLUTION_CHOICES.map((choice) => (
              <ResolutionChoice
                key={choice.id}
                icon={choice.icon}
                title={choice.title}
                subtitle={choice.sub}
                desc={choice.desc}
                selected={selectedChoice?.id === choice.id}
                onClick={() => setSelectedChoice(choice)}
              />
            ))}
          </div>

          {submitSuccess ? (
            <div className="mt-6 rounded-sm border border-[#5a6b46] bg-[#f3f6ed] p-4 text-sm text-[#5a6b46]">
              处理选择已提交，感谢您的反馈。
            </div>
          ) : (
            <>
              <div className="mt-6 flex items-center gap-3">
                <button
                  type="button"
                  className="rounded-sm bg-ink-900 px-5 py-2.5 text-xs text-paper-50 hover:bg-ink-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
                  disabled={!selectedChoice || submitting}
                  onClick={handleSubmitDecision}
                >
                  {submitting ? '提交中…' : '提交处理选择'}
                </button>
                {!selectedChoice && (
                  <span className="text-xs text-ink-500">请先选择一个处理方式</span>
                )}
              </div>
              {decisionError && (
                <div role="alert" className="mt-4 rounded-sm border border-risk-300/45 bg-risk-50/70 p-4 text-sm text-risk-700">
                  {decisionError}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Read-only note when no decision allowed */}
      {!canDecide && (
        <div className="mt-12 rounded-sm bg-dossier-50 px-5 py-4 text-xs text-ink-700">
          此发现暂无关联的处理入口。如有疑问，请联系支持团队。
        </div>
      )}
    </div>
  );
}
