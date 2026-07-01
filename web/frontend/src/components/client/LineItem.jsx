/**
 * LineItem — Cost breakdown item for reverification.
 *
 * Explicit cost-row variants for reverification.
 * Included rows use a filled check; optional rows use an outline check.
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

function LineItemFrame({ icon, label, detail, price, labelClassName, priceClassName }) {
  return (
    <div className="flex items-start border-b border-ink-900/5 py-4">
      <div className="ml-0">{icon}</div>

      <div className="ml-3 flex-1 min-w-0">
        <div className={`text-[13px] ${labelClassName}`}>{label}</div>
        {detail && (
          <div className="mt-0.5 text-[11px] text-ink-500">{detail}</div>
        )}
      </div>

      <div className={`shrink-0 font-mono text-[13px] tabular-nums ${priceClassName}`}>
        {price}
      </div>
    </div>
  );
}

export function PrimaryLineItem(props) {
  return (
    <LineItemFrame
      {...props}
      icon={<CheckFilled />}
      labelClassName="text-ink-900"
      priceClassName="font-medium text-ink-900"
    />
  );
}

export function IncludedLineItem(props) {
  return (
    <LineItemFrame
      {...props}
      icon={<CheckFilled />}
      labelClassName="text-ink-900"
      priceClassName="text-ink-900"
    />
  );
}

export function OptionalLineItem(props) {
  return (
    <LineItemFrame
      {...props}
      icon={<CheckOutline />}
      labelClassName="text-ink-500"
      priceClassName="text-ink-500"
    />
  );
}
