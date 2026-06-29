/**
 * LineItem — Cost breakdown item for reverification.
 *
 * Props: { included: boolean, label, detail, price, main? }
 * Check icon (filled if included, outline if optional). Label + detail. Price right.
 * Reference: prototype LineItem component
 */

function CheckFilled() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#3a3328" stroke="#3a3328" strokeWidth="1.5" />
      <path d="M9 12l2 2 4-4" stroke="#fbfaf6" strokeWidth="2" />
    </svg>
  );
}

function CheckOutline() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#b8a878" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
    </svg>
  );
}

export default function LineItem({ included, label, detail, price, main = false }) {
  return (
    <div className="flex items-start border-b border-ink-900/5 py-4">
      <div className="ml-0">
        {included ? <CheckFilled /> : <CheckOutline />}
      </div>

      <div className="ml-3 flex-1 min-w-0">
        <div className={`text-[13px] ${included ? 'text-ink-900' : 'text-ink-500'}`}>
          {label}
        </div>
        {detail && (
          <div className="mt-0.5 text-[11px] text-ink-500">{detail}</div>
        )}
      </div>

      <div
        className={`shrink-0 font-mono text-[13px] tabular-nums ${
          main ? 'font-medium text-ink-900' : included ? 'text-ink-900' : 'text-ink-500'
        }`}
      >
        {price}
      </div>
    </div>
  );
}
