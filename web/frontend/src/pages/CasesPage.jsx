import { useMemo } from 'react';
import { FiActivity, FiAlertCircle, FiArrowRight, FiCheckCircle, FiFilePlus, FiTrendingUp } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';
import { translateStatus } from '../utils/piLabels.js';

function classifyCase(item) {
  if (item.status === 'Review Needed' || (item.review_needed_count || 0) > 0) return 'pending';
  if (item.technical_risk === 'critical' || item.technical_risk === 'high') return 'pending';
  if (item.status === 'Running' || item.status === 'Planning') return 'running';
  if (item.status === 'Report Ready' || item.status === 'Archived') return 'done';
  return 'draft';
}

const GROUPS = [
  { key: 'pending', label: '待处理', sub: '需要人工复核的 findings', icon: FiAlertCircle, border: 'border-red-500/30', bg: 'bg-red-500/5', chipBg: 'bg-red-500/10', chipText: 'text-red-700' },
  { key: 'running', label: '进行中', sub: '正在执行审查流程', icon: FiActivity, border: 'border-amber-500/30', bg: 'bg-amber-500/5', chipBg: 'bg-amber-500/10', chipText: 'text-amber-700' },
  { key: 'done', label: '已完成', sub: '审查完毕，报告就绪', icon: FiCheckCircle, border: 'border-green-500/30', bg: 'bg-green-500/5', chipBg: 'bg-green-500/10', chipText: 'text-green-700' },
  { key: 'draft', label: '待上传', sub: '已创建但尚未提交材料', icon: FiFilePlus, border: 'border-ink-900/10', bg: 'bg-white/40', chipBg: 'bg-ink-900/8', chipText: 'text-ink-500' },
];

function CaseCard({ item, onSelect, isSelected }) {
  const risk = item.technical_risk || 'pending';
  return (
    <button
      type="button"
      onClick={() => onSelect(item.case_id)}
      aria-label={`进入 ${item.paper_title || '未命名项目'}`}
      className={`flow-list-item group grid w-full gap-3 px-4 py-4 text-left transition md:grid-cols-[minmax(0,1fr)_auto] ${
        isSelected ? 'bg-signal-100/50' : 'hover:bg-white/45'
      }`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="min-w-0 break-words font-display text-base font-semibold text-ink-900">
            {item.paper_title || '未命名项目'}
          </h3>
          <StatusPill>{translateStatus(item.status)}</StatusPill>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-500">
          {item.review_needed_count > 0 && (
            <span className="mono-chip">{item.review_needed_count} findings</span>
          )}
          {risk !== 'pending' && risk !== 'N/A' && (
            <span className="mono-chip">risk: {risk}</span>
          )}
          <span className="mono-chip">{new Intl.DateTimeFormat(navigator.languages ?? ['zh-CN'], { month: '2-digit', day: '2-digit' }).format(new Date(item.created_at))}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 text-sm font-semibold text-signal-700">
        进入
        <FiArrowRight className="transition group-hover:translate-x-1" aria-hidden="true" />
      </div>
    </button>
  );
}

function CasesPage({ cases, selectedCaseId, onSelectCase, onNavigate }) {
  const stats = useMemo(() => {
    const totalCases = cases.length;
    const totalFindings = cases.reduce((sum, c) => sum + (c.review_needed_count || 0), 0);
    const criticalCount = cases.filter((c) => c.technical_risk === 'critical' || c.technical_risk === 'high').length;
    const runningCount = cases.filter((c) => c.status === 'Running').length;
    return { totalCases, totalFindings, criticalCount, runningCount };
  }, [cases]);

  const grouped = useMemo(() => {
    const buckets = { pending: [], running: [], done: [], draft: [] };
    for (const item of cases) {
      buckets[classifyCase(item)].push(item);
    }
    // Sort pending by review_needed_count desc, others by created_at desc
    buckets.pending.sort((a, b) => (b.review_needed_count || 0) - (a.review_needed_count || 0));
    for (const key of ['running', 'done', 'draft']) {
      buckets[key].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    }
    return buckets;
  }, [cases]);

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-blue-500/10 text-blue-600">
              <FiActivity className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Total Cases</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.totalCases}</p>
            </div>
          </div>
        </div>

        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-purple-500/10 text-purple-600">
              <FiTrendingUp className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Total Findings</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.totalFindings}</p>
              {stats.criticalCount > 0 && (
                <p className="mt-1 text-xs text-red-600">{stats.criticalCount} cases at risk</p>
              )}
            </div>
          </div>
        </div>

        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-red-500/10 text-red-600">
              <FiAlertCircle className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Critical / High</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.criticalCount}</p>
            </div>
          </div>
        </div>

        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-orange-500/10 text-orange-600">
              <FiActivity className="text-xl" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Running</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.runningCount}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Kanban board */}
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-xl font-semibold text-ink-900">审查看板</h2>
          <button type="button" className="btn-primary" onClick={() => onNavigate('newAudit')}>
            <FiFilePlus aria-hidden="true" />
            新建审查
          </button>
        </div>

        {cases.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-ink-900/20 bg-white/45 p-8 text-center">
            <p className="font-display text-xl font-semibold">还没有 Case</p>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-500">
              点击右上角"新建审查"上传论文 PDF 与补充材料。
            </p>
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            {GROUPS.map((group) => {
              const items = grouped[group.key];
              const Icon = group.icon;
              return (
                <section
                  key={group.key}
                  className={`dossier-panel rounded-[2rem] border ${group.border} ${group.bg} p-5`}
                >
                  <div className="flex items-center justify-between border-b border-ink-900/10 pb-3">
                    <div className="flex items-center gap-2">
                      <Icon className={`text-lg ${group.chipText}`} aria-hidden="true" />
                      <div>
                        <h3 className="font-display text-base font-semibold text-ink-900">{group.label}</h3>
                        <p className="text-xs text-ink-500">{group.sub}</p>
                      </div>
                    </div>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${group.chipBg} ${group.chipText}`}>
                      {items.length}
                    </span>
                  </div>

                  {items.length === 0 ? (
                    <p className="mt-4 text-center text-sm text-ink-400">无</p>
                  ) : (
                    <div className="mt-2 divide-y divide-ink-900/8">
                      {items.map((item) => (
                        <CaseCard
                          key={item.case_id}
                          item={item}
                          onSelect={onSelectCase}
                          isSelected={selectedCaseId === item.case_id}
                        />
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default CasesPage;
