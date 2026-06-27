const TIER_OPTIONS = [
  {
    value: 'full',
    letter: 'A',
    name: '完整复现',
    description: '数据 + 代码 + 环境 + 运行历史',
    maxGrade: 'A',
  },
  {
    value: 'partial',
    letter: 'B',
    name: '部分复现',
    description: '数据 + 代码 + 环境，无运行历史',
    maxGrade: 'B',
  },
  {
    value: 'code_only',
    letter: 'C',
    name: '仅代码',
    description: '代码 + 数据 API（数据私有）',
    maxGrade: 'C',
  },
  {
    value: 'static',
    letter: 'C-',
    name: '静态分析',
    description: '仅论文 + 结果文件',
    maxGrade: 'C-',
  },
];

function ReproducibilityTierPicker({ value, onChange }) {
  return (
    <fieldset className="mt-4" aria-label="可复现性级别选择">
      <legend className="metric-label mb-2 block">可复现性级别</legend>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {TIER_OPTIONS.map((option) => {
          const isSelected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={`relative flex flex-col items-start rounded-2xl border-2 p-4 text-left transition-all ${
                isSelected
                  ? 'border-signal-500 bg-signal-50 shadow-md'
                  : 'border-ink-900/10 bg-white/50 hover:border-ink-900/20 hover:bg-white/70'
              }`}
              aria-pressed={isSelected}
            >
              {isSelected && (
                <span className="absolute right-2 top-2 rounded-full bg-signal-500 px-2 py-0.5 text-xs font-medium text-white">
                  已选
                </span>
              )}
              <div className="mb-2 font-display text-3xl font-bold text-ink-900">
                {option.letter}
              </div>
              <div className="mb-1 font-semibold text-ink-900">{option.name}</div>
              <div className="text-xs text-ink-500">{option.description}</div>
              <div className="mt-2 text-xs font-medium text-signal-600">
                最高评级: {option.maxGrade}
              </div>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default ReproducibilityTierPicker;
