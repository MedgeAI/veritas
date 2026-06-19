function PlaceholderPage({ title, body, lanes = [] }) {
  return (
    <section className="dossier-panel overflow-hidden rounded-[2rem] p-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div>
          <p className="metric-label">Planned Module</p>
          <h2 className="mt-3 font-display text-3xl font-semibold text-ink-900">{title}</h2>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-ink-500">{body}</p>
          <div className="mt-8 rounded-[2rem] border border-dashed border-ink-900/20 bg-white/40 p-8">
            <p className="font-display text-2xl font-semibold">高级取证工具集成层</p>
            <p className="mt-3 text-sm leading-6 text-ink-500">
              用于承载重型视觉取证工具（ELIS panel-extractor、dense copy-move、CBIR 检索等）。
              这些工具已通过 adapter 接入后端 Tool Registry，可按需从 Investigation Board 触发。
            </p>
          </div>
        </div>
        <aside className="rounded-[2rem] bg-ink-900 p-5 text-paper-50">
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-paper-200/60">Reserved Lanes</p>
          <div className="mt-4 space-y-3">
            {lanes.map((lane) => (
              <div key={lane} className="rounded-2xl border border-paper-50/10 bg-paper-50/6 px-4 py-3 font-mono text-xs">
                {lane}
              </div>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}

export default PlaceholderPage;
