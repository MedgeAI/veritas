function LoadingFallback() {
  return (
    <div className="dossier-panel relative overflow-hidden rounded-2xl p-8" role="status" aria-busy="true">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal-500 to-transparent animate-scan-line" aria-hidden="true" />
      <p className="metric-label">装载中</p>
      <p className="mt-3 text-sm text-ink-500">正在装载审查工作台模块…</p>
    </div>
  );
}

export default LoadingFallback;
