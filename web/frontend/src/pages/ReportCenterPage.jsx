import { startTransition, useEffect, useMemo, useState } from 'react';
import { FiExternalLink, FiRefreshCw } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';
import { listArtifacts, reportHtmlUrl } from '../services/api.js';

function ReportCenterPage({ selectedCase }) {
  const [artifacts, setArtifacts] = useState([]);
  const [previewReloadKey, setPreviewReloadKey] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');

  const htmlArtifact = useMemo(
    () => artifacts.find((item) => item.artifact_id === 'final_html_report'),
    [artifacts],
  );
  const ready = Boolean(htmlArtifact?.exists);
  const reportUrl = selectedCase ? reportHtmlUrl(selectedCase.case_id) : '#';

  useEffect(() => {
    if (!selectedCase) {
      setArtifacts([]);
      setError('');
      return undefined;
    }

    let cancelled = false;

    async function refreshArtifacts() {
      setIsRefreshing(true);
      try {
        const payload = await listArtifacts(selectedCase.case_id);
        if (cancelled) return;
        startTransition(() => {
          setArtifacts(payload.artifacts || []);
          setError('');
        });
      } catch (nextError) {
        if (!cancelled) setError(nextError.message || String(nextError));
      } finally {
        if (!cancelled) setIsRefreshing(false);
      }
    }

    refreshArtifacts();

    return () => {
      cancelled = true;
    };
  }, [selectedCase]);

  async function refreshStatus() {
    if (!selectedCase) return;
    setIsRefreshing(true);
    try {
      const payload = await listArtifacts(selectedCase.case_id);
      startTransition(() => {
        setArtifacts(payload.artifacts || []);
        setError('');
      });
    } catch (nextError) {
      setError(nextError.message || String(nextError));
    } finally {
      setIsRefreshing(false);
    }
  }

  function reloadPreview() {
    setPreviewReloadKey((current) => current + 1);
  }

  if (!selectedCase) {
    return <ReportCaseRequired />;
  }

  return (
    <div className="space-y-6">
      <ReportHero
        artifact={htmlArtifact}
        isRefreshing={isRefreshing}
        ready={ready}
        reportUrl={reportUrl}
        onRefreshStatus={refreshStatus}
        onReloadPreview={reloadPreview}
        error={error}
      />

      {ready ? (
        <ReadyReportPreview caseId={selectedCase.case_id} reloadKey={previewReloadKey} reportUrl={reportUrl} />
      ) : (
        <WaitingReportPreview />
      )}
    </div>
  );
}

function ReportCaseRequired() {
  return (
    <section className="dossier-panel rounded-[2rem] p-8 text-center">
      <p className="font-display text-2xl font-semibold">请先选择 Case</p>
      <p className="mt-3 text-sm text-ink-500">报告预览依赖当前 case 的 `final_audit_report.html`。</p>
    </section>
  );
}

function ReportHero({ artifact, isRefreshing, ready, reportUrl, onRefreshStatus, onReloadPreview, error }) {
  return (
    <section className="dossier-panel rounded-[2rem] p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="metric-label">Final HTML Report</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h2 className="section-title">最终审查报告</h2>
            <StatusPill tone={ready ? 'ok' : 'neutral'}>{ready ? 'ready' : 'waiting'}</StatusPill>
          </div>
          <ReportMetadata artifact={artifact} />
        </div>

        <ReportActions
          isRefreshing={isRefreshing}
          ready={ready}
          reportUrl={reportUrl}
          onRefreshStatus={onRefreshStatus}
          onReloadPreview={onReloadPreview}
        />
      </div>

      {error ? (
        <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700" role="alert">
          {error}
        </div>
      ) : null}
    </section>
  );
}

function ReportMetadata({ artifact }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <span className="mono-chip">{artifact?.path || 'final_audit_report.html'}</span>
      <span className="mono-chip">size: {formatBytes(artifact?.size_bytes)}</span>
      <span className="mono-chip">updated: {artifact?.updated_at || '-'}</span>
    </div>
  );
}

function ReportActions({ isRefreshing, ready, reportUrl, onRefreshStatus, onReloadPreview }) {
  return (
    <div className="flex flex-wrap gap-3">
      <button type="button" className="btn-secondary" onClick={onRefreshStatus} disabled={isRefreshing}>
        <FiRefreshCw aria-hidden="true" />
        {isRefreshing ? '刷新中' : '刷新状态'}
      </button>
      <button type="button" className="btn-secondary" onClick={onReloadPreview} disabled={!ready}>
        重新加载预览
      </button>
      <a className={`btn-primary ${ready ? '' : 'pointer-events-none opacity-50'}`} href={reportUrl} target="_blank" rel="noreferrer">
        <FiExternalLink aria-hidden="true" />
        新窗口打开
      </a>
    </div>
  );
}

function ReadyReportPreview({ caseId, reloadKey, reportUrl }) {
  return (
    <section className="dossier-panel overflow-hidden rounded-[2rem]">
      <iframe
        key={`${caseId}-${reloadKey}`}
        title="Veritas final audit report"
        src={reportUrl}
        loading="lazy"
        sandbox="allow-same-origin allow-popups allow-top-navigation-by-user-activation"
        className="h-[78vh] w-full bg-white [content-visibility:auto] [contain-intrinsic-size:900px]"
      />
    </section>
  );
}

function WaitingReportPreview() {
  return (
    <section className="dossier-panel overflow-hidden rounded-[2rem]">
      <div className="p-10 text-center">
        <p className="font-display text-2xl font-semibold">报告尚未生成</p>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-ink-500">
          请在 Mission Control 等待运行完成。HTML 报告一旦出现，这里会以内嵌方式打开同一个后端产物。
        </p>
      </div>
    </section>
  );
}

function formatBytes(value) {
  if (typeof value !== 'number') return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default ReportCenterPage;
