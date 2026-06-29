import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FiExternalLink, FiEye, FiEyeOff, FiRefreshCw } from 'react-icons/fi';
import GradeBadge from '../components/GradeBadge.jsx';
import StatusPill from '../components/StatusPill.jsx';
import { getRun, listArtifacts, reportHtmlUrl } from '../services/api.js';
import { friendlyError } from '../utils/piLabels.js';

function ReportCenterPage({ selectedCase }) {
  const [artifacts, setArtifacts] = useState([]);
  const [previewReloadKey, setPreviewReloadKey] = useState(0);
  const [gradeData, setGradeData] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [viewMode, setViewMode] = useState('author');
  const iframeRef = useRef(null);

  const injectViewMode = useCallback(
    (mode) => {
      const iframe = iframeRef.current;
      if (!iframe?.contentDocument) return;
      const doc = iframe.contentDocument;

      if (doc.body) {
        doc.body.setAttribute('data-view', mode);
      }

      let styleEl = doc.getElementById('view-mode-style');
      if (!styleEl) {
        styleEl = doc.createElement('style');
        styleEl.id = 'view-mode-style';
        doc.head.appendChild(styleEl);
      }

      if (mode === 'gatekeeper') {
        styleEl.textContent =
          '.author-only { display: none !important; } .gatekeeper-only { display: block !important; }';
      } else {
        styleEl.textContent =
          '.gatekeeper-only { display: none !important; } .author-only { display: block !important; }';
      }
    },
    [],
  );

  const handleIframeLoad = useCallback(() => {
    injectViewMode(viewMode);
  }, [viewMode, injectViewMode]);

  useEffect(() => {
    injectViewMode(viewMode);
  }, [viewMode, injectViewMode]);

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
      setGradeData(null);
      return undefined;
    }

    let cancelled = false;

    async function refreshArtifacts() {
      setIsRefreshing(true);
      try {
        const runId = selectedCase.latest_run_id;
        const [payload, runData] = await Promise.all([
          listArtifacts(selectedCase.case_id),
          runId ? getRun(selectedCase.case_id, runId).catch(() => null) : null,
        ]);
        if (cancelled) return;
        startTransition(() => {
          setArtifacts(payload.artifacts || []);
          setGradeData(runData?.summary?.certification_grade || null);
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
        gradeData={gradeData}
        isRefreshing={isRefreshing}
        ready={ready}
        reportUrl={reportUrl}
        onRefreshStatus={refreshStatus}
        onReloadPreview={reloadPreview}
        error={error}
      />

      {ready ? (
        <>
          <ViewModeToggle viewMode={viewMode} onViewModeChange={setViewMode} />
          <ReadyReportPreview
            caseId={selectedCase.case_id}
            reloadKey={previewReloadKey}
            reportUrl={reportUrl}
            viewMode={viewMode}
            iframeRef={iframeRef}
            onIframeLoad={handleIframeLoad}
          />
          <VersionHistorySection selectedCase={selectedCase} gradeData={gradeData} />
        </>
      ) : (
        <WaitingReportPreview />
      )}
    </div>
  );
}

function ReportCaseRequired() {
  return (
    <section className="dossier-panel rounded-2xl p-8 text-center">
      <p className="font-display text-2xl font-semibold">请先选择审查项目</p>
      <p className="mt-3 text-sm text-ink-500">报告预览依赖当前审查项目的最终报告</p>
    </section>
  );
}

function ReportHero({ artifact, gradeData, isRefreshing, ready, reportUrl, onRefreshStatus, onReloadPreview, error }) {
  return (
    <section className="dossier-panel rounded-2xl p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="metric-label">Final HTML Report</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h2 className="section-title">最终审查报告</h2>
            <StatusPill tone={ready ? 'ok' : 'neutral'}>{ready ? '已就绪' : '等待生成'}</StatusPill>
          </div>
          {gradeData ? (
            <div className="mt-4">
              <GradeBadge grade={gradeData.grade} dimensions={gradeData.dimensions} size="lg" />
            </div>
          ) : null}
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
          {friendlyError(error)}
        </div>
      ) : null}
    </section>
  );
}

function ReportMetadata({ artifact }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <span className="mono-chip">{artifact?.path || '最终审查报告'}</span>
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
        {isRefreshing ? '刷新中…' : '刷新状态'}
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

function ViewModeToggle({ viewMode, onViewModeChange }) {
  return (
    <div className="flex items-center gap-1 rounded-xl bg-ink-100/60 p-1">
      <button
        type="button"
        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
          viewMode === 'author'
            ? 'bg-white text-ink-900 shadow-sm'
            : 'text-ink-500 hover:text-ink-700'
        }`}
        onClick={() => onViewModeChange('author')}
        aria-pressed={viewMode === 'author'}
      >
        <FiEye aria-hidden="true" className="h-3.5 w-3.5" />
        作者视图
      </button>
      <button
        type="button"
        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
          viewMode === 'gatekeeper'
            ? 'bg-white text-ink-900 shadow-sm'
            : 'text-ink-500 hover:text-ink-700'
        }`}
        onClick={() => onViewModeChange('gatekeeper')}
        aria-pressed={viewMode === 'gatekeeper'}
      >
        <FiEyeOff aria-hidden="true" className="h-3.5 w-3.5" />
        把关者视图
      </button>
    </div>
  );
}

function ReadyReportPreview({ caseId, reloadKey, reportUrl, viewMode, iframeRef, onIframeLoad }) {
  return (
    <section className="dossier-panel overflow-hidden rounded-2xl">
      {viewMode === 'gatekeeper' && (
        <div className="flex items-center gap-2 border-b border-ink-200/60 bg-ink-50/80 px-4 py-2 text-xs font-medium text-ink-500">
          <FiEyeOff aria-hidden="true" className="h-3.5 w-3.5" />
          <span>只读模式 · Read-only</span>
        </div>
      )}
      <iframe
        ref={iframeRef}
        key={`${caseId}-${reloadKey}`}
        title="Veritas final audit report"
        src={reportUrl}
        loading="lazy"
        sandbox="allow-same-origin allow-popups allow-top-navigation-by-user-activation"
        onLoad={onIframeLoad}
        className="h-[78vh] w-full bg-white [content-visibility:auto] [contain-intrinsic-size:900px]"
      />
    </section>
  );
}

function WaitingReportPreview() {
  return (
    <section className="dossier-panel overflow-hidden rounded-2xl">
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
  const formatter = new Intl.NumberFormat(navigator.languages ?? ['zh-CN'], { maximumFractionDigits: 1 });
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${formatter.format(value / 1024)} KB`;
  return `${formatter.format(value / 1024 / 1024)} MB`;
}

function VersionHistorySection({ selectedCase, gradeData }) {
  const currentVersion = selectedCase?.report_version || 1;
  const parentReportId = selectedCase?.parent_report_id;

  if (!currentVersion || currentVersion <= 1) return null;

  return (
    <section className="dossier-panel rounded-2xl p-6">
      <p className="metric-label">版本历史</p>
      <div className="mt-4 flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-xl bg-accent-100/60 px-3 py-2 text-sm font-medium text-accent-700">
          <span className="font-mono">v{currentVersion}</span>
          <span>（修订版）</span>
        </div>
        {gradeData && (
          <span className="mono-chip">
            grade: {gradeData.grade || '?'}
          </span>
        )}
      </div>
      {parentReportId && (
        <p className="mt-3 text-xs text-ink-500">
          原版本编号：<span className="font-mono">{parentReportId}</span>（仍可查证）
        </p>
      )}
      <p className="mt-3 text-xs leading-5 text-ink-500">
        修订生成新版本，旧版本永久存档可查。编号可在 verify.veritas.science 验证。
      </p>
    </section>
  );
}

export default ReportCenterPage;
