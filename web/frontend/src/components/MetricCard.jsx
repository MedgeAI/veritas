function MetricCard({ label, value }) {
  return (
    <div className="rounded-2xl border border-ink-900/8 bg-paper-100/60 p-4">
      <p className="metric-label">{label}</p>
      <p className="mt-2 font-display text-3xl font-bold text-ink-900 tabular-nums truncate" title={value}>{value}</p>
    </div>
  );
}

export default MetricCard;
