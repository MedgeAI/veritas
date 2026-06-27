import { lazy, Suspense } from 'react';
import AppLayout from './AppLayout.jsx';
import LoadingFallback from './components/LoadingFallback.jsx';

const VerifyPage = lazy(() => import('./pages/VerifyPage.jsx'));

function App() {
  // Check if current path is /verify — render standalone page without AppLayout
  if (window.location.pathname === '/verify') {
    return (
      <Suspense fallback={<LoadingFallback />}>
        <VerifyPage />
      </Suspense>
    );
  }

  return <AppLayout />;
}

export default App;
