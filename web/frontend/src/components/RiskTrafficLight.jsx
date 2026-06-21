import { FiAlertCircle, FiCheckCircle, FiHelpCircle, FiInfo } from 'react-icons/fi';
import { translateRiskLevel } from '../utils/piLabels.js';

const LEVEL_CONFIG = {
  low: {
    icon: FiCheckCircle,
    label: '低风险',
    color: 'text-signal-700 bg-signal-100/60 border-signal-500/25',
  },
  medium: {
    icon: FiAlertCircle,
    label: '中风险',
    color: 'text-caution-700 bg-caution-100/60 border-caution-500/25',
  },
  high: {
    icon: FiAlertCircle,
    label: '高风险',
    color: 'text-risk-700 bg-risk-100/60 border-risk-500/25',
  },
  critical: {
    icon: FiAlertCircle,
    label: '极高风险',
    color: 'text-risk-700 bg-risk-100/70 border-risk-500/40',
  },
  info: {
    icon: FiInfo,
    label: '未发现中高风险',
    color: 'text-ink-500 bg-white/50 border-ink-900/10',
  },
  unknown: {
    icon: FiHelpCircle,
    label: '证据不足',
    color: 'text-ink-500 bg-white/50 border-ink-900/10',
  },
};

const DEFAULT = LEVEL_CONFIG.unknown;

function RiskTrafficLight({ riskLevel, riskCounts }) {
  const config = LEVEL_CONFIG[riskLevel] || DEFAULT;
  const Icon = config.icon;

  return (
    <div className={`flex items-center gap-4 rounded-2xl border px-5 py-3 ${config.color}`}>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/45 text-xl" aria-label={config.label}>
        <Icon aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold">{config.label}</p>
        {riskCounts ? (
          <p className="mt-0.5 font-mono text-[11px] opacity-75">
            {translateRiskLevel('critical')}:{riskCounts.critical || 0}
            {' · '}{translateRiskLevel('high')}:{riskCounts.high || 0}
            {' · '}{translateRiskLevel('medium')}:{riskCounts.medium || 0}
            {' · '}{translateRiskLevel('low')}:{riskCounts.low || 0}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export default RiskTrafficLight;
