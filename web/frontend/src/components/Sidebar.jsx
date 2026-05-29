import {
  FiActivity,
  FiArchive,
  FiBookOpen,
  FiCpu,
  FiFileText,
  FiGrid,
  FiImage,
  FiLayers,
  FiPlusCircle,
  FiSearch,
} from 'react-icons/fi';

const GROUPS = [
  {
    label: 'Case Flow',
    items: [
      ['cases', 'Cases', FiArchive],
      ['newAudit', 'New Audit', FiPlusCircle],
      ['mission', 'Mission Control', FiActivity],
      ['report', 'Report Center', FiFileText],
    ],
  },
  {
    label: 'Evidence Lanes',
    items: [
      ['evidence', 'Evidence Workspace', FiLayers],
      ['visual', 'Visual Forensics', FiImage],
      ['investigation', 'Investigation Board', FiSearch],
      ['review', 'Review Queue', FiBookOpen],
      ['advanced', 'Advanced Lab', FiCpu],
    ],
  },
];

function Sidebar({ activePage, onNavigate, caseCount }) {
  return (
    <aside className="hidden min-h-screen w-[292px] shrink-0 border-r border-ink-900/10 bg-ink-900 text-paper-50 lg:flex lg:flex-col">
      <div className="border-b border-paper-50/10 p-6">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-2xl bg-paper-50 text-ink-900">
            <FiGrid aria-hidden="true" />
          </div>
          <div>
            <p className="font-display text-2xl font-semibold leading-none">Veritas</p>
            <p className="mt-1 text-xs uppercase tracking-[0.22em] text-paper-200/65">Audit Console</p>
          </div>
        </div>
        <p className="mt-6 text-sm leading-6 text-paper-100/72">
          面向干实验论文的 Agent-native 技术事实复核工作台。
        </p>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-4 py-5">
        {GROUPS.map((group) => (
          <section key={group.label}>
            <p className="px-3 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-200/45">{group.label}</p>
            <div className="mt-2 space-y-1">
              {group.items.map(([page, label, Icon]) => {
                const active = activePage === page;
                return (
                  <button
                    key={page}
                    type="button"
                    onClick={() => onNavigate(page)}
                    aria-current={active ? 'page' : undefined}
                    className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm transition ${
                      active
                        ? 'bg-paper-50 text-ink-900 shadow-insetline'
                        : 'text-paper-100/72 hover:bg-paper-50/8 hover:text-paper-50'
                    }`}
                  >
                    <Icon className="text-lg" aria-hidden="true" />
                    <span className="flex-1">{label}</span>
                    {page === 'cases' ? <span className="rounded-full bg-paper-50/12 px-2 py-0.5 text-[11px]">{caseCount}</span> : null}
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </nav>

      <div className="border-t border-paper-50/10 p-4 text-xs leading-5 text-paper-100/58">
        真实 MinerU / LLM 默认开启。前端只负责编排输入、进度与证据阅读，不伪造审查结论。
      </div>
    </aside>
  );
}

export default Sidebar;
