/**
 * SecurityTierPicker — 数据安全级别选择组件。
 *
 * 三档信任级别（标准/加密/私有），决定模型运行位置、数据加密方式和材料保留时长。
 * 视觉模式：3 列网格卡片，与 ReproducibilityTierPicker 同构。
 */

const SECURITY_TIERS = [
  {
    id: 'standard',
    label: '标准',
    en: 'Standard',
    scenario: '已 preprint · 已投稿',
    features: [
      '云端 API（零数据保留）',
      'TLS 1.3 + AES-256 加密',
      '24 小时内销毁原始材料',
    ],
  },
  {
    id: 'confidential',
    label: '加密',
    en: 'Confidential',
    scenario: '投稿前未公开',
    features: [
      '云端 API + 端到端加密',
      '作者持有解密密钥',
      '平台无法读取明文',
    ],
  },
  {
    id: 'private',
    label: '私有',
    en: 'Private VPC',
    scenario: '高度敏感 · 专利相关',
    features: [
      '本地部署开源大模型',
      '数据完全不出客户网络',
      '需企业版授权',
    ],
  },
];

function SecurityTierPicker({ value = 'confidential', onChange }) {
  return (
    <fieldset aria-label="数据安全级别选择">
      <legend className="metric-label mb-2 block">数据安全级别</legend>
      <p className="mb-5 max-w-2xl text-sm leading-6 text-ink-500">
        不同级别决定模型在哪里运行、数据如何加密、保留多长时间。我们公开能做什么、不能做什么。
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {SECURITY_TIERS.map((tier) => {
          const isSelected = value === tier.id;
          return (
            <button
              key={tier.id}
              type="button"
              onClick={() => onChange(tier.id)}
              className={`relative flex flex-col items-start rounded-2xl border-2 p-5 text-left transition-[border-color,background-color,box-shadow] ${
                isSelected
                  ? 'border-ink-900 bg-paper-50 shadow-md'
                  : 'border-ink-900/10 bg-white/50 hover:border-ink-900/20 hover:bg-white/70'
              }`}
              aria-pressed={isSelected}
            >
              {isSelected && (
                <span className="absolute right-3 top-3 rounded-full bg-ink-900 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-paper-50">
                  当前选择
                </span>
              )}
              {tier.id === 'standard' && !isSelected && (
                <span className="absolute right-3 top-3 rounded bg-signal-100 px-2 py-0.5 text-[10px] font-semibold text-signal-700">
                  当前部署
                </span>
              )}
              <div className="font-display text-2xl font-semibold text-ink-900">
                {tier.label}
              </div>
              <div className="mt-0.5 font-mono text-[11px] text-ink-500 italic">
                {tier.en}
              </div>
              <div className="mt-3 text-xs text-ink-600">{tier.scenario}</div>
              <div className="my-3 h-px w-full bg-ink-900/10" />
              <ul className="space-y-2">
                {tier.features.map((f, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-ink-600">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-900/30" />
                    {f}
                  </li>
                ))}
              </ul>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default SecurityTierPicker;
