import { FiArrowRight, FiFilePlus } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';

function CasesPage({ cases, selectedCaseId, onSelectCase, onNavigate }) {
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <section className="dossier-panel rounded-[2rem] p-5">
        <div className="flex flex-col gap-3 border-b border-ink-900/10 pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="section-title">审查档案</h2>
            <p className="mt-2 text-sm text-ink-500">每个 case 对应一次投稿前技术复核输入与运行历史。</p>
          </div>
          <button type="button" className="btn-primary" onClick={() => onNavigate('newAudit')}>
            <FiFilePlus aria-hidden="true" />
            新建审查
          </button>
        </div>

        <div className="mt-4 divide-y divide-ink-900/8">
          {cases.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-ink-900/20 bg-white/45 p-8 text-center">
              <p className="font-display text-2xl font-semibold">还没有 Case</p>
              <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-500">
                从 New Audit 上传论文 PDF 与补充材料，前端会启动与 CLI 等价的真实静态审查链路。
              </p>
            </div>
          ) : null}

          {cases.map((item) => (
            <button
              key={item.case_id}
              type="button"
              onClick={() => onSelectCase(item.case_id)}
              className={`flow-list-item group grid w-full gap-4 px-3 py-5 text-left transition md:grid-cols-[minmax(0,1fr)_auto] ${
                selectedCaseId === item.case_id ? 'bg-signal-100/50' : 'hover:bg-white/45'
              }`}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="min-w-0 break-words font-display text-xl font-semibold text-ink-900">{item.paper_title}</h3>
                  <StatusPill>{item.status}</StatusPill>
                </div>
                <p className="mt-2 font-mono text-xs text-ink-300">{item.case_id}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="mono-chip">inputs: {item.input_count}</span>
                  <span className="mono-chip">owner: {item.owner}</span>
                  <span className="mono-chip">updated: {item.updated_at}</span>
                </div>
              </div>
              <div className="flex items-center gap-2 text-sm font-semibold text-signal-700">
                进入
                <FiArrowRight className="transition group-hover:translate-x-1" aria-hidden="true" />
              </div>
            </button>
          ))}
        </div>
      </section>

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
  );
}

export default CasesPage;
