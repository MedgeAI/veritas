import { useMemo } from 'react';
import { FiActivity, FiAlertCircle, FiArrowRight, FiCheckCircle, FiFilePlus, FiTrendingUp } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';

function CasesPage({ cases, selectedCaseId, onSelectCase, onNavigate }) {
  // 统计信息
  const stats = useMemo(() => {
    const totalCases = cases.length;
    const totalFindings = cases.reduce((sum, c) => sum + (c.finding_count || 0), 0);
    const criticalCount = cases.reduce((sum, c) => sum + (c.findings_by_severity?.critical || 0), 0);
    const highCount = cases.reduce((sum, c) => sum + (c.findings_by_severity?.high || 0), 0);
    const runningCount = cases.filter((c) => c.latest_run_status === 'running').length;
    const completedCount = cases.filter((c) => c.latest_run_status === 'completed' || c.latest_run_status === 'success').length;
    return { totalCases, totalFindings, criticalCount, highCount, runningCount, completedCount };
  }, [cases]);

  // 最近 5 个 case（按 created_at 排序）
  const recentCases = useMemo(() => {
    return [...cases]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);
  }, [cases]);

  // 高危 case（有 critical 或 high findings）
  const criticalCases = useMemo(() => {
    return cases
      .filter((c) => (c.findings_by_severity?.critical || 0) > 0 || (c.findings_by_severity?.high || 0) > 0)
      .sort((a, b) => {
        const aScore = (a.findings_by_severity?.critical || 0) * 10 + (a.findings_by_severity?.high || 0);
        const bScore = (b.findings_by_severity?.critical || 0) * 10 + (b.findings_by_severity?.high || 0);
        return bScore - aScore;
      })
      .slice(0, 5);
  }, [cases]);

  return (
    <div className="space-y-6">
      {/* 统计卡片 */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-blue-500/10 text-blue-600">
              <FiActivity className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Total Cases</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.totalCases}</p>
            </div>
          </div>
        </div>

        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-purple-500/10 text-purple-600">
              <FiTrendingUp className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Total Findings</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.totalFindings}</p>
              {stats.criticalCount > 0 && (
                <p className="mt-1 text-xs text-red-600">{stats.criticalCount} critical</p>
              )}
            </div>
          </div>
        </div>

        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-green-500/10 text-green-600">
              <FiCheckCircle className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Completed</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.completedCount}</p>
            </div>
          </div>
        </div>

        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-orange-500/10 text-orange-600">
              <FiAlertCircle className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Running</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.runningCount}</p>
            </div>
          </div>
        </div>
      </div>

      {/* 主体内容 */}
      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        {/* 左侧：快速访问 */}
        <div className="space-y-6">
          {/* 最近 Case */}
          <section className="dossier-panel rounded-[2rem] p-5">
            <div className="flex items-center justify-between border-b border-ink-900/10 pb-4">
              <div>
                <h2 className="section-title">Recent Cases</h2>
                <p className="mt-1 text-sm text-ink-500">最近创建的 5 个审查任务</p>
              </div>
              <button type="button" className="btn-primary" onClick={() => onNavigate('newAudit')}>
                <FiFilePlus aria-hidden="true" />
                新建审查
              </button>
            </div>

            {recentCases.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-ink-900/20 bg-white/45 p-8 text-center">
                <p className="font-display text-xl font-semibold">还没有 Case</p>
                <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-500">
                  点击右上角"新建审查"上传论文 PDF 与补充材料。
                </p>
              </div>
            ) : (
              <div className="mt-4 divide-y divide-ink-900/8">
                {recentCases.map((item) => (
                  <button
                    key={item.case_id}
                    type="button"
                    onClick={() => onSelectCase(item.case_id)}
                    className={`flow-list-item group grid w-full gap-4 px-3 py-4 text-left transition md:grid-cols-[minmax(0,1fr)_auto] ${
                      selectedCaseId === item.case_id ? 'bg-signal-100/50' : 'hover:bg-white/45'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-3">
                        <h3 className="min-w-0 break-words font-display text-lg font-semibold text-ink-900">
                          {item.paper_title || item.paper_id || item.case_id}
                        </h3>
                        <StatusPill>{item.latest_run_status || item.status}</StatusPill>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink-500">
                        {item.finding_count > 0 && (
                          <span className="mono-chip">{item.finding_count} findings</span>
                        )}
                        <span className="mono-chip">{new Date(item.created_at).toLocaleDateString('zh-CN')}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm font-semibold text-signal-700">
                      进入
                      <FiArrowRight className="transition group-hover:translate-x-1" aria-hidden="true" />
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          {/* 高危 Case */}
          {criticalCases.length > 0 && (
            <section className="dossier-panel rounded-[2rem] p-5">
              <div className="border-b border-ink-900/10 pb-4">
                <h2 className="section-title">High Priority</h2>
                <p className="mt-1 text-sm text-ink-500">有 critical 或 high 级别 findings 的 case</p>
              </div>

              <div className="mt-4 divide-y divide-ink-900/8">
                {criticalCases.map((item) => {
                  const critical = item.findings_by_severity?.critical || 0;
                  const high = item.findings_by_severity?.high || 0;
                  return (
                    <button
                      key={item.case_id}
                      type="button"
                      onClick={() => onSelectCase(item.case_id)}
                      className={`flow-list-item group grid w-full gap-4 px-3 py-4 text-left transition md:grid-cols-[minmax(0,1fr)_auto] ${
                        selectedCaseId === item.case_id ? 'bg-signal-100/50' : 'hover:bg-white/45'
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-3">
                          <h3 className="min-w-0 break-words font-display text-lg font-semibold text-ink-900">
                            {item.paper_title || item.paper_id || item.case_id}
                          </h3>
                          {critical > 0 && (
                            <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-700">
                              {critical} critical
                            </span>
                          )}
                          {high > 0 && (
                            <span className="rounded-full bg-orange-500/10 px-2 py-0.5 text-xs font-medium text-orange-700">
                              {high} high
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 text-sm font-semibold text-signal-700">
                        进入
                        <FiArrowRight className="transition group-hover:translate-x-1" aria-hidden="true" />
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          )}
        </div>

        {/* 右侧：说明面板 */}
        <aside className="dossier-panel rounded-[2rem] p-6">
          <p className="metric-label">Operating Contract</p>
          <h3 className="mt-3 font-display text-2xl font-semibold">Web 只封装流程，不降低审查真实性</h3>
          <div className="mt-5 space-y-4 text-sm leading-6 text-ink-500">
            <p>启动运行后，backend 会直接调用 `run_static_audit()`，默认使用真实 MinerU、opencode 和百炼 Qwen 配置。</p>
            <p>最终报告仍来自 `outputs/&lt;case_id&gt;/research-integrity-audit/final_audit_report.html`。</p>
            <p>当前页面不做最终诚信判定，只把证据、异常和人工复核入口组织起来。</p>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default CasesPage;
