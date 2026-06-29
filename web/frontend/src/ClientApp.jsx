import { useState, useEffect, useRef } from 'react';
import ClientLayout from './layouts/ClientLayout.jsx';
import { parseClientWorkspace, writeClientWorkspace } from './utils/clientWorkspace.js';

// Lazy load client pages
import SubmitPage from './pages/client/SubmitPage.jsx';
import ProgressPage from './pages/client/ProgressPage.jsx';
import ReportPage from './pages/client/ReportPage.jsx';
import IssuePage from './pages/client/IssuePage.jsx';
import ReverificationPage from './pages/client/ReverificationPage.jsx';
import VerifyPage from './pages/client/VerifyPage.jsx';

function ClientApp() {
  const [workspace, setWorkspace] = useState(parseClientWorkspace());
  const mainRef = useRef(null);

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
    writeClientWorkspace(newWorkspace);
    setWorkspace(newWorkspace);
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
      {renderPage()}
    </ClientLayout>
  );
}

export default ClientApp;
