import { useState } from 'react';
import { verifyReport } from '../services/api.js';

/**
 * Public Verification Page — standalone, no sidebar/topbar.
 *
 * Allows external parties (journal editors, etc.) to verify the authenticity
 * of a Veritas certification by report ID.
 *
 * Uses Veritas brand palette: paper/ink/signal/risk (not Tailwind defaults).
 */
export default function VerifyPage() {
  const [reportId, setReportId] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!reportId.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await verifyReport(reportId.trim());
      setResult(data);
    } catch (err) {
      setError(err.message || 'Verification failed');
    } finally {
      setLoading(false);
    }
  }

  const gradeColors = {
    A: 'bg-signal-500',
    B: 'bg-accent-500',
    C: 'bg-caution-500',
    D: 'bg-risk-500',
  };

  return (
    <div className="min-h-screen bg-paper-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="font-display text-3xl font-bold text-ink-900 mb-2">
            PUBLIC VERIFICATION · 公开验证
          </h1>
          <p className="font-mono text-xs text-ink-500">
            verify.veritas.science 查证一份认证的真伪
          </p>
        </div>

        {/* Input Form */}
        <form onSubmit={handleSubmit} className="dossier-panel rounded-2xl p-6 mb-8">
          <label htmlFor="reportId" className="block text-sm font-medium text-ink-700 mb-2">
            Report ID / 报告编号
          </label>
          <div className="flex gap-3">
            <input
              id="reportId"
              type="text"
              value={reportId}
              onChange={(e) => setReportId(e.target.value)}
              placeholder="VRT-YYYYMM-XXXXXX"
              spellCheck={false}
              autoComplete="off"
              className="flex-1 input-field font-mono text-sm tracking-wide"
              aria-label="Report ID"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !reportId.trim()}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? '查证中…' : '查证'}
            </button>
          </div>
          <p className="mt-2 font-mono text-[11px] text-ink-500">
            格式：VRT-YYYYMM-XXXXXX（例如：VRT-202606-A3F9B2）
          </p>
        </form>

        {/* Error Message */}
        {error && (
          <div className="rounded-2xl border border-risk-300/45 bg-risk-100/70 px-4 py-3 mb-6 text-sm text-risk-700" role="alert">
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="dossier-panel rounded-2xl p-6" aria-live="polite">
            {result.verified ? (
              <>
                {/* Success Banner */}
                <div className="text-center mb-6">
                  <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-signal-100 mb-3">
                    <span className="text-3xl text-signal-700">✓</span>
                  </div>
                  <h2 className="font-display text-xl font-semibold text-signal-700">
                    报告真实有效
                  </h2>
                </div>

                {/* Paper Info */}
                <div className="border-t border-ink-900/10 pt-4 mb-4">
                  <h3 className="font-mono text-[11px] uppercase tracking-wide text-ink-500 mb-1">论文标题</h3>
                  <p className="font-display text-base text-ink-900">{result.paper_title || 'N/A'}</p>
                </div>

                {/* Grade Badge */}
                <div className="flex items-center justify-center my-6">
                  <div className={`${gradeColors[result.grade] || 'bg-ink-300'} text-white rounded-2xl w-24 h-24 flex flex-col items-center justify-center shadow-dossier`}>
                    <span className="font-display text-5xl font-bold leading-none">{result.grade}</span>
                  </div>
                </div>
                <p className="text-center text-sm text-ink-500 mb-6">
                  {result.grade_label || '评级'}
                </p>

                {/* Dimensions */}
                {result.dimensions && result.dimensions.length > 0 && (
                  <div className="border-t border-ink-900/10 pt-4 mb-4">
                    <h3 className="font-mono text-[11px] uppercase tracking-wide text-ink-500 mb-3">维度评估</h3>
                    <div className="space-y-2">
                      {result.dimensions.map((dim, idx) => (
                        <div key={idx} className="flex items-start gap-3 text-sm">
                          <span className="font-medium text-ink-700 min-w-[120px]">
                            {dim.label || dim.name}
                          </span>
                          <span className={`flex-1 text-sm ${
                            dim.status === 'pass' ? 'text-signal-700' :
                            dim.status === 'pass_with_notes' ? 'text-accent-700' :
                            dim.status === 'warning' ? 'text-caution-700' :
                            dim.status === 'fail' ? 'text-risk-700' :
                            'text-ink-500'
                          }`}>
                            {dim.detail}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Metadata */}
                <div className="border-t border-ink-900/10 pt-4 mt-4">
                  <div className="grid grid-cols-2 gap-4 font-mono text-[11px] text-ink-500">
                    <div>
                      <span className="font-semibold text-ink-700">验证时间：</span>
                      {result.created_at ? new Date(result.created_at).toLocaleString(navigator.languages ?? ['zh-CN']) : 'N/A'}
                    </div>
                    <div>
                      <span className="font-semibold text-ink-700">协议版本：</span>
                      {result.version || 'N/A'}
                    </div>
                  </div>
                </div>

                {/* Disclaimer */}
                <div className="mt-6 pt-4 border-t border-ink-900/10">
                  <p className="text-xs text-ink-500 text-center italic">
                    本稿件已通过独立技术核查。这不代替学术评议。
                  </p>
                </div>
              </>
            ) : (
              /* Not Found */
              <div className="text-center py-8">
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-risk-100 mb-3">
                  <span className="text-3xl text-risk-700">✗</span>
                </div>
                <h2 className="font-display text-xl font-semibold text-risk-700 mb-2">
                  未找到报告
                </h2>
                <p className="text-sm text-ink-500">
                  报告编号 <span className="font-mono">{result.report_id}</span> 不存在或已失效。
                </p>
                <p className="font-mono text-[11px] text-ink-500 mt-4">
                  请检查报告编号是否正确，或联系认证机构确认。
                </p>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="text-center mt-8 font-mono text-[11px] text-ink-500">
          <p>Veritas 公开验证服务 · 只读模式 · 本报告不可篡改</p>
        </div>
      </div>
    </div>
  );
}
