import { useEffect, useState } from 'react';
import { FiChevronLeft, FiShield } from 'react-icons/fi';
import { getReverificationCost, getVersionHistory, submitReverification } from '../../services/api.js';
import { IncludedLineItem, OptionalLineItem, PrimaryLineItem } from '../../components/client/LineItem.jsx';
import ClientEmptyState from '../../components/client/ClientEmptyState.jsx';

const italicStyle = { fontStyle: 'italic' };
const subtitleStyle = { fontFamily: '"Cormorant Garamond", serif', fontStyle: 'italic' };

/**
 * ReverificationPage — client-facing reverification/payment page.
 *
 * Uses getReverificationCost for dynamic pricing,
 * getVersionHistory for version chain,
 * submitReverification for submission.
 * Visual layout matches prototype RepayPage.
 */
export default function ReverificationPage({ caseId, onNavigate }) {
  const [costData, setCostData] = useState(null);
  const [_versionHistory, setVersionHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [newVersionInfo, setNewVersionInfo] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!caseId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getReverificationCost(caseId).catch(() => null),
      getVersionHistory(caseId).catch(() => null),
    ]).then(([cost, hist]) => {
      if (cancelled) return;
      if (cost) setCostData(cost);
      if (hist) setVersionHistory(hist.versions || []);
      setLoading(false);
    }).catch(() => {
      if (!cancelled) {
        setError('加载失败，请稍后重试');
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [caseId]);

  async function handleConfirm() {
    setSubmitting(true);
    setError('');
    try {
      const result = await submitReverification(caseId);
      setNewVersionInfo(result);
      setConfirmed(true);
    } catch (err) {
      setError(err.message || '提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  function handleLater() {
    onNavigate?.('report');
  }

  if (!caseId) {
    return <ClientEmptyState type="reverification" onNavigate={onNavigate} />;
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <div className="font-display text-2xl text-ink-500">加载中…</div>
      </div>
    );
  }

  if (error && !costData) {
    return (
      <div className="mx-auto max-w-[980px] px-14 py-16 pb-24 text-center">
        <div className="font-display text-xl text-risk-500">{error}</div>
      </div>
    );
  }

  const currency = costData?.currency || '¥';
  const total = costData?.total || 0;

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* Back link */}
      <button
        type="button"
        onClick={() => onNavigate?.('report')}
        className="mb-8 inline-flex items-center gap-1 text-sm text-ink-500 transition hover:text-ink-900"
      >
        <FiChevronLeft size={14} strokeWidth={1.5} aria-hidden="true" />
        返回报告
      </button>

      {/* Hero block */}
      <div className="mb-16">
        <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-ink-500">
          Re-verification · 修订重核
        </div>
        <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
          修订完成后的<br />
          <em className="font-normal text-accent-500" style={italicStyle}>重新核查</em>
        </h1>
        <p className="mt-6 max-w-[540px] font-display text-[16px] leading-[1.7] text-ink-700" style={subtitleStyle}>
          上传修订后的稿件与代码，系统将对修改部分增量复核，并出具新版报告。<br />
          新版本保留原编号链路，标注为 v{costData?.next_version || '?' }。旧版本仍可查证。
        </p>
      </div>

      <div className="my-16 h-px bg-ink-100" />

      {/* Line items */}
      <section className="mb-16">
        <SectionLabel num="—" title="核查清单" sub="Items" />
        <div className="border-t border-ink-100">
          <PrimaryLineItem
            label="修订内容增量复核"
            detail={`仅核对修改部分，约 ${costData?.finding_count || 0} 处变更`}
            price={`${currency} ${costData?.base_fee || 0}`}
          />
          <IncludedLineItem
            label="逐项验证修复"
            detail="确认每项已正确解决"
            price="已含"
          />
          <IncludedLineItem
            label="重新评定等级"
            detail="基于修复结果重新计算认证等级"
            price="已含"
          />
          <IncludedLineItem
            label="新版 PDF 证书"
            detail={`保留原编号链路，标注 v${costData?.next_version || '?'}`}
            price="已含"
          />
          {costData?.optional_addon_label && (
            <OptionalLineItem
              label={costData.optional_addon_label}
              detail="自动修复代码层面的问题（可选）"
              price={`+ ${currency} ${costData.optional_addon_price}`}
            />
          )}
        </div>

        {/* Total bar */}
        <div className="mt-6 flex items-baseline justify-between border-t border-ink-900 pt-6">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-ink-500">合计</div>
            <div className="mt-1 text-xs text-ink-500 italic">
              已开通完整认证，本次为追加重核服务
            </div>
          </div>
          <div className="font-display text-[40px] font-normal text-ink-900">
            {currency} {total}
          </div>
        </div>
      </section>

      {/* Pay actions */}
      {confirmed ? (
        <div className="rounded-sm border border-accent-200 bg-accent-50 p-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-100">
            <FiShield size={20} className="text-accent-700" aria-hidden="true" />
          </div>
          <p className="font-display text-xl font-semibold text-accent-700">
            已确认，开始重新核查
          </p>
          <p className="mt-2 text-sm text-ink-500">
            {newVersionInfo
              ? `v${newVersionInfo.new_version} (${newVersionInfo.new_report_id}) 正在生成中`
              : `v${costData?.next_version || '?'} 正在生成中`}
            ，请稍后查看结果
          </p>
          <button
            type="button"
            className="mt-6 inline-flex items-center gap-2 rounded-full bg-ink-900 px-6 py-3 text-sm font-semibold text-paper-50 transition hover:-translate-y-0.5 hover:shadow-lg"
            onClick={() => onNavigate?.('report')}
          >
            查看报告
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <button
            type="button"
            className="flex-1 rounded-sm border border-ink-900/20 px-6 py-3.5 text-sm font-medium text-ink-700 transition hover:bg-paper-100"
            onClick={handleLater}
            disabled={submitting}
          >
            稍后处理
          </button>
          <button
            type="button"
            className="flex-[2] inline-flex items-center justify-center gap-2 rounded-sm bg-ink-900 px-6 py-3.5 text-sm font-semibold text-paper-50 transition hover:-translate-y-0.5 hover:shadow-lg disabled:cursor-not-allowed disabled:opacity-50"
            onClick={handleConfirm}
            disabled={submitting}
          >
            <FiShield size={14} strokeWidth={1.5} aria-hidden="true" />
            {submitting ? '处理中…' : `确认支付 · 开始重新核查`}
          </button>
        </div>
      )}

      {error && confirmed === false && (
        <div className="mt-5 rounded-sm border border-risk-300/45 bg-risk-50/70 p-4 text-sm text-risk-700">
          {error}
        </div>
      )}

      {/* Team subscription hint */}
      <div className="mt-12 rounded-sm border border-ink-100 bg-paper-100/40 px-6 py-5">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-ink-500">团队订阅</div>
        <p className="text-[13px] leading-relaxed text-ink-700">
          课题组开通团队订阅可享 60% 折扣，¥ 1,980 / 月，含 8 份完整认证 + 不限次数重核。
          <a href="#" className="ml-1 text-accent-500 hover:underline">了解详情 →</a>
        </p>
      </div>
    </div>
  );
}

function SectionLabel({ num, title, sub }) {
  return (
    <div className="mb-5 flex items-baseline gap-4 border-b border-ink-100 pb-3">
      <span className="font-mono text-[11px] tracking-[2px] text-ink-300">{num}</span>
      <span className="font-display text-[22px] font-normal text-ink-900">{title}</span>
      <span className="ml-auto text-[11px] text-ink-500 italic">{sub}</span>
    </div>
  );
}
