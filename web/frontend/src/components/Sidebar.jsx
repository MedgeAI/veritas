import { useMemo } from 'react';
import {
  FiActivity,
  FiAlertTriangle,
  FiBookOpen,
  FiFileText,
  FiGrid,
  FiImage,
  FiPlusCircle,
  FiRefreshCw,
} from 'react-icons/fi';
import { FaUsers } from 'react-icons/fa';

const GROUPS = [
  {
    label: 'Case Flow',
    items: [
      ['cases', 'Dashboard', FiGrid],
      ['newAudit', '新建审查', FiPlusCircle],
      ['mission', '运行监控', FiActivity],
      ['report', '审查报告', FiFileText],
    ],
  },
  {
    label: '调查流程',
    items: [
      ['findings', '审查发现', FiAlertTriangle],
      ['evidence', '证据审查', FiImage],
      ['actions', '行动项', FiBookOpen],
    ],
  },
  {
    label: '认证服务',
    items: [
      ['reverification', '修订重核', FiRefreshCw],
    ],
  },
];

let _dateFmt;
const formatCaseDate = (dateStr) => {
  if (!_dateFmt) _dateFmt = new Intl.DateTimeFormat(navigator.languages ?? ['zh-CN'], { month: '2-digit', day: '2-digit' });
  try { return _dateFmt.format(new Date(dateStr)); } catch { return dateStr; }
};

function Sidebar({ activePage, onNavigate, cases, selectedCaseId, onSelectCase, caseCount, isAdmin, alwaysAvailablePages }) {
  const hasSelectedCase = Boolean(selectedCaseId);
  const alwaysAvail = alwaysAvailablePages ?? new Set(['cases', 'newAudit']);

  const recentCases = useMemo(
    () => [...(cases || [])]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5),
    [cases],
  );

  return (
    <aside className="hidden sticky top-0 h-screen w-[292px] shrink-0 overflow-y-auto border-r border-ink-900/10 bg-ink-900 text-paper-50 lg:flex lg:flex-col">
      <div className="border-b border-paper-50/10 p-6">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-2xl bg-paper-50 text-ink-900">
            <FiGrid aria-hidden="true" />
          </div>
          <div>
            <p className="font-display text-2xl font-semibold leading-none">Veritas</p>
            <p className="mt-1 text-xs uppercase tracking-[0.22em] text-paper-300">Audit Console</p>
          </div>
        </div>
        <p className="mt-6 text-sm leading-6 text-paper-300">
          面向生物医药论文的 Agent-native 技术事实复核工作台。
        </p>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-4 py-5">
        {GROUPS.map((group, gi) => (
          <section key={group.label}>
            <p className="px-3 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-300">{group.label}</p>
            <div className="mt-2 space-y-1">
              {group.items.map(([page, label, Icon]) => {
                const active = activePage === page;
                // Cases and NewAudit are always available; others require selected case
                const alwaysAvailable = alwaysAvail.has(page);
                const disabled = !alwaysAvailable && !hasSelectedCase;
                return (
                  <button
                    key={page}
                    type="button"
                    onClick={() => !disabled && onNavigate(page)}
                    disabled={disabled}
                    aria-current={active ? 'page' : undefined}
                    className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm transition ${
                      disabled
                        ? 'cursor-not-allowed text-paper-300'
                        : active
                        ? 'bg-paper-50 text-ink-900 shadow-insetline'
                        : 'text-paper-300 hover:bg-paper-50/[0.08] hover:text-paper-50'
                    }`}
                  >
                    <Icon className="text-lg" aria-hidden="true" />
                    <span className="flex-1">{label}</span>
                    {page === 'cases' ? (
                      <span className="rounded-full bg-paper-50/12 px-2 py-0.5 text-[11px]">{caseCount}</span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </section>
        ))}

        {/* Admin section */}
        {isAdmin ? (
          <section>
            <p className="px-3 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-300">管理</p>
            <div className="mt-2 space-y-1">
              <button
                type="button"
                onClick={() => onNavigate('admin')}
                aria-current={activePage === 'admin' ? 'page' : undefined}
                aria-label="用户管理"
                className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm transition ${
                  activePage === 'admin'
                    ? 'bg-paper-50 text-ink-900 shadow-insetline'
                    : 'text-paper-300 hover:bg-paper-50/[0.08] hover:text-paper-50'
                }`}
              >
                <FaUsers className="text-lg" aria-hidden="true" />
                <span className="flex-1">用户管理</span>
              </button>
            </div>
          </section>
        ) : null}
      </nav>

      {/* Recent cases quick-switch */}
      {recentCases.length > 0 && (
        <div className="border-t border-paper-50/10 px-4 py-4">
          <p className="mb-2 px-1 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-300">最近审查项目</p>
          <div className="space-y-1">
            {recentCases.map((item) => {
              const isSelected = item.case_id === selectedCaseId;
              return (
                <button
                  key={item.case_id}
                  type="button"
                  onClick={() => onSelectCase && onSelectCase(item.case_id)}
                  className={`flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left text-xs transition ${
                    isSelected
                      ? 'bg-paper-50 text-ink-900'
                      : 'text-paper-300 hover:bg-paper-50/[0.08] hover:text-paper-50'
                  }`}
                >
                  <span className="flex-1 truncate">{item.paper_title || '未命名项目'}</span>
                  <span className="shrink-0 text-[10px] text-paper-300">{formatCaseDate(item.created_at)}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="border-t border-paper-50/10 p-4 text-xs leading-5 text-paper-300">
        呈现结构化证据与待办事项，不代替学术判断。
      </div>
    </aside>
  );
}

export default Sidebar;
