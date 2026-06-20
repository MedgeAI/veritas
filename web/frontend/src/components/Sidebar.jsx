import { useState } from 'react';
import {
  FiActivity,
  FiArchive,
  FiBookOpen,
  FiChevronDown,
  FiChevronRight,
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
      ['cbir', 'CBIR Search', FiSearch],
      ['investigation', 'Investigation Board', FiSearch],
      ['review', 'Review Queue', FiBookOpen],
      ['advanced', 'Advanced Lab', FiCpu],
    ],
  },
];

function formatCaseDate(isoString) {
  if (!isoString) return '';
  try {
    const date = new Date(isoString);
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${month}-${day} ${hours}:${minutes}`;
  } catch {
    return '';
  }
}

function getCaseStatusBadge(caseItem) {
  if (!caseItem) return null;

  const latestRunStatus = caseItem.latest_run_status;
  const hasFindings = caseItem.finding_count > 0;

  if (latestRunStatus === 'running') {
    return { text: '运行中', className: 'bg-blue-500/20 text-blue-200' };
  }
  if (latestRunStatus === 'failed') {
    return { text: '失败', className: 'bg-red-500/20 text-red-200' };
  }
  if (hasFindings) {
    const criticalCount = caseItem.findings_by_severity?.critical || 0;
    const highCount = caseItem.findings_by_severity?.high || 0;
    if (criticalCount > 0) {
      return { text: `${criticalCount} critical`, className: 'bg-red-500/20 text-red-200' };
    }
    if (highCount > 0) {
      return { text: `${highCount} high`, className: 'bg-orange-500/20 text-orange-200' };
    }
    return { text: `${caseItem.finding_count} findings`, className: 'bg-yellow-500/20 text-yellow-200' };
  }
  return { text: '已完成', className: 'bg-green-500/20 text-green-200' };
}

function Sidebar({ activePage, onNavigate, cases, selectedCaseId, onSelectCase, caseCount }) {
  const [casesExpanded, setCasesExpanded] = useState(true);
  const hasSelectedCase = Boolean(selectedCaseId);

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
        {/* Case 列表区域 */}
        {cases && cases.length > 0 && (
          <section>
            <button
              type="button"
              onClick={() => setCasesExpanded(!casesExpanded)}
              className="flex w-full items-center justify-between px-3 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-200/45 hover:text-paper-200/65"
            >
              <span>Audit Cases</span>
              {casesExpanded ? <FiChevronDown className="text-sm" /> : <FiChevronRight className="text-sm" />}
            </button>
            {casesExpanded && (
              <div className="mt-2 space-y-1">
                {cases.map((caseItem) => {
                  const isSelected = caseItem.case_id === selectedCaseId;
                  const statusBadge = getCaseStatusBadge(caseItem);
                  return (
                    <button
                      key={caseItem.case_id}
                      type="button"
                      onClick={() => onSelectCase && onSelectCase(caseItem.case_id)}
                      className={`flex w-full flex-col gap-1 rounded-2xl px-3 py-3 text-left transition ${
                        isSelected
                          ? 'bg-paper-50 text-ink-900 shadow-insetline'
                          : 'text-paper-100/72 hover:bg-paper-50/[0.08] hover:text-paper-50'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="flex-1 text-sm font-medium leading-tight truncate">
                          {caseItem.paper_id || caseItem.case_id}
                        </span>
                        {statusBadge && (
                          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${statusBadge.className}`}>
                            {statusBadge.text}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] opacity-70">
                        <span>{formatCaseDate(caseItem.created_at)}</span>
                        {caseItem.finding_count > 0 && (
                          <>
                            <span>·</span>
                            <span>{caseItem.finding_count} findings</span>
                          </>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        )}

        {/* Case Flow - Cases 和 New Audit 始终可用 */}
        <section>
          <p className="px-3 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-200/45">Case Flow</p>
          <div className="mt-2 space-y-1">
            {GROUPS[0].items.filter(([page]) => page === 'cases' || page === 'newAudit').map(([page, label, Icon]) => {
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
                      : 'text-paper-100/72 hover:bg-paper-50/[0.08] hover:text-paper-50'
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

        {/* Case Flow - 其他页面需要选中 case */}
        <section>
          <div className="mt-2 space-y-1">
            {GROUPS[0].items.filter(([page]) => page !== 'cases' && page !== 'newAudit').map(([page, label, Icon]) => {
              const active = activePage === page;
              const disabled = !hasSelectedCase;
              return (
                <button
                  key={page}
                  type="button"
                  onClick={() => !disabled && onNavigate(page)}
                  disabled={disabled}
                  aria-current={active ? 'page' : undefined}
                  className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm transition ${
                    disabled
                      ? 'cursor-not-allowed text-paper-100/25'
                      : active
                      ? 'bg-paper-50 text-ink-900 shadow-insetline'
                      : 'text-paper-100/72 hover:bg-paper-50/[0.08] hover:text-paper-50'
                  }`}
                >
                  <Icon className="text-lg" aria-hidden="true" />
                  <span className="flex-1">{label}</span>
                </button>
              );
            })}
          </div>
        </section>

        {/* Evidence Lanes - 需要选中 case */}
        <section>
          <p className="px-3 text-[10px] font-bold uppercase tracking-[0.22em] text-paper-200/45">Evidence Lanes</p>
          <div className="mt-2 space-y-1">
            {GROUPS[1].items.map(([page, label, Icon]) => {
              const active = activePage === page;
              const disabled = !hasSelectedCase;
              return (
                <button
                  key={page}
                  type="button"
                  onClick={() => !disabled && onNavigate(page)}
                  disabled={disabled}
                  aria-current={active ? 'page' : undefined}
                  className={`flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm transition ${
                    disabled
                      ? 'cursor-not-allowed text-paper-100/25'
                      : active
                      ? 'bg-paper-50 text-ink-900 shadow-insetline'
                      : 'text-paper-100/72 hover:bg-paper-50/[0.08] hover:text-paper-50'
                  }`}
                >
                  <Icon className="text-lg" aria-hidden="true" />
                  <span className="flex-1">{label}</span>
                </button>
              );
            })}
          </div>
        </section>
      </nav>

      <div className="border-t border-paper-50/10 p-4 text-xs leading-5 text-paper-100/58">
        真实 MinerU / LLM 默认开启。前端只负责编排输入、进度与证据阅读，不伪造审查结论。
      </div>
    </aside>
  );
}

export default Sidebar;
