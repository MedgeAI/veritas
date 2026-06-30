/**
 * IssuePage.jsx — Finding detail with three certainty layers (PRD Phase 5).
 *
 * Fetches ClientReportView to get certainty_by_finding_id[findingId].
 * Renders:
 *   - Back link
 *   - Header: severity tag + title + location
 *   - Three certainty layers (fact / inference / suggestion)
 *   - Resolution section (only if review_decision_allowed)
 *     - 4 choice cards
 */

import { ViewTransition, useState, useEffect } from 'react';
import { FiChevronLeft, FiCheckCircle as CheckCircle2, FiEdit3 as Edit3, FiPlay as Play, FiMessageSquare as MessageSquare } from 'react-icons/fi';
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
  const [selectedChoice, setSelectedChoice] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState(false);

  // Hook MUST be called unconditionally at the top — early returns BEFORE a
  // hook break React's rule-of-hooks (hook ordering).  The guards go INSIDE
  // the effect body instead; the effect becomes a no-op when context is missing.
  useEffect(() => {
    if (!caseId || !findingId) return;
    setLoading(true);
    fetchClientReport(caseId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [caseId, findingId]);

  if (!caseId) {
    return <ClientEmptyState type="issue" onNavigate={onNavigate} />;
  }

  if (!findingId) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <p className="font-display text-2xl text-ink-500">请先从报告的问题列表中选择一项</p>
      </div>
    );
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

  if (!data) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <p className="font-display text-2xl text-ink-500">未找到该问题的数据</p>
      </div>
    );
  }

  // Find the target finding across all layers
  const allFindings = [
    ...(data.risk?.findings_by_layer?.layer_1 || []),
    ...(data.risk?.findings_by_layer?.layer_2 || []),
    ...(data.risk?.findings_by_layer?.layer_3 || []),
  ];
  const finding = allFindings.find((f) => f.finding_id === findingId);

  if (!finding) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16">
        <div className="py-24 text-center text-sm text-ink-500">
          未找到该发现 (ID: {findingId})
        </div>
      </div>
    );
  }

  const certainty = data.certainty_by_finding_id?.[findingId] || {};
  const cfg = RISK_CONFIG[finding.risk_level] || RISK_CONFIG.info;
  const canDecide = finding.review_decision_allowed && finding.source_ref;

  const handleSubmitDecision = async () => {
    if (!selectedChoice || !canDecide) return;
    setSubmitting(true);
    try {
      await saveReviewDecision(caseId, finding.source_ref, {
        status: selectedChoice.status,
        decision_type: selectedChoice.decision_type,
        note: '',
      });
      setSubmitSuccess(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* Back link */}
      <button
        type="button"
        className="inline-flex items-center gap-1 text-xs text-ink-700 hover:text-ink-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 rounded-sm"
        onClick={() => onNavigate?.('report')}
      >
        <FiChevronLeft size={13} strokeWidth={1.5} /> 返回报告
      </button>

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
