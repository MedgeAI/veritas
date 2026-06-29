import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FiExternalLink, FiRefreshCw } from 'react-icons/fi';
import FollowUpDisplay from '../components/FollowUpDisplay.jsx';
import GradeBadge from '../components/GradeBadge.jsx';
import MaterialChecklist from '../components/MaterialChecklist.jsx';
import ProgressTracker from '../components/ProgressTracker.jsx';
import RiskTrafficLight from '../components/RiskTrafficLight.jsx';
import EmptyState from '../components/EmptyState.jsx';
import StatusPill from '../components/StatusPill.jsx';
import { useRunSteps } from '../hooks/useRunSteps.js';
import { translateStatus, translateArtifactLabel, translateRiskLevel, translateIssueCategory } from '../utils/piLabels.js';
import { checkMaterials, getRiskSummary, getRun, listArtifacts, reportHtmlUrl } from '../services/api.js';

function MissionControlPage({ selectedCase, selectedRunId, onSelectRun, onRefreshCases }) {
  const selectedCaseId = selectedCase?.case_id || '';
  const effectiveRunId = selectedRunId || selectedCase?.latest_run_id || '';
  const [run, setRun] = useState(null);
  const [artifacts, setArtifacts] = useState([]);
  const [error, setError] = useState('');
  const [staleRun, setStaleRun] = useState(false);
  const [riskSummary, setRiskSummary] = useState(null);
  const [materials, setMaterials] = useState(null);

  // Fetch steps from backend for dynamic progress rendering
  const { steps } = useRunSteps(selectedCaseId, effectiveRunId);

  const selectedCaseRef = useRef(selectedCase);
  useEffect(() => { selectedCaseRef.current = selectedCase; }, [selectedCase]);

  const isLive = useMemo(() => ['queued', 'running'].includes(run?.status), [run]);
  const isFinished = run?.status === 'completed';

  const refresh = useCallback(async () => {
    const sc = selectedCaseRef.current;
    if (!sc || !effectiveRunId) return;
    try {
      const [nextRun, nextArtifacts] = await Promise.all([
        getRun(sc.case_id, effectiveRunId),
        listArtifacts(sc.case_id),
      ]);
      setRun(nextRun);
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
  }, [effectiveRunId, onRefreshCases, onSelectRun]);

  // Fetch risk summary when run completes (or when case/run changes)
  useEffect(() => {
    if (!selectedCaseId || !isFinished) {
      setRiskSummary(null);
      return;
    }
    let cancelled = false;
    getRiskSummary(selectedCaseId)
      .then((data) => { if (!cancelled) setRiskSummary(data); })
      .catch(() => { /* non-critical: leave null */ });
    return () => { cancelled = true; };
  }, [selectedCaseId, isFinished]);

  // Fetch materials completeness when case changes
  useEffect(() => {
    if (!selectedCaseId) {
      setMaterials(null);
      return;
    }
    let cancelled = false;
    checkMaterials(selectedCaseId)
      .then((data) => { if (!cancelled) setMaterials(data); })
      .catch(() => { /* non-critical: leave null */ });
    return () => { cancelled = true; };
  }, [selectedCaseId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedCaseId || !effectiveRunId) return undefined;
    const timer = window.setInterval(refresh, isLive ? 2500 : 8000);
    return () => window.clearInterval(timer);
  }, [effectiveRunId, isLive, refresh, selectedCaseId]);

  if (!selectedCase) {
    return <EmptyState title="请先选择或创建一个 Case。" />;
  }

  if (!effectiveRunId) {
    return <EmptyState title="当前 Case 还没有运行记录，请在 New Audit 启动审查。" />;
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      {run ? (
        <div className="xl:col-span-2">
          <ProgressTracker steps={steps} runStatus={run.status} caseId={selectedCaseId} />
        </div>
      ) : null}

      {/* Risk Summary — only shown after run completes */}
      {isFinished && riskSummary ? (
        <section className="xl:col-span-2 dossier-panel rounded-2xl p-6">
          {/* Certification Grade */}
          {run?.summary?.certification_grade ? (
            <div className="mb-5">
              <p className="metric-label mb-3">认证评级</p>
              <GradeBadge
                grade={run.summary.certification_grade.grade}
                dimensions={run.summary.certification_grade.dimensions}
                size="lg"
              />
            </div>
          ) : null}
          <p className="metric-label">风险评估</p>
          <div className="mt-4">
            <RiskTrafficLight riskLevel={riskSummary.overall_risk} riskCounts={riskSummary.risk_counts} />
          </div>
          <p className="mt-4 font-mono text-[11px] text-ink-500">
            {riskSummary.status === 'unavailable'
              ? '风险概览数据尚未生成，当前证据不足以汇总风险。'
              : `共 ${riskSummary.total_findings} 个发现，其中 ${riskSummary.high_quality_count} 个为中高风险`}
          </p>
          {riskSummary.status === 'unavailable' ? (
            <p className="mt-4 rounded-2xl bg-white/45 p-4 text-sm text-ink-500">
              请等待审查完成后重试，或查看下方产物准备情况和异常记录。
            </p>
          ) : riskSummary.top_findings.length > 0 ? (
            <div className="mt-5 space-y-4">
              <p className="text-sm font-semibold text-ink-900">Top {riskSummary.top_findings.length} 发现</p>
              {riskSummary.top_findings.map((finding, idx) => {
                const fId = finding.finding_id || '';
                const questions = riskSummary.follow_ups?.[fId] || [];
                return (
                  <article key={fId || idx} className="rounded-2xl border border-ink-900/8 bg-white/50 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[11px] text-ink-500">{fId}</span>
                          <StatusPill tone={finding.risk_level === 'critical' || finding.risk_level === 'high' ? 'risk' : 'warn'}>
                            {translateRiskLevel(finding.risk_level)}
                          </StatusPill>
                          {finding.issue_category ? (
                            <span className="font-mono text-[10px] text-ink-500">{translateIssueCategory(finding.issue_category)}</span>
                          ) : null}
                        </div>
                        <p className="mt-1.5 text-sm leading-6 text-ink-700">{finding.summary}</p>
                      </div>
                    </div>
                    <div className="mt-3 border-t border-ink-900/5 pt-3">
                      <p className="mb-1.5 text-[11px] font-semibold text-ink-500">建议追问</p>
                      <FollowUpDisplay followUps={questions} />
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-4 rounded-2xl bg-white/45 p-4 text-sm text-ink-500">
              未发现中高风险问题。
            </p>
          )}
        </section>
      ) : null}

      <section className="dossier-panel rounded-2xl p-6">
        <div className="flex flex-col gap-4 border-b border-ink-900/10 pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="metric-label">运行状态</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <h2 className="section-title">{effectiveRunId}</h2>
              {run ? <StatusPill>{translateStatus(run.status)}</StatusPill> : <StatusPill>loading</StatusPill>}
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <button type="button" className="btn-secondary" onClick={refresh}>
              <FiRefreshCw aria-hidden="true" />
              刷新进度
            </button>
            <a className="btn-primary" href={reportHtmlUrl(selectedCaseId)} target="_blank" rel="noreferrer">
              <FiExternalLink aria-hidden="true" />
              报告
            </a>
          </div>
        </div>

        {error ? (
          <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm leading-6 text-risk-700" role="alert" aria-live="polite">
            {staleRun ? (
              <>
                <strong>上次恢复的 run 不存在。</strong>
                <span className="block">这通常说明本地缓存记录的是旧工作区，或审查数据已被清理。请选择当前审查项目的最新运行，或重新启动审查。</span>
              </>
            ) : (
              <>
                {error}
                <button
                  type="button"
                  className="mt-2 block text-sm underline"
                  onClick={() => { setError(''); refresh(); }}
                >
                  刷新重试
                </button>
              </>
            )}
          </div>
        ) : null}
      </section>

      <aside className="space-y-6">
        {materials ? (
          <MaterialChecklist caseId={selectedCaseId} materials={materials} />
        ) : null}

        <section className="dossier-panel rounded-2xl p-6">
          <p className="metric-label">产物准备情况</p>
          <div className="mt-4 space-y-3" aria-live="polite">
            {artifacts.map((artifact) => (
              <div key={artifact.artifact_id} className="flex items-center justify-between gap-3 rounded-2xl bg-white/50 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-ink-900">{translateArtifactLabel(artifact.label)}</p>
                </div>
                <StatusPill tone={artifact.exists ? 'ok' : 'neutral'}>{artifact.exists ? '已就绪' : '缺失'}</StatusPill>
              </div>
            ))}
          </div>
        </section>

        <section className="dossier-panel rounded-2xl p-6">
          <p className="metric-label">异常记录</p>
          <p className="mt-3 text-sm leading-6 text-ink-500">
            审查过程中遇到的错误会记录在此处。如果审查正常完成，此处为空。
          </p>
          {run?.error ? (
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-semibold text-risk-700">查看错误详情</summary>
              <pre className="mt-2 overflow-auto rounded-2xl bg-risk-100 p-3 font-mono text-xs text-risk-700">{run.error}</pre>
            </details>
          ) : null}
        </section>
      </aside>
    </div>
  );
}

export default MissionControlPage;
