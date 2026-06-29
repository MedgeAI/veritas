/**
 * TierRow — Reproducibility tier selector row.
 *
 * Reference: prototype SubmitPage tierList.
 * Left: badge letter. Right: tier name + description.
 * Selected state: accent border.
 */

export default function TierRow({ tier, badge, desc, selected = false, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-5 border-b border-ink-900/5 py-5 text-left transition-colors ${
        selected ? 'bg-paper-100/60' : 'hover:bg-paper-100/40'
      }`}
      aria-pressed={selected}
    >
      <div
        className={`flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-sm border font-display text-[18px] font-medium transition-colors ${
          selected
            ? 'border-accent-500 bg-paper-50 text-accent-500'
            : 'border-ink-900 bg-paper-50 text-ink-900'
        }`}
      >
        {badge}
      </div>

      <div className="flex-1">
        <div className="text-sm font-medium text-ink-900">{tier}</div>
        <div className="mt-0.5 text-[12.5px] leading-5 text-ink-700">{desc}</div>
      </div>

      {selected && (
        <div className="rounded-sm border border-accent-500 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.15em] text-accent-500">
          已选
        </div>
      )}
    </button>
  );
}
