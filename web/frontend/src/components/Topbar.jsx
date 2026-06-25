import { useEffect, useRef, useState } from 'react';
import { FaSignOutAlt, FaUser } from 'react-icons/fa';
import { FiExternalLink, FiRefreshCw } from 'react-icons/fi';
import StatusPill from './StatusPill.jsx';
import { reportHtmlUrl } from '../services/api.js';
import { translateStatus } from '../utils/piLabels.js';

function Topbar({ selectedCase, selectedRunId, onRefresh, currentUser, onLogout }) {
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const logoutRef = useRef(null);

  useEffect(() => {
    if (!showLogoutConfirm) return;
    function handleClickOutside(e) {
      if (logoutRef.current && !logoutRef.current.contains(e.target)) {
        setShowLogoutConfirm(false);
      }
    }
    function handleEscape(e) {
      if (e.key === 'Escape') setShowLogoutConfirm(false);
    }
    document.addEventListener('click', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('click', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [showLogoutConfirm]);
  return (
    <header className="mb-6 flex flex-col gap-4 border-b border-ink-900/10 pb-5 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <p className="metric-label">当前审查项目</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="min-w-0 break-words font-display text-3xl font-semibold tracking-tight text-ink-900">
            {selectedCase?.paper_title || selectedCase?.case_id || '未选择审查项目'}
          </h1>
          {selectedCase ? <StatusPill>{translateStatus(selectedCase.status)}</StatusPill> : null}
        </div>
        <p className="mt-2 font-mono text-xs text-ink-500">
          {selectedCase ? selectedCase.case_id : '创建或选择一个审查项目'}
          {selectedRunId ? ` / 运行 ${selectedRunId.length > 8 ? `${selectedRunId.slice(0, 8)}…` : selectedRunId}` : ''}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {currentUser ? (
          <div className="flex items-center gap-2 rounded-full border border-ink-900/10 bg-paper-50/80 px-3 py-1.5 text-sm text-ink-500">
            <FaUser className="text-xs text-ink-500" aria-hidden="true" />
            <span className="font-medium">{currentUser.username}</span>
          </div>
        ) : null}
        {onLogout ? (
          <div ref={logoutRef} className="relative">
            <button
              type="button"
              className="btn-ghost focus-visible:ring-2 focus-visible:ring-ink-500 focus-visible:ring-offset-2"
              onClick={() => setShowLogoutConfirm((v) => !v)}
              title="登出当前用户"
            >
              <FaSignOutAlt aria-hidden="true" />
              登出
            </button>
            {showLogoutConfirm && (
              <div className="absolute right-0 top-full z-20 mt-2 w-48 rounded-xl border border-ink-900/10 bg-paper-50 p-3 shadow-lg">
                <p className="text-sm text-ink-700">确定登出？</p>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    className="flex-1 rounded-lg bg-ink-900 px-3 py-1.5 text-xs font-semibold text-paper-50 hover:bg-ink-700"
                    onClick={() => { onLogout(); setShowLogoutConfirm(false); }}
                  >
                    确定
                  </button>
                  <button
                    type="button"
                    className="flex-1 rounded-lg border border-ink-900/10 px-3 py-1.5 text-xs font-semibold text-ink-500 hover:bg-ink-900/5"
                    onClick={() => setShowLogoutConfirm(false)}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : null}
        <button type="button" className="btn-secondary" onClick={onRefresh}>
          <FiRefreshCw aria-hidden="true" />
          刷新
        </button>
        <a
          className={`btn-primary ${selectedCase ? '' : 'pointer-events-none opacity-50'}`}
          href={selectedCase ? reportHtmlUrl(selectedCase.case_id) : '#'}
          target="_blank"
          rel="noreferrer"
          {...(!selectedCase ? { 'aria-disabled': 'true' } : {})}
        >
          <FiExternalLink aria-hidden="true" />
          打开 HTML 报告
        </a>
      </div>
    </header>
  );
}

export default Topbar;
