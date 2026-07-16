import { lazy } from 'react';
import LoadingFallback from './components/LoadingFallback.jsx';
import { SuspenseReveal } from './components/ViewTransitions.jsx';
import { detectEntry } from './utils/entrypoint.js';

const VerifyPage = lazy(() => import('./pages/VerifyPage.jsx'));
const ClientApp = lazy(() => import('./ClientApp.jsx'));
const AdminApp = lazy(() => import('./AdminApp.jsx'));

function App() {
  const entry = detectEntry();
  if (entry === 'verify') {
    return (
      <SuspenseReveal fallback={<LoadingFallback />}>
        <VerifyPage />
      </SuspenseReveal>
    );
  }
  if (entry === 'ops') {
    return (
      <SuspenseReveal fallback={<LoadingFallback />}>
        <AdminApp />
      </SuspenseReveal>
    );
  }
  return (
    <SuspenseReveal fallback={<LoadingFallback />}>
      <ClientApp />
    </SuspenseReveal>
  );
}

export default App;
