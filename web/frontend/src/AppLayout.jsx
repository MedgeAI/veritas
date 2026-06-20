import { Suspense, lazy, startTransition, useEffect, useMemo, useState } from 'react';
import Sidebar from './components/Sidebar.jsx';
import Topbar from './components/Topbar.jsx';
import LoadingFallback from './components/LoadingFallback.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import { checkHealth, listCases } from './services/api.js';

const CasesPage = lazy(() => import('./pages/CasesPage.jsx'));
const NewAuditPage = lazy(() => import('./pages/NewAuditPage.jsx'));
const MissionControlPage = lazy(() => import('./pages/MissionControlPage.jsx'));
const EvidenceWorkspacePage = lazy(() => import('./pages/EvidenceWorkspacePage.jsx'));
const ReportCenterPage = lazy(() => import('./pages/ReportCenterPage.jsx'));
const VisualForensicsPage = lazy(() => import('./pages/VisualForensicsPage.jsx'));
const InvestigationBoardPage = lazy(() => import('./pages/InvestigationBoardPage.jsx'));
const ReviewQueuePage = lazy(() => import('./pages/ReviewQueuePage.jsx'));
const CBIRSearchPage = lazy(() => import('./pages/CBIRSearchPage.jsx'));
const PlaceholderPage = lazy(() => import('./pages/PlaceholderPage.jsx'));

const PAGE_META = {
  cases: ['Cases', '管理审查档案、恢复最近一次任务上下文。'],
  newAudit: ['New Audit', '创建 case、上传论文材料、启动真实 audit-paper 流程。'],
  mission: ['Mission Control', '观察当前运行状态、进度事件和失败节点。'],
  evidence: ['Evidence Workspace', '读取结构化产物，包括 manifest、bundle、investigation rounds。'],
  visual: ['Visual Forensics Gallery', '图像取证候选、VLM 初筛与人工复核入口。'],
  investigation: ['Investigation Board', 'Agent 选择确定性工具后的调查轨迹。'],
  review: ['Review Queue', '人工复核队列，不让模型直接给最终诚信判定。'],
  cbir: ['CBIR Search', '通过 Panel ID 或图片上传搜索相似 panel。'],
  report: ['Report Center', '预览并打开最终 HTML 报告。'],
  advanced: ['Advanced Lab', '预留 pdf-extractor、panel-extractor、copy-move 与 CBIR 服务。'],
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
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  } catch {
    return;
  }
}

function AppLayout() {
  // 默认打开 New Audit 页面（ChatGPT 模式：聚焦"开始新任务"）
  const urlWorkspace = workspaceFromUrl();
  const [activePage, setActivePage] = useState(urlWorkspace?.activePage || 'newAudit');
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

  async function refreshCases() {
    try {
      const payload = await listCases();
      setCases(payload.cases || []);
      setLoadError('');
    } catch (error) {
      setLoadError(error.message || String(error));
    }
  }

  async function refreshBackendHealth() {
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
  }

  useEffect(() => {
    refreshCases();
    refreshBackendHealth();
    const timer = window.setInterval(refreshBackendHealth, 5000);
    function handlePopState() {
      const nextWorkspace = workspaceFromUrl();
      if (!nextWorkspace) return;
      startTransition(() => {
        setActivePage(nextWorkspace.activePage);
        setSelectedCaseId(nextWorkspace.caseId);
        setSelectedRunId(nextWorkspace.runId);
      });
    }
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

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
      setSelectedRunId(runRecord.run_id);
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
        return <CasesPage {...shared} />;
      case 'newAudit':
        return <NewAuditPage {...shared} onCaseCreated={handleCaseCreated} onRunStarted={handleRunStarted} />;
      case 'mission':
        return <MissionControlPage {...shared} />;
      case 'evidence':
        return <EvidenceWorkspacePage {...shared} />;
      case 'report':
        return <ReportCenterPage {...shared} />;
      case 'visual':
        return <VisualForensicsPage {...shared} />;
      case 'investigation':
        return <InvestigationBoardPage {...shared} />;
      case 'review':
        return <ReviewQueuePage {...shared} />;
      case 'cbir':
        return <CBIRSearchPage {...shared} />;
      case 'advanced':
        return (
          <PlaceholderPage
            title={PAGE_META.advanced[0]}
            body={PAGE_META.advanced[1]}
            lanes={['pdf-extractor', 'panel-extractor', 'copy-move-detection-keypoint', 'cbir-service + Milvus']}
          />
        );
      default:
        return <CasesPage {...shared} />;
    }
  }

  const [pageTitle, pageSubtitle] = PAGE_META[activePage] || PAGE_META.cases;

  return (
    <div className="audit-shell min-h-screen lg:flex">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>
      <Sidebar
        activePage={activePage}
        onNavigate={navigate}
        cases={cases}
        selectedCaseId={selectedCaseId}
        onSelectCase={selectCase}
        caseCount={cases.length}
      />

      <main id="main-content" className="min-w-0 flex-1 px-4 py-4 sm:px-6 lg:px-8 lg:py-6">
        <Topbar selectedCase={selectedCase} selectedRunId={selectedRunId} onRefresh={refreshCases} />

        <div className="mb-5 flex flex-col gap-3 lg:hidden">
          <select className="input-field" name="mobile_page" aria-label="切换页面" value={activePage} onChange={(event) => navigate(event.target.value)}>
            {Object.entries(PAGE_META).map(([key, [label]]) => (
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
          <p className="metric-label">{pageTitle}</p>
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
