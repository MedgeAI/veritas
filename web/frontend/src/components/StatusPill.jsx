const TONES = {
  ok: 'border-signal-500/25 bg-signal-100 text-signal-700',
  warn: 'border-caution-500/25 bg-caution-100 text-caution-700',
  risk: 'border-risk-500/25 bg-risk-100 text-risk-700',
  neutral: 'border-ink-900/10 bg-white/55 text-ink-500',
  running: 'border-signal-500/25 bg-signal-100 text-signal-700',
};

function inferTone(value) {
  const normalized = String(value || '').toLowerCase();
  if (['completed', 'report ready', 'uploaded'].includes(normalized)) return 'ok';
  if (['running', 'queued', 'planning'].includes(normalized)) return 'running';
  if (['failed', 'review needed'].includes(normalized)) return 'risk';
  if (['warning', 'pending'].includes(normalized)) return 'warn';
  return 'neutral';
}

function StatusPill({ children, tone }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-bold ${TONES[tone || inferTone(children)]}`}>
      {children}
    </span>
  );
}

export default StatusPill;
