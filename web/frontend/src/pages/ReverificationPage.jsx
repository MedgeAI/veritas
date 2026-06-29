import { useEffect, useState } from 'react';
import { FiArrowRight, FiCheck, FiClock } from 'react-icons/fi';
import { getReverificationCost, getVersionHistory, submitReverification } from '../services/api.js';

/**
 * ReverificationPage — shows what will be re-verified, version chain,
 * cost breakdown, and lets the user confirm payment (mocked).
 */
export default function ReverificationPage({ selectedCase, onNavigate }) {
  const [versionHistory, setVersionHistory] = useState([]);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [newVersionInfo, setNewVersionInfo] = useState(null);
  const [costData, setCostData] = useState(null);

  useEffect(() => {
    if (!selectedCase?.case_id) return;
    let cancelled = false;

    async function load() {
      try {
        const [histData, cost] = await Promise.all([
          getVersionHistory(selectedCase.case_id).catch(() => null),
          getReverificationCost(selectedCase.case_id).catch(() => null),
        ]);
        if (cancelled) return;
        if (histData) setVersionHistory(histData.versions || []);
        if (cost) setCostData(cost);
      } catch {
        // ignore — cost and version history are supplementary
      }
    }

    load();
    return () => { cancelled = true; };
  }, [selectedCase]);

  if (!selectedCase) {
    return (
      <section className="dossier-panel rounded-2xl p-8 text-center">
        <p className="font-display text-2xl font-semibold">请先选择审查项目</p>
      </section>
    );
  }

  const currentVersion = selectedCase.report_version || 1;
  const nextVersion = currentVersion + 1;

  async function handleConfirm() {
    setLoading(true);
    try {
      const result = await submitReverification(selectedCase.case_id);
      setNewVersionInfo(result);
      setConfirmed(true);
    } catch (err) {
      console.error('[Reverification] Failed:', err);
    } finally {
      setLoading(false);
    }
  }

  function handleLater() {
    onNavigate?.('mission');
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <section className="dossier-panel rounded-2xl p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-100 text-accent-700">
            <FiArrowRight className="h-6 w-6" aria-hidden="true" />
          </div>
          <div className="flex-1">
            <h2 className="section-title">修订版重新核查</h2>
            <p className="mt-2 text-sm text-ink-500">
              作者已修改论文并重新提交，系统将对修订内容进行增量复核
            </p>
          </div>
        </div>
      </section>

      {/* Version Chain */}
      <section className="dossier-panel rounded-2xl p-6">
        <h3 className="font-display text-lg font-semibold mb-4">版本链路</h3>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Previous versions */}
          {versionHistory.map((v) => (
            <div key={v.report_id || v.version} className="flex items-center gap-3">
              <div className="flex flex-col items-center rounded-xl border border-ink-200 bg-ink-50 px-4 py-3">
                <span className="text-sm font-semibold text-ink-700">v{v.version}</span>
                <span className="text-xs text-ink-500">
                  {v.date ? new Date(v.date).toLocaleDateString(navigator.languages ?? ['zh-CN']) : '-'}
                </span>
                <span className="mt-1 inline-flex items-center rounded-full bg-ink-200 px-2 py-0.5 text-xs font-medium text-ink-700">
                  {v.grade || '?'}
                </span>
              </div>
              <FiArrowRight className="h-4 w-4 text-ink-400" aria-hidden="true" />
            </div>
          ))}

          {/* Current version */}
          <div className="flex flex-col items-center rounded-xl border-2 border-accent-400 bg-accent-50 px-4 py-3">
            <span className="text-sm font-semibold text-accent-700">v{currentVersion} (当前)</span>
            <span className="text-xs text-accent-600">
              {selectedCase.updated_at ? new Date(selectedCase.updated_at).toLocaleDateString(navigator.languages ?? ['zh-CN']) : '-'}
            </span>
          </div>

          <FiArrowRight className="h-4 w-4 text-ink-400" aria-hidden="true" />

          {/* Next version (pending) */}
          <div className="flex flex-col items-center rounded-xl border-2 border-dashed border-accent-300 bg-white px-4 py-3 opacity-70">
            <span className="text-sm font-semibold text-ink-500">v{nextVersion}</span>
            <span className="text-xs text-ink-400">待生成</span>
          </div>
        </div>
      </section>

      {/* Scope */}
      <section className="dossier-panel rounded-2xl p-6">
        <h3 className="font-display text-lg font-semibold mb-4">复核范围</h3>
        <ul className="space-y-3 text-sm">
          <li className="flex items-start gap-3">
            <FiCheck className="mt-0.5 h-4 w-4 text-green-600 shrink-0" aria-hidden="true" />
            <div>
              <span className="font-medium text-ink-800">修订内容增量复核</span>
              <p className="text-xs text-ink-500 mt-0.5">仅检查作者修改的部分，不重复审查未变更内容</p>
            </div>
          </li>
          <li className="flex items-start gap-3">
            <FiCheck className="mt-0.5 h-4 w-4 text-green-600 shrink-0" aria-hidden="true" />
            <div>
              <span className="font-medium text-ink-800">逐项验证修复</span>
              <p className="text-xs text-ink-500 mt-0.5">确认每个 finding 的修复是否有效</p>
            </div>
          </li>
          <li className="flex items-start gap-3">
            <FiCheck className="mt-0.5 h-4 w-4 text-green-600 shrink-0" aria-hidden="true" />
            <div>
              <span className="font-medium text-ink-800">重新评定等级</span>
              <p className="text-xs text-ink-500 mt-0.5">基于修复结果重新计算认证等级</p>
            </div>
          </li>
        </ul>
      </section>

      {/* Cost Breakdown — LineItem pattern from prototype */}
      <section className="dossier-panel rounded-2xl p-6">
        <h3 className="font-display text-lg font-semibold mb-4">核查清单</h3>
        {costData ? (
          <div>
            {/* Included items */}
            <div className="border-b border-ink-900/8 py-4 flex items-start gap-3">
              <FiCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-900" aria-hidden="true" />
              <div className="flex-1">
                <div className="text-sm font-medium text-ink-900">修订内容增量复核</div>
                <div className="text-xs text-ink-500 mt-0.5">仅核对修改部分，不重复审查未变更内容</div>
              </div>
              <div className="font-mono text-sm text-ink-900 whitespace-nowrap">
                {costData.currency}{costData.base_fee}
              </div>
            </div>

            <div className="border-b border-ink-900/8 py-4 flex items-start gap-3">
              <FiCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-900" aria-hidden="true" />
              <div className="flex-1">
                <div className="text-sm font-medium text-ink-900">逐项验证修复</div>
                <div className="text-xs text-ink-500 mt-0.5">确认每个 finding 的修复是否有效</div>
              </div>
              <div className="font-mono text-sm text-ink-500 whitespace-nowrap">已含</div>
            </div>

            <div className="border-b border-ink-900/8 py-4 flex items-start gap-3">
              <FiCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-900" aria-hidden="true" />
              <div className="flex-1">
                <div className="text-sm font-medium text-ink-900">重新评定等级</div>
                <div className="text-xs text-ink-500 mt-0.5">基于修复结果重新计算认证等级</div>
              </div>
              <div className="font-mono text-sm text-ink-500 whitespace-nowrap">已含</div>
            </div>

            <div className="border-b border-ink-900/8 py-4 flex items-start gap-3">
              <FiCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-900" aria-hidden="true" />
              <div className="flex-1">
                <div className="text-sm font-medium text-ink-900">新版报告</div>
                <div className="text-xs text-ink-500 mt-0.5">保留原编号链路，标注 v{costData.next_version}</div>
              </div>
              <div className="font-mono text-sm text-ink-500 whitespace-nowrap">已含</div>
            </div>

            {/* Optional add-on (reserved) */}
            {costData.finding_count > 0 && (
              <div className="border-b border-ink-900/8 py-4 flex items-start gap-3 opacity-60">
                <div className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full border border-ink-900/20" />
                <div className="flex-1">
                  <div className="text-sm text-ink-700">{costData.optional_addon_label}</div>
                  <div className="text-xs text-ink-500 mt-0.5">自动修复代码层面的问题</div>
                </div>
                <div className="font-mono text-sm text-ink-500 whitespace-nowrap">+ {costData.currency} {costData.optional_addon_price}</div>
              </div>
            )}

            {costData.total >= costData.max_fee && (
              <div className="mt-2 text-xs text-ink-500 italic">
                已应用费用上限 ({costData.currency}{costData.max_fee})
              </div>
            )}

            {/* Total bar */}
            <div className="mt-4 flex items-baseline justify-between border-t border-ink-900 pt-5">
              <div>
                <div className="font-mono text-[10px] uppercase tracking-widest text-ink-500">合计</div>
                <div className="text-xs text-ink-500 mt-1 italic">
                  已开通完整认证，本次为追加重核服务
                </div>
              </div>
              <div className="font-display text-4xl font-semibold text-ink-900">
                {costData.currency}{costData.total}
              </div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-ink-500">加载费用信息中…</div>
        )}
      </section>

      {/* Actions */}
      <section className="dossier-panel rounded-2xl p-6">
        {confirmed ? (
          <div className="text-center py-4">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-signal-100 mb-3">
              <FiCheck className="h-6 w-6 text-signal-700" aria-hidden="true" />
            </div>
            <p className="font-display text-lg font-semibold text-signal-700">
              已确认，开始重新核查
            </p>
            <p className="text-sm text-ink-500 mt-2">
              {newVersionInfo
                ? `v${newVersionInfo.new_version} (${newVersionInfo.new_report_id}) 正在生成中`
                : `v${nextVersion} 正在生成中`}
              ，请稍后查看结果
            </p>
            <button
              type="button"
              className="btn-primary mt-4"
              onClick={() => onNavigate?.('mission')}
            >
              查看进度
            </button>
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row items-center gap-4">
            <button
              type="button"
              className="btn-secondary w-full sm:w-auto"
              onClick={handleLater}
            >
              <FiClock className="h-4 w-4" aria-hidden="true" />
              稍后处理
            </button>
            <button
              type="button"
              className="btn-primary w-full sm:w-auto"
              onClick={handleConfirm}
              disabled={loading}
            >
              {loading ? '处理中…' : `确认支付 · 开始重新核查${costData ? ` · ${costData.currency}${costData.total}` : ''}`}
            </button>
          </div>
        )}
      </section>

      {/* Team subscription hint */}
      <section className="rounded-2xl border border-ink-200/60 bg-ink-50/50 p-4 text-center text-xs text-ink-500">
        <p>
          团队订阅用户享有无限次修订复核。
          <a href="#" className="text-accent-600 hover:underline ml-1">
            了解详情 →
          </a>
        </p>
      </section>
    </div>
  );
}
