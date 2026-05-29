function PlaceholderPage({ title, body, lanes = [] }) {
  return (
    <section className="dossier-panel overflow-hidden rounded-[2rem] p-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div>
          <p className="metric-label">Planned Module</p>
          <h2 className="mt-3 font-display text-3xl font-semibold text-ink-900">{title}</h2>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-ink-500">{body}</p>
          <div className="mt-8 rounded-[2rem] border border-dashed border-ink-900/20 bg-white/40 p-8">
            <p className="font-display text-2xl font-semibold">P1 先保留入口，避免现在把所有能力塞进一个报告页</p>
            <p className="mt-3 text-sm leading-6 text-ink-500">
              当前验收重点是 Web 端创建 case、提交输入、启动审查、显示进度、打开最终 HTML 报告。后续模块会直接读取同一套 artifacts 和 tool registry trace。
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
