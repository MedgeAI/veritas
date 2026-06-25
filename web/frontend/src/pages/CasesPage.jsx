import { useEffect, useMemo, useRef, useState } from 'react';
import { FaTrash } from 'react-icons/fa';
import { FiActivity, FiAlertCircle, FiArrowRight, FiCheckCircle, FiFilePlus, FiTrendingUp } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';
import { deleteCase } from '../services/api.js';
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

function CaseCard({ item, onSelect, isSelected, isAdmin, onDeleteCase }) {
  const risk = item.technical_risk || 'pending';
  return (
    <div
      className={`flow-list-item group grid w-full gap-3 px-4 py-4 text-left transition md:grid-cols-[minmax(0,1fr)_auto] md:items-center ${
        isSelected ? 'bg-signal-100/50' : 'hover:bg-white/45'
      }`}
    >
      <button
        type="button"
        onClick={() => onSelect(item.case_id)}
        className="min-w-0 text-left"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 break-words font-display text-base font-semibold text-ink-900">
            {item.paper_title || '未命名项目'}
          </span>
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
      </button>
      <div className="flex items-center justify-end gap-2 text-sm font-semibold text-signal-700">
        {isAdmin && (
          <button
            type="button"
            className="rounded-lg p-1.5 text-ink-300 transition hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
            aria-label={`删除 ${item.paper_title || item.case_id}`}
            onClick={() => onDeleteCase(item)}
          >
            <FaTrash className="text-xs" aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          className="flex items-center gap-1 rounded-lg px-2 py-1 transition hover:bg-signal-100/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
          onClick={() => onSelect(item.case_id)}
        >
          进入
          <FiArrowRight className="transition group-hover:translate-x-1" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function CasesPage({ cases, selectedCaseId, onSelectCase, onNavigate, isAdmin, onRefreshCases }) {
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const dialogRef = useRef(null);
  const cancelBtnRef = useRef(null);

  useEffect(() => {
    if (!deleteTarget) return undefined;
    const previouslyFocused = document.activeElement;
    // Focus cancel button on open
    const timer = setTimeout(() => {
      cancelBtnRef.current?.focus();
    }, 0);

    const dialog = dialogRef.current;
    if (!dialog) return () => clearTimeout(timer);

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        if (!deleteLoading) setDeleteTarget(null);
        return;
      }
      if (event.key === 'Tab') {
        const focusable = dialog.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey) {
          if (document.activeElement === first) {
            event.preventDefault();
            last.focus();
          }
        } else if (document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    dialog.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(timer);
      dialog.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [deleteTarget, deleteLoading]);

  const stats = useMemo(() => {
    const totalCases = cases.length;
    const totalFindings = cases.reduce((sum, c) => sum + (c.review_needed_count || 0), 0);
    const criticalCount = cases.filter((c) => c.technical_risk === 'critical' || c.technical_risk === 'high').length;
    const runningCount = cases.filter((c) => c.status === 'Running').length;

    // Risk distribution for mini bar
    const riskDist = { critical: 0, high: 0, medium: 0, low: 0, unknown: 0 };
    for (const c of cases) {
      const r = c.technical_risk || 'unknown';
      if (r in riskDist) riskDist[r]++;
      else riskDist.unknown++;
    }

    // Recent activity: cases created in last 7 days
    const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const recentCount = cases.filter((c) => new Date(c.created_at).getTime() > weekAgo).length;

    // Pending review summary
    const pendingReview = cases.filter((c) => (c.review_needed_count || 0) > 0);
    const pendingFindings = pendingReview.reduce((sum, c) => sum + (c.review_needed_count || 0), 0);

    return { totalCases, totalFindings, criticalCount, runningCount, riskDist, recentCount, pendingReview: pendingReview.length, pendingFindings };
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

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    setDeleteError('');
    try {
      await deleteCase(deleteTarget.case_id);
      setDeleteTarget(null);
      if (onRefreshCases) onRefreshCases();
    } catch (err) {
      setDeleteError(err.message || '删除失败，请稍后重试');
    } finally {
      setDeleteLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-blue-500/10 text-blue-600">
              <FiActivity className="text-xl" aria-hidden="true" />
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
              <FiTrendingUp className="text-xl" aria-hidden="true" />
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
              <FiAlertCircle className="text-xl" aria-hidden="true" />
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
              <FiActivity className="text-xl" aria-hidden="true" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Running</p>
              <p className="font-display text-2xl font-semibold text-ink-900">{stats.runningCount}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Aggregate summary strip */}
      {cases.length > 0 && (
        <div className="dossier-panel rounded-2xl p-5">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            {/* Risk distribution mini bar */}
            <div className="flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">风险分布</p>
              <div className="mt-2 flex h-3 overflow-hidden rounded-full bg-ink-900/5">
                {stats.riskDist.critical > 0 && (
                  <div
                    className="bg-red-500 transition-all duration-300"
                    style={{ width: `${(stats.riskDist.critical / stats.totalCases) * 100}%` }}
                    title={`Critical: ${stats.riskDist.critical}`}
                  />
                )}
                {stats.riskDist.high > 0 && (
                  <div
                    className="bg-orange-500 transition-all duration-300"
                    style={{ width: `${(stats.riskDist.high / stats.totalCases) * 100}%` }}
                    title={`High: ${stats.riskDist.high}`}
                  />
                )}
                {stats.riskDist.medium > 0 && (
                  <div
                    className="bg-amber-400 transition-all duration-300"
                    style={{ width: `${(stats.riskDist.medium / stats.totalCases) * 100}%` }}
                    title={`Medium: ${stats.riskDist.medium}`}
                  />
                )}
                {stats.riskDist.low > 0 && (
                  <div
                    className="bg-signal-500 transition-all duration-300"
                    style={{ width: `${(stats.riskDist.low / stats.totalCases) * 100}%` }}
                    title={`Low: ${stats.riskDist.low}`}
                  />
                )}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-500">
                <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-red-500" />Critical {stats.riskDist.critical}</span>
                <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-orange-500" />High {stats.riskDist.high}</span>
                <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-amber-400" />Medium {stats.riskDist.medium}</span>
                <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-signal-500" />Low {stats.riskDist.low}</span>
              </div>
            </div>

            {/* Pending review + recent activity */}
            <div className="flex items-center gap-6 border-t border-ink-900/8 pt-4 md:border-l md:border-t-0 md:pl-6 md:pt-0">
              <div className="text-center">
                <p className="font-display text-2xl font-semibold text-ink-900">{stats.pendingFindings}</p>
                <p className="text-[11px] text-ink-500">待审阅 findings</p>
                {stats.pendingReview > 0 && (
                  <p className="text-[10px] text-ink-500">分布在 {stats.pendingReview} 个 case</p>
                )}
              </div>
              <div className="h-8 w-px bg-ink-900/10" aria-hidden="true" />
              <div className="text-center">
                <p className="font-display text-2xl font-semibold text-ink-900">{stats.recentCount}</p>
                <p className="text-[11px] text-ink-500">近 7 天新增</p>
              </div>
            </div>
          </div>
        </div>
      )}

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
                    <p className="mt-4 text-center text-sm text-ink-500">无</p>
                  ) : (
                    <div className="mt-2 divide-y divide-ink-900/8">
                      {items.map((item) => (
                        <CaseCard
                          key={item.case_id}
                          item={item}
                          onSelect={onSelectCase}
                          isSelected={selectedCaseId === item.case_id}
                          isAdmin={isAdmin}
                          onDeleteCase={setDeleteTarget}
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

      {/* Delete confirmation dialog */}
      {deleteTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="关闭删除确认"
            onClick={() => !deleteLoading && setDeleteTarget(null)}
            disabled={deleteLoading}
            tabIndex={-1}
          />
          <div ref={dialogRef} className="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="delete-case-title">
            <h3 id="delete-case-title" className="mb-3 font-display text-lg font-semibold text-ink-900">确认删除</h3>
            <p className="mb-4 text-sm text-ink-500">
              确定要删除 case <strong className="text-ink-900">{deleteTarget.case_id}</strong>（{deleteTarget.paper_title || '未命名项目'}）吗？此操作不可撤销。
            </p>
            {deleteError ? (
              <div className="mb-4 rounded-xl border border-red-300/50 bg-red-50/70 px-3 py-2 text-sm text-red-700" role="alert" aria-live="polite">{deleteError}</div>
            ) : null}
            <div className="flex justify-end gap-2">
              <button ref={cancelBtnRef} type="button" className="btn-ghost" onClick={() => setDeleteTarget(null)} disabled={deleteLoading}>取消</button>
              <button type="button" className="btn-danger" onClick={handleConfirmDelete} disabled={deleteLoading}>
                {deleteLoading ? '删除中…' : '删除'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default CasesPage;
