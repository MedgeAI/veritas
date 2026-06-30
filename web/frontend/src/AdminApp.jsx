import AppLayout from './AppLayout.jsx';
import LoadingFallback from './components/LoadingFallback.jsx';
import { SuspenseReveal } from './components/ViewTransitions.jsx';

/**
 * AdminApp — ops/auditor portal.
 *
 * Loaded only when detectEntry() resolves to 'ops'.  Owns AppLayout
 * (Sidebar + Topbar + admin routes).  Client users never load this
 * module, so admin-only components are tree-shaken out of the client
 * bundle.
 */
export default function AdminApp() {
  return (
    <SuspenseReveal fallback={<LoadingFallback />}>
      <AppLayout />
    </SuspenseReveal>
  );
}
