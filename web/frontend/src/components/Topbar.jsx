import { FiExternalLink, FiRefreshCw } from 'react-icons/fi';
import StatusPill from './StatusPill.jsx';
import { reportHtmlUrl } from '../services/api.js';
import { translateStatus } from '../utils/piLabels.js';

function Topbar({ selectedCase, selectedRunId, onRefresh }) {
  return (
    <header className="mb-6 flex flex-col gap-4 border-b border-ink-900/10 pb-5 md:flex-row md:items-center md:justify-between">
      <div>
        <p className="metric-label">当前审查项目</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="font-display text-3xl font-semibold tracking-tight text-ink-900">
            {selectedCase?.paper_title || selectedCase?.case_id || '未选择审查项目'}
          </h1>
          {selectedCase ? <StatusPill>{translateStatus(selectedCase.status)}</StatusPill> : null}
        </div>
        <p className="mt-2 font-mono text-xs text-ink-300">
          {selectedCase ? selectedCase.case_id : '创建或选择一个审查项目'}
          {selectedRunId ? ` / 运行 ${selectedRunId.length > 8 ? `${selectedRunId.slice(0, 8)}...` : selectedRunId}` : ''}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn-secondary" onClick={onRefresh}>
          <FiRefreshCw aria-hidden="true" />
          刷新
        </button>
        <a
          className={`btn-primary ${selectedCase ? '' : 'pointer-events-none opacity-50'}`}
          href={selectedCase ? reportHtmlUrl(selectedCase.case_id) : '#'}
          target="_blank"
          rel="noreferrer"
        >
          <FiExternalLink aria-hidden="true" />
          打开 HTML 报告
        </a>
      </div>
    </header>
  );
}

export default Topbar;
