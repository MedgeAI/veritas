/**
 * FindingCard — single finding in the report list.
 *
 * Left 2px color border: critical=risk-500, warning=accent-500, info=ink-500.
 * Displays: finding_id, severity tag, category, summary, location, action buttons.
 */

const RISK_CONFIG = {
  critical: { label: '严重', borderColor: 'border-risk-500', textColor: 'text-risk-500' },
  high:     { label: '高',    borderColor: 'border-risk-500', textColor: 'text-risk-500' },
  warning:  { label: '警告', borderColor: 'border-accent-500', textColor: 'text-accent-500' },
  medium:   { label: '警告', borderColor: 'border-accent-500', textColor: 'text-accent-500' },
  info:     { label: '注意', borderColor: 'border-ink-500', textColor: 'text-ink-500' },
  low:      { label: '低',    borderColor: 'border-ink-500', textColor: 'text-ink-500' },
};

export default function FindingCard({ finding, onViewDetails, role = 'author' }) {
  const cfg = RISK_CONFIG[finding.risk_level] || RISK_CONFIG.info;
  const hasSourceRef = Boolean(finding.source_ref);

  const buttonText =
    role === 'author'
      ? hasSourceRef
        ? '查看建议与修复'
        : '查看详情'
      : '查看证据链';

  return (
    <div
      className={`mb-2.5 rounded-sm border border-paper-200 bg-white p-5 border-l-2 ${cfg.borderColor}`}
    >
      <div className="flex items-start gap-4">
        {/* Finding ID rail */}
        <div className="w-12 flex-shrink-0 pt-0.5 font-mono text-xs font-medium tracking-wider">
          <span className={cfg.textColor}>{finding.finding_id}</span>
        </div>

        <div className="min-w-0 flex-1">
          {/* Tags row */}
          <div className="flex items-center gap-2.5">
            <span
              className={`rounded-sm border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.15em] ${cfg.textColor} border-current`}
            >
              {cfg.label}
            </span>
            <span className="text-[11px] italic text-ink-500">
              {finding.issue_category}
            </span>
          </div>

          {/* Summary */}
          <div className="mt-2.5 text-sm leading-relaxed text-ink-900 font-medium">
            {finding.summary}
          </div>

          {/* Location */}
          {finding.location && (
            <div className="mt-1.5 font-mono text-[11px] text-ink-500">
              {finding.location}
            </div>
          )}

          {/* Evidence refs */}
          {finding.evidence_refs && finding.evidence_refs.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {finding.evidence_refs.slice(0, 3).map((ref, i) => (
                <span key={i} className="mono-chip truncate max-w-[200px]">
                  {ref}
                </span>
              ))}
              {finding.evidence_refs.length > 3 && (
                <span className="text-[10px] text-ink-500">
                  +{finding.evidence_refs.length - 3}
                </span>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="mt-3.5 flex items-center gap-3">
            <button
              className={`rounded-sm px-3 py-1.5 text-[11.5px] transition-colors ${
                role === 'author' && hasSourceRef
                  ? 'bg-ink-900 text-paper-50 hover:bg-ink-700'
                  : 'border border-paper-300 text-ink-700 hover:bg-paper-100'
              }`}
              onClick={() => onViewDetails?.(finding)}
            >
              {buttonText} &rarr;
            </button>
            {role === 'author' && hasSourceRef && (
              <button
                className="rounded-sm border border-paper-300 px-3 py-1.5 text-[11.5px] text-ink-700 hover:bg-paper-100"
                onClick={() => onViewDetails?.(finding)}
              >
                申诉/说明
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
