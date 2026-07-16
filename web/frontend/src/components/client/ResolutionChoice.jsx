/**
 * ResolutionChoice — Decision choice card.
 *
 * Props: { icon, title, subtitle, desc, price, selected, onClick }
 * Card with icon left, content middle, price right.
 * Selected: accent border + bg.
 * Reference: prototype Choice component
 */

export default function ResolutionChoice({
  icon: Icon,
  title,
  subtitle,
  desc,
  price,
  selected = false,
  onClick,
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative flex w-full items-start rounded-sm border-2 p-[22px] text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 ${
        selected
          ? 'border-accent-500 bg-accent-50/50'
          : 'border-paper-200 bg-white hover:border-paper-300 hover:bg-paper-50/50'
      }`}
      style={{ marginBottom: 10 }}
      aria-pressed={selected}
    >
      {Icon && (
        <Icon
          size={18}
          strokeWidth={1.4}
          className={`shrink-0 ${selected ? 'text-accent-700' : 'text-ink-500'}`}
        />
      )}
      <div className="ml-4 min-w-0 flex-1">
        <div className="text-[13.5px] font-medium text-ink-900">{title}</div>
        {subtitle && (
          <div className="mt-0.5 text-[10px] italic text-ink-500">{subtitle}</div>
        )}
        <div className="mt-1.5 text-xs leading-relaxed text-ink-700">{desc}</div>
      </div>
      {price && (
        <div className="ml-5 shrink-0 self-start font-display text-[15px] text-ink-900">
          {price}
        </div>
      )}
      {selected && (
        <span className="absolute right-3 top-3 rounded-full bg-accent-500 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
          已选
        </span>
      )}
    </button>
  );
}
