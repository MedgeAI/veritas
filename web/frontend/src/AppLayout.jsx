import { Suspense, lazy, startTransition, useCallback, useEffect, useMemo, useState } from 'react';
import Sidebar from './components/Sidebar.jsx';
import Topbar from './components/Topbar.jsx';
import LoadingFallback from './components/LoadingFallback.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import { checkHealth, clearAuthCredentials, getCurrentUser, listCases } from './services/api.js';

const LoginPage = lazy(() => import('./pages/LoginPage.jsx'));
const CasesPage = lazy(() => import('./pages/CasesPage.jsx'));
const NewAuditPage = lazy(() => import('./pages/NewAuditPage.jsx'));
const MissionControlPage = lazy(() => import('./pages/MissionControlPage.jsx'));
const ReportCenterPage = lazy(() => import('./pages/ReportCenterPage.jsx'));
const FindingsPage = lazy(() => import('./pages/FindingsPage.jsx'));
const EvidenceReviewPage = lazy(() => import('./pages/EvidenceReviewPage.jsx'));
const ActionsPage = lazy(() => import('./pages/ActionsPage.jsx'));
const AdminPage = lazy(() => import('./pages/AdminPage.jsx'));
const ReverificationPage = lazy(() => import('./pages/ReverificationPage.jsx'));
const VerifyPage = lazy(() => import('./pages/VerifyPage.jsx'));

const ALWAYS_AVAILABLE_PAGES = new Set(['cases', 'newAudit']);

const PAGE_META = {
  cases: ['Dashboard', '按风险等级分组的审查看板，快速定位需要关注的 case。'],
  newAudit: ['新建审查', '创建 case、上传论文材料、启动审查流程。'],
  mission: ['运行监控', '观察当前运行状态、进度事件和失败节点。'],
  report: ['审查报告', '预览并打开最终 HTML 报告。'],
  findings: ['审查发现', '风险概览与高危发现，快速判断论文需要关注的重点。'],
  evidence: ['证据审查', '图像取证、相似 Panel 搜索与可视化证据分析。'],
  actions: ['行动项', '待复核发现、材料补交与追问清单。'],
  reverification: ['重新核查', '修订版增量复核，版本链路追踪。'],
  verify: ['公开验证', '输入报告编号，查证认证真伪。'],
  admin: ['用户管理', '管理系统用户、角色和权限。'],
};

function workspaceFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const activePage = params.get('page') || '';
    const caseId = params.get('case') || '';
    const runId = params.get('run') || '';
    if (!activePage && !caseId && !runId) return null;
    return {
      activePage: PAGE_META[activePage] ? activePage : 'cases',
      caseId,
      runId,
    };
  } catch {
    return null;
  }
}

function writeWorkspaceUrl(value) {
  try {
    const url = new URL(window.location.href);
    if (value.activePage && value.activePage !== 'cases') {
      url.searchParams.set('page', value.activePage);
    } else {
      url.searchParams.delete('page');
    }
    if (value.caseId) url.searchParams.set('case', value.caseId);
    else url.searchParams.delete('case');
    if (value.runId) url.searchParams.set('run', value.runId);
    else url.searchParams.delete('run');
    window.history.pushState(null, '', `${url.pathname}${url.search}${url.hash}`);
  } catch {
    return;
  }
}

function AppLayout() {
  // Auth state
  const [authState, setAuthState] = useState({ checked: false, user: null, isAdmin: false });
  const [authChecking, setAuthChecking] = useState(true);

  // 默认打开 Dashboard（待办看板）
  const urlWorkspace = workspaceFromUrl();
  const [activePage, setActivePage] = useState(urlWorkspace?.activePage || 'cases');
  const [cases, setCases] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState(urlWorkspace?.caseId || '');
  const [selectedRunId, setSelectedRunId] = useState(urlWorkspace?.runId || '');
  const [loadError, setLoadError] = useState('');
  const [workspaceNotice, setWorkspaceNotice] = useState(() => {
    if (!urlWorkspace?.caseId && !urlWorkspace?.runId) return null;
    return {
      tone: 'neutral',
      title: '已打开链接中的工作区',
      detail: `恢复的是 case/run 选择，不代表任务仍在执行。case=${urlWorkspace?.caseId || '-'} run=${urlWorkspace?.runId || '-'}`,
      dismissible: true,
    };
  });
  const [backendHealth, setBackendHealth] = useState({
    online: true,
    detail: '',
    recoveredInterruptedRuns: 0,
  });

  const selectedCase = useMemo(
    () => cases.find((item) => item.case_id === selectedCaseId) || null,
    [cases, selectedCaseId],
  );

  const refreshCases = useCallback(async () => {
    try {
      const payload = await listCases();
      setCases(payload.cases || []);
      setLoadError('');
    } catch (error) {
      setLoadError(error.message || String(error));
    }
  }, []);

  const refreshBackendHealth = useCallback(async () => {
    try {
      const payload = await checkHealth();
      setBackendHealth({
        online: true,
        detail: '',
        recoveredInterruptedRuns: Number(payload.recovered_interrupted_runs || 0),
      });
    } catch (error) {
      setBackendHealth({
        online: false,
        detail: error.message || String(error),
        recoveredInterruptedRuns: 0,
      });
    }
  }, []);

  // Auth check on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const user = await getCurrentUser();
        if (cancelled) return;
        if (!user) {
          setAuthState({ checked: true, user: null, isAdmin: false });
          setAuthChecking(false);
          return;
        }
        // /api/me returns is_admin directly
        setAuthState({ checked: true, user, isAdmin: user.isAdmin || false });
      } catch {
        if (!cancelled) setAuthState({ checked: true, user: null, isAdmin: false });
      } finally {
        if (!cancelled) setAuthChecking(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authState.user) return;
    refreshCases();
    refreshBackendHealth();
    const timer = window.setInterval(refreshBackendHealth, 15_000);

    function handleVisibility() {
      if (document.visibilityState === 'visible') {
        refreshBackendHealth();
      }
    }

    function handlePopState() {
      const nextWorkspace = workspaceFromUrl();
      if (!nextWorkspace) return;
      startTransition(() => {
        setActivePage(nextWorkspace.activePage);
        setSelectedCaseId(nextWorkspace.caseId);
        setSelectedRunId(nextWorkspace.runId);
      });
    }

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('popstate', handlePopState);
    };
  }, [refreshCases, refreshBackendHealth, authState.user]);

  useEffect(() => {
    const workspace = {
      activePage,
      caseId: selectedCaseId,
      runId: selectedRunId,
    };
    writeWorkspaceUrl(workspace);
  }, [activePage, selectedCaseId, selectedRunId]);

  useEffect(() => {
    if (!cases.length || !selectedCaseId) return;
    const nextCase = cases.find((item) => item.case_id === selectedCaseId);
    if (!nextCase) {
      setSelectedCaseId('');
      setSelectedRunId('');
      setWorkspaceNotice({
        tone: 'warning',
        title: '上次工作区已失效',
        detail: `本地记录的 case=${selectedCaseId} 在当前 backend store 中不存在，已清空选择。`,
        dismissible: true,
      });
      return;
    }

    if (selectedRunId && nextCase.latest_run_id && selectedRunId !== nextCase.latest_run_id) {
      setWorkspaceNotice({
        tone: 'warning',
        title: '已恢复上次工作区',
        detail: `当前 case 的最新 run 是 ${nextCase.latest_run_id}。localStorage 中的 run=${selectedRunId} 只是上次打开的选择，请以 Mission Control 查询结果为准。`,
        dismissible: true,
      });
    }
  }, [cases, selectedCaseId, selectedRunId]);

  function selectCase(caseId) {
    const nextCase = cases.find((item) => item.case_id === caseId);
    startTransition(() => {
      setSelectedCaseId(caseId);
      setSelectedRunId(nextCase?.latest_run_id || '');
      // 从 cases 页面进入 → 跳转到 mission；否则保持当前页面，只切换 case 数据
      setActivePage((current) => (current === 'cases' ? 'mission' : current));
    });
    setWorkspaceNotice(null);
  }

  function handleCaseCreated(caseRecord) {
    setCases((current) => {
      const rest = current.filter((item) => item.case_id !== caseRecord.case_id);
      return [caseRecord, ...rest];
    });
    setSelectedCaseId(caseRecord.case_id);
    setSelectedRunId(caseRecord.latest_run_id || '');
    setWorkspaceNotice(null);
  }

  function handleRunStarted(runRecord) {
    startTransition(() => {
      setSelectedRunId(runRecord.job_id);
      setActivePage('mission');
    });
    setWorkspaceNotice(null);
    refreshCases();
  }

  function navigate(page) {
    startTransition(() => {
      setActivePage(PAGE_META[page] ? page : 'cases');
    });
  }

  function handleLogin(user) {
    // /api/me already returns isAdmin from Cloudflare provider
    setAuthState({ checked: true, user, isAdmin: user.isAdmin || false });
  }

  function handleLogout() {
    clearAuthCredentials();
    setAuthState({ checked: true, user: null, isAdmin: false });
    setCases([]);
    setSelectedCaseId('');
    setSelectedRunId('');
  }

  function renderActivePage() {
    const shared = {
      cases,
      selectedCase,
      selectedCaseId,
      selectedRunId,
      onSelectCase: selectCase,
      onSelectRun: setSelectedRunId,
      onRefreshCases: refreshCases,
      onNavigate: navigate,
    };

    switch (activePage) {
      case 'cases':
        return <CasesPage {...shared} isAdmin={authState.isAdmin} />;
      case 'newAudit':
        return <NewAuditPage {...shared} onCaseCreated={handleCaseCreated} onRunStarted={handleRunStarted} />;
      case 'mission':
        return <MissionControlPage {...shared} />;
      case 'report':
        return <ReportCenterPage {...shared} />;
      case 'findings':
        return <FindingsPage {...shared} />;
      case 'evidence':
        return <EvidenceReviewPage {...shared} />;
      case 'actions':
        return <ActionsPage {...shared} />;
      case 'reverification':
        return <ReverificationPage {...shared} />;
      case 'admin':
        return authState.isAdmin ? <AdminPage /> : <CasesPage {...shared} isAdmin={false} />;
      default:
        return <CasesPage {...shared} isAdmin={authState.isAdmin} />;
    }
  }

  const [pageTitle, pageSubtitle] = PAGE_META[activePage] || PAGE_META.cases;

  // Public verification page: no auth required, no sidebar/topbar
  if (activePage === 'verify') {
    return (
      <Suspense fallback={<LoadingFallback />}>
        <VerifyPage />
      </Suspense>
    );
  }

  // Auth gate: show login page when not authenticated
  if (authChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingFallback />
      </div>
    );
  }

  if (!authState.user) {
    return (
      <Suspense fallback={<LoadingFallback />}>
        <LoginPage onLogin={handleLogin} />
      </Suspense>
    );
  }

  return (
    <div className="audit-shell h-screen overflow-hidden lg:flex">
      <Sidebar
        activePage={activePage}
        onNavigate={navigate}
        cases={cases}
        selectedCaseId={selectedCaseId}
        onSelectCase={selectCase}
        caseCount={cases.length}
        isAdmin={authState.isAdmin}
        alwaysAvailablePages={ALWAYS_AVAILABLE_PAGES}
      />

      <main id="main-content" className="min-w-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 lg:px-8 lg:py-6">
        <Topbar
          selectedCase={selectedCase}
          selectedRunId={selectedRunId}
          onRefresh={refreshCases}
          currentUser={authState.user}
          onLogout={handleLogout}
        />

        <div className="mb-5 flex flex-col gap-3 lg:hidden">
          <select className="input-field" name="mobile_page" aria-label={`当前页面：${pageTitle}，点击切换导航页面`} value={activePage} onChange={(event) => navigate(event.target.value)} autoComplete="off">
            {Object.entries(PAGE_META).filter(([key]) => key !== 'admin' || authState.isAdmin).map(([key, [label]]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {loadError ? (
          <div className="mb-5 rounded-2xl border border-risk-300/40 bg-risk-100/65 p-4 text-sm text-risk-700" role="status" aria-live="polite">
            Backend 连接失败：{loadError}
          </div>
        ) : null}

        {!backendHealth.online ? (
          <div className="mb-5 rounded-2xl border border-risk-300/40 bg-risk-100/75 p-4 text-sm leading-6 text-risk-700" role="status" aria-live="polite">
            <strong>Backend 已断开。</strong>
            当前页面仍可查看已缓存的界面状态，但无法继续刷新任务进度。当前 thread runner 模式下，backend 进程退出会中断正在执行的审查；重启后该 run 会被标记为 interrupted。
            {backendHealth.detail ? <span className="mt-1 block font-mono text-xs">{backendHealth.detail}</span> : null}
          </div>
        ) : backendHealth.recoveredInterruptedRuns > 0 ? (
          <div className="mb-5 rounded-2xl border border-caution-300/50 bg-caution-100/70 p-4 text-sm leading-6 text-caution-700" role="status" aria-live="polite">
            Backend 已恢复 {backendHealth.recoveredInterruptedRuns} 个重启前遗留的 running/queued 任务，并标记为 interrupted。请在 Mission Control 查看 `runner_interrupted` 事件后重新发起新 run。
          </div>
        ) : null}

        {workspaceNotice ? (
          <div
            className={`mb-5 rounded-2xl border p-4 text-sm leading-6 ${
              workspaceNotice.tone === 'warning'
                ? 'border-caution-300/50 bg-caution-100/70 text-caution-700'
                : 'border-ink-900/10 bg-white/65 text-ink-500'
            }`}
            role="status"
            aria-live="polite"
          >
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <strong className="text-ink-900">{workspaceNotice.title}</strong>
                <span className="mt-1 block">{workspaceNotice.detail}</span>
              </div>
              {workspaceNotice.dismissible ? (
                <button type="button" className="btn-ghost shrink-0" onClick={() => setWorkspaceNotice(null)}>
                  知道了
                </button>
              ) : null}
            </div>
          </div>
        ) : null}

        <section className="mb-6">
          <h2 className="metric-label">{pageTitle}</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-500">{pageSubtitle}</p>
        </section>

        <ErrorBoundary>
          <Suspense fallback={<LoadingFallback />}>
            <div className="animate-rise-in">{renderActivePage()}</div>
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default AppLayout;
