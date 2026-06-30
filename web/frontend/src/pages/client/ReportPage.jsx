/**
 * ReportPage.jsx — Client report view (PRD Phase 4).
 *
 * Fetches ClientReportView from BFF and renders:
 *   - RoleBar (author/reviewer toggle, visual only)
 *   - CertHead (report metadata)
 *   - GradeStrip (A/B/C/D horizontal bar)
 *   - GradeNote (summary)
 *   - DimGrid (4 dimension cards)
 *   - Findings list (FindingCard for each finding)
 *   - Bottom bar (action buttons differ by role)
 */

import { useState, useEffect } from 'react';
import { FiRefreshCw, FiShield, FiLock, FiDownload } from 'react-icons/fi';
import { fetchClientReport } from '../../services/api';
import GradeStrip from '../../components/client/GradeStrip';
import FindingCard from '../../components/client/FindingCard';
import ClientEmptyState from '../../components/client/ClientEmptyState';

const STATUS_LABELS = {
  unavailable: '报告不可用',
  running: '核查进行中',
  ready: '报告就绪',
  failed: '核查失败',
};

export default function ReportPage({ caseId, onNavigate }) {
  const [role, setRole] = useState('author');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!caseId) { setLoading(false); return; }
    setLoading(true);
    fetchClientReport(caseId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [caseId]);

  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error} />;
  }

  if (!data) {
    return <ClientEmptyState type="report" caseId={caseId} onNavigate={onNavigate} />;
  }

  if (data.status !== 'ready') {
    return <StatusState status={data.status} onNavigate={onNavigate} />;
  }

  const { case: caseInfo, certification, risk } = data;
  const grade = certification?.grade || '?';
  const summary = certification?.summary || '';
  const dimensions = certification?.dimensions || [];

  // Flatten findings from all layers
  const allFindings = [
    ...(risk?.findings_by_layer?.layer_1 || []),
    ...(risk?.findings_by_layer?.layer_2 || []),
    ...(risk?.findings_by_layer?.layer_3 || []),
  ];

  const isAuthor = role === 'author';

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* RoleBar */}
      <div className="flex items-center gap-2 border-b border-ink-900/10 pb-7">
        <span className="mr-2 text-[10px] font-medium uppercase tracking-[0.2em] text-ink-500">
          视图
        </span>
        <button
          type="button"
          onClick={() => setRole('author')}
          aria-pressed={isAuthor}
          className={`rounded-sm border px-3.5 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 ${
            isAuthor
              ? 'border-ink-900 bg-ink-900 text-paper-50'
              : 'border-paper-300 text-ink-500 hover:bg-paper-100'
          }`}
        >
          作者
        </button>
        <button
          type="button"
          onClick={() => setRole('reviewer')}
          aria-pressed={!isAuthor}
          className={`rounded-sm border px-3.5 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 ${
            !isAuthor
              ? 'border-ink-900 bg-ink-900 text-paper-50'
              : 'border-paper-300 text-ink-500 hover:bg-paper-100'
          }`}
        >
          把关者
        </button>
        <div className="flex-1" />
        {!isAuthor && (
          <span className="inline-flex items-center gap-1.5 text-[11px] italic text-ink-500">
            <FiLock size={11} strokeWidth={1.5} /> 只读模式 · Read-only
          </span>
        )}
      </div>

      {/* CertHead */}
      <div className="mt-12 mb-12">
        <div className="flex items-baseline justify-between border-b border-ink-900 pb-6">
          <div className="text-[10px] font-medium uppercase tracking-[0.3em] text-ink-500">
            Verification Report · 独立核查报告
          </div>
          <div className="font-mono text-xs tracking-wider text-ink-900">
            {certification?.report_id || '生成中…'}
          </div>
        </div>

        <h1 className="mt-6 font-display text-5xl font-normal text-ink-900">
          {caseInfo?.paper_title || '未命名稿件'}
        </h1>

        <div className="mt-4 font-display text-lg italic text-ink-700">
          {caseInfo?.paper_title || ''}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3 text-xs text-ink-700">
          <span>Case: {caseInfo?.case_id || '-'}</span>
          <span className="text-paper-300">·</span>
          <span>
            {data.run?.completed_at
              ? new Date(data.run.completed_at).toLocaleDateString(navigator.languages ?? ['zh-CN'], {
                  year: 'numeric',
                  month: '2-digit',
                  day: '2-digit',
                })
              : '日期待定'}
          </span>
        </div>
      </div>

      {/* GradeStrip */}
      <GradeStrip grade={grade} dimensions={dimensions} />

      {/* GradeNote */}
      {summary && (
        <div className="mt-5 rounded-sm bg-dossier-50 px-5 py-4 text-[13px] leading-[1.7] text-ink-700">
          {summary}
          {!isAuthor && (
            <span className="mt-2 block text-accent-500">
              · 把关者建议：可作为送审参考；建议关注后续修订报告。
            </span>
          )}
        </div>
      )}

      {/* Findings */}
      <div className="mt-16">
        <div className="mb-6 flex items-end justify-between">
          <div>
            <h2 className="font-display text-[28px] font-normal text-ink-900">Findings</h2>
            <div className="mt-1 text-[11px] italic text-ink-500">
              核查发现 · {allFindings.length} 项
            </div>
          </div>
          <button type="button" className="inline-flex items-center gap-1.5 rounded-sm border border-ink-900 px-4 py-2 text-xs text-ink-900 hover:bg-paper-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50" aria-label="下载 PDF 证书">
            <FiDownload size={13} strokeWidth={1.5} aria-hidden="true" /> 下载 PDF 证书
          </button>
        </div>

        {allFindings.length === 0 ? (
          <div className="py-12 text-center text-sm text-ink-500">
            未发现任何问题
          </div>
        ) : (
          allFindings.map((finding) => (
            <FindingCard
              key={finding.finding_id}
              finding={finding}
              role={role}
              onViewDetails={(f) =>
                onNavigate?.('issue', { finding: f.finding_id })
              }
            />
          ))
        )}
      </div>

      {/* Bottom bar */}
      {isAuthor ? (
        <div className="mt-12 flex items-center gap-4 rounded-sm border border-paper-200 bg-dossier-50 px-6 py-5">
          <div className="flex-1">
            <div className="text-[13.5px] font-medium text-ink-900">
              处理问题，重新核查
            </div>
            <div className="mt-1 text-xs text-ink-700">
              修订后系统将出具新版报告，等级可能提升至 A。原版本永久存档可查。
            </div>
          </div>
          <button
            type="button"
            className="rounded-sm border border-ink-900 px-4 py-2 text-xs text-ink-900 hover:bg-paper-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
            onClick={() => onNavigate?.('issue')}
          >
            逐项处理
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-sm bg-ink-900 px-5 py-2 text-xs text-paper-50 hover:bg-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
            onClick={() => onNavigate?.('reverification')}
          >
            <FiRefreshCw size={13} strokeWidth={1.5} aria-hidden="true" /> 完成修改后重核
          </button>
        </div>
      ) : (
        <div className="mt-12 flex items-center gap-4 rounded-sm border border-paper-200 bg-dossier-50 px-6 py-5">
          <FiShield size={18} strokeWidth={1.5} className="text-ink-900" />
          <div className="flex-1">
            <div className="text-[13.5px] font-medium text-ink-900">
              本报告由 Veritas 独立出具，不可篡改
            </div>
            <div className="mt-1 text-xs text-ink-700">
              编号可在 verify.veritas.science 验证。修订生成新版本，旧版本仍可查证。
            </div>
          </div>
          <button
            type="button"
            className="rounded-sm border border-ink-900 px-4 py-2 text-xs text-ink-900 hover:bg-paper-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
            onClick={() => onNavigate?.('verify')}
          >
            查看验证页
          </button>
        </div>
      )}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="mx-auto max-w-[980px] px-14 py-16">
      <div className="py-24 text-center">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-ink-200 border-t-ink-900" />
        <div className="mt-4 text-sm text-ink-500">加载报告…</div>
      </div>
    </div>
  );
}

function ErrorState({ message }) {
  return (
    <div className="mx-auto max-w-[980px] px-14 py-16">
      <div className="py-24 text-center">
        <div className="text-sm text-risk-500">加载失败：{message}</div>
      </div>
    </div>
  );
}

function StatusState({ status, onNavigate }) {
  const label = STATUS_LABELS[status] || status;

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16">
      <div className="py-24 text-center">
        <div className="font-display text-3xl text-ink-900">{label}</div>
        {status === 'running' && (
          <>
            <div className="mt-4 text-sm text-ink-700">
              核查正在进行中，请稍候…
            </div>
            <button
              type="button"
              className="mt-6 rounded-sm border border-ink-900 px-5 py-2 text-xs text-ink-900 hover:bg-paper-100"
              onClick={() => onNavigate?.('progress')}
            >
              查看进度
            </button>
          </>
        )}
        {status === 'failed' && (
          <div className="mt-4 text-sm text-risk-500">
            核查过程中出现错误，请联系支持
          </div>
        )}
        {status === 'unavailable' && (
          <div className="mt-4 text-sm text-ink-500">
            报告尚未生成
          </div>
        )}
      </div>
    </div>
  );
}
