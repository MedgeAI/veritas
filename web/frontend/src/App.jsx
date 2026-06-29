import { lazy, Suspense } from 'react';
import AppLayout from './AppLayout.jsx';
import ClientLayout from './layouts/ClientLayout.jsx';
import LoadingFallback from './components/LoadingFallback.jsx';
import { detectEntry } from './utils/entrypoint.js';

const VerifyPage = lazy(() => import('./pages/VerifyPage.jsx'));
const ClientApp = lazy(() => import('./ClientApp.jsx'));

function App() {
  const entry = detectEntry();
  if (entry === 'verify') {
    return <Suspense fallback={<LoadingFallback />}><VerifyPage /></Suspense>;
  }
  if (entry === 'ops') {
    return <AppLayout />;
  }
  return <Suspense fallback={<LoadingFallback />}><ClientApp /></Suspense>;
}

export default App;
