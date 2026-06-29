/**
 * VerifyPage.jsx — Client-embedded verification page (PRD Phase 5).
 *
 * Uses ClientLayout design language. Renders:
 *   - Hero: "verify.veritas.science 查证一份认证的真伪"
 *   - Input form: report_id text input + 查证 button
 *   - Result card: grade badge, dimensions, paper title, metadata
 * Supports URL query param: ?report_id=XXX auto-fill and query.
 */

import { useState, useEffect } from 'react';
import { FiSearch, FiShield } from 'react-icons/fi';
import { verifyReport } from '../../services/api';
import GradeBadge from '../../components/GradeBadge';

const GRADE_LABELS = {
  A: '完全通过',
  B: '有条件通过',
  C: '待修订',
  D: '未通过',
};

export default function VerifyPage({ onNavigate }) {
  const [reportId, setReportId] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [verified, setVerified] = useState(false);

  // Auto-fill from URL query param
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const rid = params.get('report_id');
    if (rid) {
      setReportId(rid);
      // Auto-submit
      handleVerify(rid);
    }
  }, []);

  const handleVerify = async (id) => {
    const targetId = id || reportId;
    if (!targetId.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setVerified(false);

    try {
      const data = await verifyReport(targetId.trim());
      setResult(data);
      setVerified(true);
    } catch (e) {
      setError(e.message || '查证失败');
      setVerified(false);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    handleVerify();
  };

  const dimensions = result?.dimensions || [];

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* Hero */}
      <div className="mb-16">
        <div className="mb-5.5 text-[10px] font-medium uppercase tracking-[0.25em] text-ink-500">
          Public verification · 公开验证
        </div>
        <h1 className="font-display text-[56px] font-normal leading-[1.15] text-ink-900">
          verify.veritas.science
          <br />
          <em className="font-normal italic text-accent-500">查证一份认证的真伪</em>
        </h1>
        <p className="mt-6 max-w-[540px] font-display text-base italic leading-[1.7] text-ink-700">
          期刊编辑、审稿人或任何把关者可在此输入报告编号，查证认证真实性。
          <br />
          无需注册，所有信息只读。
        </p>
      </div>

      <div className="h-px bg-paper-200" />

      {/* Input form */}
      <form
        onSubmit={handleSubmit}
        className="mt-10 flex items-center gap-3 rounded-sm border border-ink-900 bg-white px-5 py-3.5"
      >
        <FiSearch size={16} strokeWidth={1.5} className="text-ink-500" />
        <input
          type="text"
          value={reportId}
          onChange={(e) => setReportId(e.target.value)}
          placeholder="输入报告编号，如 VRT-2026-05-A8F92C"
          className="flex-1 border-none bg-transparent font-mono text-sm tracking-wider text-ink-900 outline-none placeholder:text-ink-300"
        />
        <button
          type="submit"
          disabled={loading || !reportId.trim()}
          className="rounded-sm bg-ink-900 px-5 py-2 text-xs text-paper-50 hover:bg-ink-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
        >
          {loading ? '查证中...' : '查证'}
        </button>
      </form>

      {/* Error state */}
      {error && (
        <div className="mt-6 rounded-sm border border-risk-500 bg-red-50 px-5 py-4 text-sm text-risk-500" role="alert" aria-live="polite">
          {error}
        </div>
      )}

      {/* Result card */}
      {verified && result && (
        <div className="mt-8 rounded-sm border border-paper-200 bg-white p-8">
          {/* Result header */}
          <div className="flex items-start justify-between">
            <div>
              <div className="text-[10px] font-medium uppercase tracking-[0.2em] text-[#5a6b46]">
                &#10003; 报告真实有效
              </div>
              <h3 className="mt-2.5 font-display text-[32px] font-normal text-ink-900">
                {result.paper_title || '未命名稿件'}
              </h3>
              {result.grade_label && (
                <div className="mt-1 font-display text-[15px] italic text-ink-700">
                  {result.grade_label}
                </div>
              )}
            </div>

            {/* Grade badge */}
            <div className="text-center">
              <div className="flex h-[70px] w-[70px] items-center justify-center rounded-full border-2 border-[#5a6b46] bg-paper-50 font-display text-[38px] font-normal text-ink-900">
                {result.grade || '?'}
              </div>
              <div className="mt-2 text-[10px] tracking-[0.15em] text-[#5a6b46]">
                {GRADE_LABELS[result.grade] || '待评级'}
              </div>
            </div>
          </div>

          {/* Metadata grid */}
          <div className="mt-6 grid grid-cols-2 gap-2.5 text-xs text-ink-700">
            {result.report_id && (
              <div>
                <span className="mr-2 text-[10px] uppercase tracking-wider text-ink-500">
                  报告编号
                </span>
                <span className="font-mono">{result.report_id}</span>
              </div>
            )}
            {result.version && (
              <div>
                <span className="mr-2 text-[10px] uppercase tracking-wider text-ink-500">
                  当前版本
                </span>
                v{result.version}
              </div>
            )}
            {result.completed_at && (
              <div>
                <span className="mr-2 text-[10px] uppercase tracking-wider text-ink-500">
                  核查时间
                </span>
                {new Date(result.completed_at).toLocaleDateString(navigator.languages ?? ['zh-CN'])}
              </div>
            )}
          </div>

          <div className="my-6 h-px bg-paper-200" />

          {/* Summary / conclusion */}
          {result.summary && (
            <div className="text-[13.5px] leading-[1.75] text-ink-900">
              {result.summary}
            </div>
          )}

          {/* Dimension mini stats */}
          {dimensions.length > 0 && (
            <div className="mt-5 grid grid-cols-4 gap-2">
              {dimensions.map((d) => (
                <div
                  key={d.name}
                  className="rounded-sm border border-paper-200 bg-paper-50 px-3.5 py-2.5"
                >
                  <div className="text-[10px] uppercase tracking-wider text-ink-500">
                    {d.label}
                  </div>
                  <div className="mt-1 text-sm font-medium text-[#5a6b46]">
                    {d.status === 'pass'
                      ? '通过'
                      : d.status === 'pass_with_notes'
                        ? '基本通过'
                        : d.status === 'warning'
                          ? '有备注'
                          : '未通过'}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Note for gatekeepers */}
          <div className="mt-6 rounded-sm bg-dossier-50 px-4.5 py-3.5 text-[12.5px] leading-[1.65] text-ink-700">
            <b>给把关者的建议：</b>
            本稿件已通过独立技术核查。这不代替学术评议——新颖性、影响力、领域贡献仍需期刊审稿人判断。
          </div>
        </div>
      )}

      {/* Empty state when no result yet */}
      {!verified && !error && !loading && (
        <div className="mt-12 text-center text-sm text-ink-500">
          输入报告编号后点击"查证"按钮
        </div>
      )}
    </div>
  );
}
