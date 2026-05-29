import { useCallback, useEffect, useMemo, useState } from 'react';
import StatusPill from '../components/StatusPill.jsx';
import { getArtifactText, listArtifacts } from '../services/api.js';

function prettyText(text, artifactId) {
  if (artifactId?.endsWith('report')) return text;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function EvidenceWorkspacePage({ selectedCase }) {
  const [artifacts, setArtifacts] = useState([]);
  const [activeArtifactId, setActiveArtifactId] = useState('');
  const [artifactText, setArtifactText] = useState('');
  const [error, setError] = useState('');

  const activeArtifact = useMemo(
    () => artifacts.find((item) => item.artifact_id === activeArtifactId),
    [artifacts, activeArtifactId],
  );

  const refreshArtifacts = useCallback(async () => {
    if (!selectedCase) return;
    try {
      const payload = await listArtifacts(selectedCase.case_id);
      const nextArtifacts = payload.artifacts || [];
      setArtifacts(nextArtifacts);
      const firstReady = nextArtifacts.find((item) => item.exists);
      setActiveArtifactId((current) => current || firstReady?.artifact_id || nextArtifacts[0]?.artifact_id || '');
      setError('');
    } catch (nextError) {
      setError(nextError.message || String(nextError));
    }
  }, [selectedCase]);

  useEffect(() => {
    refreshArtifacts();
  }, [refreshArtifacts]);

  useEffect(() => {
    async function loadArtifact() {
      if (!selectedCase || !activeArtifactId || !activeArtifact?.exists || activeArtifact.kind === 'html_report') {
        setArtifactText('');
        return;
      }
      try {
        const text = await getArtifactText(selectedCase.case_id, activeArtifactId);
        setArtifactText(prettyText(text, activeArtifactId));
        setError('');
      } catch (nextError) {
        setError(nextError.message || String(nextError));
      }
    }
    loadArtifact();
  }, [selectedCase, activeArtifactId, activeArtifact?.exists, activeArtifact?.kind]);

  if (!selectedCase) {
    return <EmptyEvidence />;
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <section className="dossier-panel rounded-[2rem] p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="metric-label">Artifacts</p>
            <h2 className="mt-2 font-display text-2xl font-semibold">证据产物</h2>
          </div>
          <button type="button" className="btn-ghost" onClick={refreshArtifacts}>
            刷新
          </button>
        </div>

        <div className="mt-5 space-y-3">
          {artifacts.map((artifact) => (
            <button
              key={artifact.artifact_id}
              type="button"
              onClick={() => setActiveArtifactId(artifact.artifact_id)}
              className={`flow-list-item w-full rounded-3xl border p-4 text-left transition ${
                activeArtifactId === artifact.artifact_id
                  ? 'border-signal-500/35 bg-signal-100/60'
                  : 'border-ink-900/8 bg-white/45 hover:bg-white/70'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold text-ink-900">{artifact.label}</p>
                <StatusPill tone={artifact.exists ? 'ok' : 'neutral'}>{artifact.exists ? 'ready' : 'missing'}</StatusPill>
              </div>
              <p className="mt-2 font-mono text-[11px] text-ink-300">{artifact.path}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="dossier-panel min-h-[640px] rounded-[2rem] p-6">
        <div className="flex flex-col gap-3 border-b border-ink-900/10 pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="metric-label">Viewer</p>
            <h2 className="section-title">{activeArtifact?.label || '未选择产物'}</h2>
          </div>
          {activeArtifact ? <span className="mono-chip">{activeArtifact.kind}</span> : null}
        </div>

        {error ? <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700">{error}</div> : null}

        {!activeArtifact ? (
          <p className="mt-6 text-sm text-ink-500">当前 case 尚未生成可读取产物。</p>
        ) : activeArtifact.kind === 'html_report' ? (
          <p className="mt-6 text-sm text-ink-500">HTML 报告请在 Report Center 预览，避免把报告 iframe 和证据 JSON 阅读混在一起。</p>
        ) : !activeArtifact.exists ? (
          <p className="mt-6 text-sm text-ink-500">该产物尚未生成。请在 Mission Control 查看运行进度。</p>
        ) : (
          <pre className="mt-5 max-h-[620px] overflow-auto rounded-3xl bg-ink-900 p-5 font-mono text-xs leading-6 text-paper-100">
            {artifactText || 'loading...'}
          </pre>
        )}
      </section>
    </div>
  );
}

function EmptyEvidence() {
  return (
    <section className="dossier-panel rounded-[2rem] p-8 text-center">
      <p className="font-display text-2xl font-semibold">请先选择 Case</p>
      <p className="mt-3 text-sm text-ink-500">Evidence Workspace 读取已完成或运行中的结构化产物。</p>
    </section>
  );
}

export default EvidenceWorkspacePage;
