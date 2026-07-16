import { lazy, startTransition, useState, useEffect } from 'react';
import ClientLayout from './layouts/ClientLayout.jsx';
import { parseClientWorkspace, writeClientWorkspace } from './utils/clientWorkspace.js';
import LoadingFallback from './components/LoadingFallback.jsx';
import { PageViewTransition, SuspenseReveal } from './components/ViewTransitions.jsx';
import { markNavigationTransition } from './utils/viewTransitions.js';

// Lazy load client pages — only the active tab is needed per session,
// so deferring the others cuts first-paint bundle by ~50-65 KB.
const SubmitPage = lazy(() => import('./pages/client/SubmitPage.jsx'));
const ProgressPage = lazy(() => import('./pages/client/ProgressPage.jsx'));
const ReportPage = lazy(() => import('./pages/client/ReportPage.jsx'));
const IssuePage = lazy(() => import('./pages/client/IssuePage.jsx'));
const ReverificationPage = lazy(() => import('./pages/client/ReverificationPage.jsx'));
const VerifyPage = lazy(() => import('./pages/client/VerifyPage.jsx'));

function classifyClientNavigation(currentTab, nextTab) {
  if (currentTab === 'report' && nextTab === 'issue') return 'nav-forward';
  if (currentTab === 'issue' && nextTab === 'report') return 'nav-back';
  if (currentTab === 'submit' && nextTab === 'progress') return 'nav-forward';
  if (currentTab === 'progress' && nextTab === 'report') return 'nav-forward';
  if (currentTab === 'report' && nextTab === 'reverification') return 'nav-forward';
  if (currentTab === 'reverification' && nextTab === 'report') return 'nav-back';
  return 'nav-lateral';
}

function ClientApp() {
  const [workspace, setWorkspace] = useState(parseClientWorkspace());

  useEffect(() => {
    // Sync workspace state when URL changes
    const handlePopState = () => {
      setWorkspace(parseClientWorkspace());
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const handleTabChange = (tab, params = {}) => {
    const newWorkspace = { ...workspace, tab, ...params };
    const transitionType = classifyClientNavigation(workspace.tab, tab);
    startTransition(() => {
      markNavigationTransition(transitionType);
      writeClientWorkspace(newWorkspace);
      setWorkspace(newWorkspace);
    });
    // Move focus to main content on tab change
    requestAnimationFrame(() => {
      const main = document.getElementById('main-content');
      if (main) {
        main.setAttribute('tabindex', '-1');
        main.focus({ preventScroll: true });
      }
    });
  };

  const handleNavigate = (tab, params = {}) => {
    handleTabChange(tab, params);
  };

  const renderPage = () => {
    const { tab, case: caseId, run: runId, finding: findingId } = workspace;

    switch (tab) {
      case 'submit':
        return <SubmitPage caseId={caseId} onNavigate={handleNavigate} />;
      case 'progress':
        return <ProgressPage caseId={caseId} runId={runId} onNavigate={handleNavigate} />;
      case 'report':
        return <ReportPage caseId={caseId} onNavigate={handleNavigate} />;
      case 'issue':
        return <IssuePage caseId={caseId} findingId={findingId} onNavigate={handleNavigate} />;
      case 'reverification':
        return <ReverificationPage caseId={caseId} onNavigate={handleNavigate} />;
      case 'verify':
        return <VerifyPage />;
      default:
        return <SubmitPage caseId={caseId} onNavigate={handleNavigate} />;
    }
  };

  return (
    <ClientLayout activeTab={workspace.tab} onTabChange={handleTabChange}>
      <SuspenseReveal fallback={<LoadingFallback />}>
        <PageViewTransition key={`${workspace.tab}:${workspace.case}:${workspace.run}:${workspace.finding}`}>
          {renderPage()}
        </PageViewTransition>
      </SuspenseReveal>
    </ClientLayout>
  );
}

export default ClientApp;
