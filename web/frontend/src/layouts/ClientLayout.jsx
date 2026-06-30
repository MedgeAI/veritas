import { useEffect, useState } from 'react';
import { getCurrentUser } from '../services/api.js';
import LoginPage from '../pages/LoginPage.jsx';
import ClientHeader from '../components/ClientHeader.jsx';
import ClientFooter from '../components/ClientFooter.jsx';

/**
 * 客户门户布局
 *
 * 职责：
 * 1. Auth gate: 检查登录状态，未登录显示 LoginPage
 * 2. 结构：ClientHeader + <main>{children}</main> + ClientFooter
 * 3. 不包含 Sidebar、Topbar、case 列表、后台健康告警
 *
 * Props:
 * - activeTab: 当前激活的 tab
 * - onTabChange: tab 切换回调
 * - children: 页面内容
 */
export default function ClientLayout({ activeTab, onTabChange, children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function checkAuth() {
      try {
        // getCurrentUser returns null on 401, throws on network error
        const currentUser = await getCurrentUser();
        if (mounted) {
          setUser(currentUser); // null = not logged in
        }
      } catch {
        // Network error or server unavailable — treat as not logged in
        if (mounted) {
          setUser(null);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    checkAuth();

    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-paper-50 flex items-center justify-center">
        <div role="status" aria-live="polite" className="text-ink-900 font-display text-2xl italic">Loading…</div>
      </div>
    );
  }

  if (!user) {
    return <LoginPage onLogin={setUser} />;
  }

  return (
    <div className="min-h-screen bg-paper-50">
      <ClientHeader activeTab={activeTab} onTabChange={onTabChange} />
      <main id="main-content" className="max-w-[980px] mx-auto pt-16 px-14 pb-25">
        {children}
      </main>
      <ClientFooter />
    </div>
  );
}
