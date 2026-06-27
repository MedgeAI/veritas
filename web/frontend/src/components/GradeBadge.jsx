/**
 * GradeBadge — Certification grade visual (A / B / C / D).
 *
 * Renders a prominent grade badge matching the prototype's "档案感" style.
 * Each grade has a distinct color and Chinese label.
 */

const GRADE_CONFIG = {
  A: { label: '完全通过', color: 'bg-signal-500 text-white', ring: 'ring-signal-200' },
  B: { label: '有条件通过', color: 'bg-accent-500 text-white', ring: 'ring-accent-200' },
  C: { label: '待修订', color: 'bg-caution-500 text-white', ring: 'ring-caution-200' },
  D: { label: '未通过', color: 'bg-risk-500 text-white', ring: 'ring-risk-200' },
};

const DEFAULT_CONFIG = { label: '待评级', color: 'bg-ink-200 text-ink-600', ring: 'ring-ink-100' };

export default function GradeBadge({ grade, dimensions, size = 'md' }) {
  const config = GRADE_CONFIG[grade] || DEFAULT_CONFIG;
  const isLarge = size === 'lg';

  return (
    <div className={`inline-flex items-center gap-3 rounded-2xl ring-2 ${config.ring} ${isLarge ? 'p-4' : 'p-2.5'}`}>
      <div
        className={`${isLarge ? 'h-16 w-16 text-4xl' : 'h-10 w-10 text-xl'} grid place-items-center rounded-xl font-display font-bold ${config.color}`}
      >
        {grade || '?'}
      </div>
      <div className={isLarge ? '' : 'hidden sm:block'}>
        <p className={`font-semibold text-ink-900 ${isLarge ? 'text-lg' : 'text-sm'}`}>
          {config.label}
        </p>
        {dimensions && dimensions.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-2">
            {dimensions.map((d) => (
              <span
                key={d.name}
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  d.status === 'pass'
                    ? 'bg-signal-50 text-signal-700'
                    : d.status === 'pass_with_notes'
                    ? 'bg-accent-50 text-accent-700'
                    : d.status === 'warning'
                    ? 'bg-caution-50 text-caution-700'
                    : 'bg-risk-50 text-risk-700'
                }`}
              >
                {d.label}
                <span className="font-mono">
                  {d.status === 'pass' ? '✓' : d.status === 'pass_with_notes' ? '≈' : d.status === 'warning' ? '!' : '✗'}
                </span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * GradeBadgeCompact — small inline badge for cards/lists.
 */
export function GradeBadgeCompact({ grade }) {
  const config = GRADE_CONFIG[grade] || DEFAULT_CONFIG;
  return (
    <span
      className={`inline-grid h-7 w-7 place-items-center rounded-lg text-xs font-bold ${config.color}`}
      title={config.label}
    >
      {grade || '?'}
    </span>
  );
}
