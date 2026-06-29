/**
 * ServiceRow — Service tier selector row.
 *
 * Reference: prototype SubmitPage serviceList.
 * Left: name + features. Right: price + est time.
 * Selected: accent border.
 */

export default function ServiceRow({ name, price, est, features, selected = false, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-5 border-b border-ink-900/5 py-[22px] text-left transition-colors ${
        selected ? 'bg-paper-100/60' : 'hover:bg-paper-100/40'
      }`}
      aria-pressed={selected}
    >
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-ink-900">{name}</span>
          {selected && (
            <span className="rounded-sm border border-accent-500 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.15em] text-accent-500">
              当前选择
            </span>
          )}
        </div>
        <div className="mt-1 text-xs leading-[1.6] text-ink-700">{features}</div>
      </div>

      <div className="shrink-0 text-right">
        <div className="font-display text-[22px] font-normal text-ink-900">{price}</div>
        {est && (
          <div className="mt-0.5 text-[10px] italic text-ink-500">{est}</div>
        )}
      </div>
    </button>
  );
}
