/**
 * ServiceTierPicker — 核查服务套餐选择组件。
 *
 * 三档服务（基础扫描/完整认证/认证+修复），决定核查深度和交付物。
 * 视觉模式：纵向列表行，名称+特征在左，价格在右。
 */

const SERVICE_TIERS = [
  {
    id: 'basic',
    name: '基础扫描',
    price: 0,
    priceLabel: '免费',
    features: '静态检查 · 仅显示问题数量摘要，不含证据与建议',
  },
  {
    id: 'full',
    name: '完整认证',
    price: 680,
    priceLabel: '¥ 680',
    est: '约 2–4 小时',
    recommended: true,
    features: '完整证据链 · 修改建议 · 正式 PDF 证书 · 期刊可在线验证 · 唯一报告编号',
  },
  {
    id: 'full_plus',
    name: '认证 + 修复',
    price: 1280,
    priceLabel: '¥ 1,280',
    est: '承诺 24 小时内',
    features: '完整认证 · 含 5 次重跑额度 · 代码问题自动修复',
  },
];

function ServiceTierPicker({ value = 'full', onChange }) {
  return (
    <fieldset aria-label="核查服务套餐选择">
      <legend className="metric-label mb-2 block">核查服务</legend>
      <p className="mb-5 max-w-2xl text-sm leading-6 text-ink-500">
        不同套餐决定核查深度和交付物。完整认证包含正式证书和在线验证能力。
      </p>
      <div className="flex flex-col">
        {SERVICE_TIERS.map((tier) => {
          const isSelected = value === tier.id;
          return (
            <button
              key={tier.id}
              type="button"
              onClick={() => onChange(tier.id)}
              className={`flex items-center gap-5 border-b border-ink-900/8 py-5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 ${
                isSelected
                  ? 'bg-paper-50'
                  : 'hover:bg-paper-100/40'
              } ${tier.recommended ? '' : ''}`}
              aria-pressed={isSelected}
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-ink-900">{tier.name}</span>
                  {tier.recommended && (
                    <span className="rounded-full bg-signal-500 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                      推荐
                    </span>
                  )}
                  {tier.id === 'full_plus' && (
                    <span className="rounded bg-caution-100 px-1.5 py-0.5 text-[10px] font-semibold text-caution-700">
                      即将推出
                    </span>
                  )}
                </div>
                <div className="mt-1 text-xs leading-5 text-ink-500">
                  {tier.features}
                </div>
              </div>
              <div className="text-right">
                <div className="font-display text-2xl font-semibold text-ink-900">
                  {tier.priceLabel}
                </div>
                {tier.est && (
                  <div className="mt-0.5 font-mono text-[10px] text-ink-500 italic">
                    {tier.est}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default ServiceTierPicker;
