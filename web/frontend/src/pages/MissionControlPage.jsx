import { useCallback, useEffect, useMemo, useState } from 'react';
import { FiExternalLink, FiRefreshCw } from 'react-icons/fi';
import StatusPill from '../components/StatusPill.jsx';
import { getEvents, getRun, listArtifacts, reportHtmlUrl } from '../services/api.js';

function eventDetail(event) {
  const copy = { ...event };
  delete copy.timestamp;
  delete copy.event;
  return JSON.stringify(copy, null, 2);
}

function eventKey(event, index) {
  return [
    index,
    event.timestamp || 'no-ts',
    event.event || 'event',
    event.key || '',
    event.title || '',
    event.attempt || '',
  ].join('|');
}

function MissionControlPage({ selectedCase, selectedRunId, onSelectRun, onRefreshCases }) {
  const effectiveRunId = selectedRunId || selectedCase?.latest_run_id || '';
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [error, setError] = useState('');
  const [staleRun, setStaleRun] = useState(false);

  const isLive = useMemo(() => ['queued', 'running'].includes(run?.status), [run]);

  const refresh = useCallback(async () => {
    if (!selectedCase || !effectiveRunId) return;
    try {
      const [nextRun, nextEvents, nextArtifacts] = await Promise.all([
        getRun(selectedCase.case_id, effectiveRunId),
        getEvents(selectedCase.case_id, effectiveRunId),
        listArtifacts(selectedCase.case_id),
      ]);
      setRun(nextRun);
      setEvents(nextEvents.events || []);
      setArtifacts(nextArtifacts.artifacts || []);
      onSelectRun(nextRun.run_id);
      setError('');
      setStaleRun(false);
      if (!['queued', 'running'].includes(nextRun.status)) {
        onRefreshCases();
      }
    } catch (nextError) {
      const message = nextError.message || String(nextError);
      setError(message);
      setStaleRun(message.includes('run not found'));
    }
  }, [effectiveRunId, onRefreshCases, onSelectRun, selectedCase]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedCase || !effectiveRunId) return undefined;
    const timer = window.setInterval(refresh, isLive ? 2500 : 8000);
    return () => window.clearInterval(timer);
  }, [effectiveRunId, isLive, refresh, selectedCase]);

  if (!selectedCase) {
    return <EmptyMission message="请先选择或创建一个 Case。" />;
  }

  if (!effectiveRunId) {
    return <EmptyMission message="当前 Case 还没有运行记录，请在 New Audit 启动审查。" />;
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="flex flex-col gap-4 border-b border-ink-900/10 pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="metric-label">Run State</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <h2 className="section-title">{effectiveRunId}</h2>
              {run ? <StatusPill>{run.status}</StatusPill> : <StatusPill>loading</StatusPill>}
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <button type="button" className="btn-secondary" onClick={refresh}>
              <FiRefreshCw aria-hidden="true" />
              刷新进度
            </button>
            <a className="btn-primary" href={reportHtmlUrl(selectedCase.case_id)} target="_blank" rel="noreferrer">
              <FiExternalLink aria-hidden="true" />
              报告
            </a>
          </div>
        </div>

        {error ? (
          <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm leading-6 text-risk-700">
            {staleRun ? (
              <>
                <strong>上次恢复的 run 不存在。</strong>
                <span className="block">这通常说明 localStorage 记录的是旧工作区，或 backend 的 `web_data` 已被清理。请选择当前 case 的最新 run，或重新启动审查。</span>
              </>
            ) : (
              error
            )}
          </div>
        ) : null}

        <div className="mt-6 grid gap-4 md:grid-cols-4">
          <Metric label="status" value={run?.status || '-'} />
          <Metric label="started" value={run?.started_at || '-'} />
          <Metric label="completed" value={run?.completed_at || '-'} />
          <Metric label="events" value={events.length} />
        </div>

        <div className="mt-7">
          <p className="metric-label">Progress Events</p>
          <div className="mt-3 max-h-[580px] space-y-3 overflow-auto pr-2">
            {events.length === 0 ? <p className="rounded-2xl bg-white/45 p-5 text-sm text-ink-500">等待 backend 写入进度事件。</p> : null}
            {events.map((event, index) => (
              <article key={eventKey(event, index)} className="flow-list-item rounded-3xl border border-ink-900/8 bg-white/50 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="grid h-8 w-8 place-items-center rounded-full bg-ink-900 font-mono text-xs text-paper-50">
                      {index + 1}
                    </span>
                    <div>
                      <p className="font-semibold text-ink-900">{event.event || 'event'}</p>
                      <p className="font-mono text-xs text-ink-300">{event.timestamp || 'no timestamp'}</p>
                    </div>
                  </div>
                </div>
                <pre className="mt-3 overflow-auto rounded-2xl bg-paper-100/65 p-3 font-mono text-[11px] leading-5 text-ink-500">
                  {eventDetail(event)}
                </pre>
              </article>
            ))}
          </div>
        </div>
      </section>

      <aside className="space-y-6">
        <section className="dossier-panel rounded-[2rem] p-6">
          <p className="metric-label">Artifact Readiness</p>
          <div className="mt-4 space-y-3">
            {artifacts.map((artifact) => (
              <div key={artifact.artifact_id} className="flex items-center justify-between gap-3 rounded-2xl bg-white/50 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-ink-900">{artifact.label}</p>
                  <p className="font-mono text-[11px] text-ink-300">{artifact.artifact_id}</p>
                </div>
                <StatusPill tone={artifact.exists ? 'ok' : 'neutral'}>{artifact.exists ? 'ready' : 'missing'}</StatusPill>
              </div>
            ))}
          </div>
        </section>

        <section className="dossier-panel rounded-[2rem] p-6">
          <p className="metric-label">Failure Surface</p>
          <p className="mt-3 text-sm leading-6 text-ink-500">
            MinerU 网络错误、LLM 结构化输出失败和 Tool Registry 调用失败都会在进度事件、run.error 或最终 bundle 中留下记录。
          </p>
          {run?.error ? <pre className="mt-4 overflow-auto rounded-2xl bg-risk-100 p-3 font-mono text-xs text-risk-700">{run.error}</pre> : null}
        </section>
      </aside>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-3xl border border-ink-900/8 bg-white/50 p-4">
      <p className="metric-label">{label}</p>
      <p className="mt-2 break-words font-mono text-xs text-ink-700">{String(value)}</p>
    </div>
  );
}

function EmptyMission({ message }) {
  return (
    <section className="dossier-panel rounded-[2rem] p-8 text-center">
      <p className="font-display text-2xl font-semibold">{message}</p>
      <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-ink-500">
        当前 Web P1 的核心是把 CLI 审查闭环变成可观察任务，而不是替换底层审查逻辑。
      </p>
    </section>
  );
}

export default MissionControlPage;
