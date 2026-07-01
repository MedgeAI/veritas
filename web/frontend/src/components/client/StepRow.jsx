/**
 * StepRow — Vertical timeline step row for progress page.
 *
 * Props: { number, label, labelEn, status: 'done'|'completed'|'running'|'pending'|'failed'|'skipped'|'warning', detail, time, log? }
 * Vertical timeline with dot + connector line.
 * Done: filled ink-900 dot with check. Running: animated pulse. Pending: outline dot.
 * Reference: prototype ProgressPage stepRow
 */

function DotDone() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function DotRunning() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5">
      <circle cx="12" cy="12" r="10" strokeOpacity="0.3" />
      <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round">
        <animateTransform
          attributeName="transform"
          type="rotate"
          from="0 12 12"
          to="360 12 12"
          dur="1s"
          repeatCount="indefinite"
        />
      </path>
    </svg>
  );
}

function DotFailed() {
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function DotWarning() {
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round">
      <line x1="12" y1="5" x2="12" y2="13" />
      <circle cx="12" cy="18" r="1" />
    </svg>
  );
}

export default function StepRow({
  number,
  label,
  labelEn,
  status,
  detail,
  time,
  log,
}) {
  const isDone = status === 'done' || status === 'completed';
  const isRunning = status === 'running';
  const isFailed = status === 'failed';
  const isWarning = status === 'warning';
  const isPending = status === 'pending' || status === 'skipped';
  const textTone = isPending
    ? 'text-[#b8a878]'
    : isWarning
      ? 'text-[#8a5a00]'
      : 'text-ink-900';
  const detailTone = isPending
    ? 'text-[#b8a878]'
    : isWarning
      ? 'text-[#8a5a00]'
      : 'text-ink-700';

  // Dot styling: pending = outline (paper-50 bg + d8cea8 border), others = filled
  const dotBg = isDone
    ? 'bg-ink-900'
    : isRunning
      ? 'bg-accent-500'
      : isFailed
        ? 'bg-risk-500'
        : isWarning
          ? 'bg-[#8a5a00]'
          : 'bg-paper-50';
  const dotBorder = isDone
    ? 'border-ink-900'
    : isRunning
      ? 'border-accent-500'
      : isFailed
        ? 'border-risk-500'
        : isWarning
          ? 'border-[#8a5a00]'
          : 'border-[#d8cea8]';

  return (
    <div className="flex">
      {/* Left rail: 18px wide, contains dot + connector */}
      <div className="flex w-[18px] shrink-0 flex-col items-center">
        <div
          className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-[1.5px] mt-[2px] ${dotBg} ${dotBorder}`}
        >
          {isDone && <DotDone />}
          {isRunning && <DotRunning />}
          {isFailed && <DotFailed />}
          {isWarning && <DotWarning />}
        </div>
        {/* Connector line to next step */}
        <div
          className={`mt-1 w-[1px] flex-1 ${isDone ? 'bg-ink-900' : 'bg-paper-200'}`}
        />
      </div>

      {/* Right body */}
      <div className="min-w-0 flex-1 pb-8 pl-5">
        <div className="flex flex-wrap items-baseline gap-x-3.5">
          <span className="font-mono text-[11px] tracking-[0.15em] text-ink-300">
            {number}
          </span>
          <span
            className={`text-[15px] font-medium ${textTone}`}
          >
            {label}
          </span>
          <span className="font-display text-[11px] italic text-ink-500">
            {labelEn}
          </span>
          {time && (
            <span className="ml-auto text-[11px] text-ink-500">
              {time}
            </span>
          )}
        </div>
        <div
          className={`mt-2 text-[13px] leading-[1.6] ${detailTone}`}
        >
          {detail}
        </div>
        {log && log.length > 0 && (
          <div className="mt-3 rounded-sm bg-ink-900 px-3.5 py-3 font-mono text-[11.5px] leading-[1.7] text-paper-50">
            {log.map((line, i) => (
              <div
                key={i}
                className={line.startsWith('$') ? 'text-ink-900' : 'text-ink-500'}
                style={line.startsWith('$') ? { color: '#fbfaf6' } : { color: '#9b8d6f' }}
              >
                {line}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
