import { useState } from 'react';
import { verifyReport } from '../services/api.js';

/**
 * Public Verification Page — standalone, no sidebar/topbar.
 *
 * Allows external parties (journal editors, etc.) to verify the authenticity
 * of a Veritas certification by report ID.
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
    A: 'bg-green-500',
    B: 'bg-yellow-500',
    C: 'bg-orange-500',
    D: 'bg-red-500',
  };

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            PUBLIC VERIFICATION · 公开验证
          </h1>
          <p className="text-sm text-gray-600">
            verify.veritas.science 查证一份认证的真伪
          </p>
        </div>

        {/* Input Form */}
        <form onSubmit={handleSubmit} className="bg-white shadow-md rounded-lg p-6 mb-8">
          <label htmlFor="reportId" className="block text-sm font-medium text-gray-700 mb-2">
            Report ID / 报告编号
          </label>
          <div className="flex gap-3">
            <input
              id="reportId"
              type="text"
              value={reportId}
              onChange={(e) => setReportId(e.target.value)}
              placeholder="VRT-YYYYMM-XXXXXX"
              className="flex-1 px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              aria-label="Report ID"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !reportId.trim()}
              className="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? '查证中...' : '查证'}
            </button>
          </div>
          <p className="mt-2 text-xs text-gray-500">
            格式：VRT-YYYYMM-XXXXXX（例如：VRT-202606-A3F9B2）
          </p>
        </form>

        {/* Error Message */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6" role="alert">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="bg-white shadow-md rounded-lg p-6" aria-live="polite">
            {result.verified ? (
              <>
                {/* Success Banner */}
                <div className="text-center mb-6">
                  <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-3">
                    <span className="text-3xl">✓</span>
                  </div>
                  <h2 className="text-xl font-semibold text-green-800">
                    报告真实有效
                  </h2>
                </div>

                {/* Paper Info */}
                <div className="border-t border-gray-200 pt-4 mb-4">
                  <h3 className="text-sm font-medium text-gray-500 mb-1">论文标题</h3>
                  <p className="text-base text-gray-900">{result.paper_title || 'N/A'}</p>
                </div>

                {/* Grade Badge */}
                <div className="flex items-center justify-center my-6">
                  <div className={`${gradeColors[result.grade] || 'bg-gray-500'} text-white rounded-full w-24 h-24 flex items-center justify-center text-5xl font-bold shadow-lg`}>
                    {result.grade}
                  </div>
                </div>
                <p className="text-center text-sm text-gray-600 mb-6">
                  {result.grade_label || '评级'}
                </p>

                {/* Dimensions */}
                {result.dimensions && result.dimensions.length > 0 && (
                  <div className="border-t border-gray-200 pt-4 mb-4">
                    <h3 className="text-sm font-medium text-gray-500 mb-3">维度评估</h3>
                    <div className="space-y-2">
                      {result.dimensions.map((dim, idx) => (
                        <div key={idx} className="flex items-start gap-3 text-sm">
                          <span className="font-medium text-gray-700 min-w-[120px]">
                            {dim.label || dim.name}
                          </span>
                          <span className={`flex-1 ${
                            dim.status === 'pass' ? 'text-green-700' :
                            dim.status === 'pass_with_notes' ? 'text-blue-700' :
                            dim.status === 'warning' ? 'text-yellow-700' :
                            dim.status === 'fail' ? 'text-red-700' :
                            'text-gray-700'
                          }`}>
                            {dim.detail}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Metadata */}
                <div className="border-t border-gray-200 pt-4 mt-4">
                  <div className="grid grid-cols-2 gap-4 text-xs text-gray-500">
                    <div>
                      <span className="font-medium">验证时间：</span>
                      {result.created_at ? new Date(result.created_at).toLocaleString('zh-CN') : 'N/A'}
                    </div>
                    <div>
                      <span className="font-medium">协议版本：</span>
                      {result.version || 'N/A'}
                    </div>
                  </div>
                </div>

                {/* Disclaimer */}
                <div className="mt-6 pt-4 border-t border-gray-200">
                  <p className="text-xs text-gray-500 text-center italic">
                    本稿件已通过独立技术核查。这不代替学术评议。
                  </p>
                </div>
              </>
            ) : (
              /* Not Found */
              <div className="text-center py-8">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-3">
                  <span className="text-3xl">✗</span>
                </div>
                <h2 className="text-xl font-semibold text-red-800 mb-2">
                  未找到报告
                </h2>
                <p className="text-sm text-gray-600">
                  报告编号 {result.report_id} 不存在或已失效。
                </p>
                <p className="text-xs text-gray-500 mt-4">
                  请检查报告编号是否正确，或联系认证机构确认。
                </p>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="text-center mt-8 text-xs text-gray-500">
          <p>Veritas 公开验证服务 · 只读模式 · 本报告不可篡改</p>
        </div>
      </div>
    </div>
  );
}
