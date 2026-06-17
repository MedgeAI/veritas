import { useCallback, useEffect, useState } from 'react';
import { FiRefreshCw, FiActivity } from 'react-icons/fi';
import { listInvestigations } from '../services/api.js';

function InvestigationBoardPage({ selectedCase, selectedCaseId }) {
  const [records, setRecords] = useState([]);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedRecord, setSelectedRecord] = useState(null);

  const loadData = useCallback(async () => {
    if (!selectedCaseId) return;
    setLoading(true);
    setError('');
    try {
      const data = await listInvestigations(selectedCaseId);
      setRecords(data.records || []);
      setResults(data.results || []);
    } catch (err) {
      setError(err.message || 'Failed to load investigations');
    } finally {
      setLoading(false);
    }
  }, [selectedCaseId]);

  useEffect(() => { loadData(); }, [loadData]);

  if (!selectedCase) {
    return (
      <section className="dossier-panel overflow-hidden rounded-[2rem] p-6">
        <p className="text-sm text-ink-900/50">Select a case to view investigation records.</p>
      </section>
    );
  }

  const triggerBadge = (meta) => {
    const trigger = meta?.trigger || 'unknown';
    const colors = {
      web_manual: 'bg-blue-100 text-blue-800',
      cli_orchestrator: 'bg-green-100 text-green-800',
      agent_investigation: 'bg-purple-100 text-purple-800',
    };
    return (
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[trigger] || 'bg-gray-100 text-gray-700'}`}>
        {trigger}
      </span>
    );
  };

  const statusBadge = (status) => {
    const colors = {
      completed: 'bg-emerald-100 text-emerald-800',
      ran: 'bg-emerald-100 text-emerald-800',
      failed: 'bg-red-100 text-red-800',
      skipped: 'bg-amber-100 text-amber-800',
    };
    return (
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-700'}`}>
        {status}
      </span>
    );
  };

  // Find result payload for a record
  const getResultForRecord = (record) => {
    const actionId = record.action_id || '';
    return results.find(r => r.record?.action_id === actionId);
  };

  return (
    <section className="dossier-panel overflow-hidden rounded-[2rem] p-6">
      {/* Header */}
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-ink-900 flex items-center gap-2">
            <FiActivity className="text-ink-900/60" />
            Investigation Board
          </h2>
          <p className="mt-1 text-sm text-ink-900/50">
            {records.length} record{records.length !== 1 ? 's' : ''} · {results.length} with output artifacts
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-2 rounded-xl border border-ink-900/10 bg-white/60 px-4 py-2 text-sm text-ink-900/70 transition hover:bg-white"
        >
          <FiRefreshCw className={loading ? 'animate-spin' : ''} />
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </header>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {records.length === 0 && !loading && (
        <div className="rounded-[2rem] border border-dashed border-ink-900/20 bg-white/40 p-8 text-center">
          <p className="text-sm text-ink-900/50">No investigation records yet.</p>
          <p className="mt-1 text-xs text-ink-900/40">
            Records appear after running visual investigations from Visual Forensics or the CLI orchestrator.
          </p>
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left: Records list */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-900/40">
            Investigation Records
          </h3>
          {records.map((record, i) => {
            const key = `${record.round_id || 0}-${record.action_id || i}`;
            const isSelected = selectedRecord?.action_id === record.action_id;
            return (
              <button
                key={key}
                onClick={() => setSelectedRecord(record)}
                className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                  isSelected
                    ? 'border-ink-900/30 bg-ink-900/5 shadow-sm'
                    : 'border-ink-900/10 bg-white/60 hover:bg-white'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-medium text-ink-900">
                    {record.tool_id || 'unknown'}
                  </span>
                  <div className="flex items-center gap-2">
                    {statusBadge(record.status)}
                    {triggerBadge(record.metadata)}
                  </div>
                </div>
                {record.hypothesis && (
                  <p className="mt-1 text-xs text-ink-900/60 line-clamp-2">{record.hypothesis}</p>
                )}
                <div className="mt-1 flex items-center gap-3 text-xs text-ink-900/40">
                  {record.round_id != null && <span>Round {record.round_id}</span>}
                  {record.output_artifacts?.length > 0 && (
                    <span>{record.output_artifacts.length} artifact(s)</span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Right: Detail panel */}
        <div>
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-900/40">
            Record Detail
          </h3>
          {!selectedRecord ? (
            <div className="rounded-[2rem] border border-dashed border-ink-900/20 bg-white/40 p-8 text-center">
              <p className="text-sm text-ink-900/50">Select a record to view details.</p>
            </div>
          ) : (
            <div className="space-y-4 rounded-xl border border-ink-900/10 bg-white/60 p-4">
              <div>
                <h4 className="text-sm font-semibold text-ink-900">{selectedRecord.tool_id}</h4>
                <p className="text-xs text-ink-900/50">
                  Round {selectedRecord.round_id ?? '—'} · Action {selectedRecord.action_id ?? '—'}
                </p>
              </div>

              {selectedRecord.hypothesis && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Hypothesis</p>
                  <p className="text-sm text-ink-900">{selectedRecord.hypothesis}</p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="font-medium text-ink-900/60">Status</span>
                  <div className="mt-1">{statusBadge(selectedRecord.status)}</div>
                </div>
                <div>
                  <span className="font-medium text-ink-900/60">Validation</span>
                  <p className="mt-1 text-ink-900">{selectedRecord.validation_status || '—'}</p>
                </div>
                <div>
                  <span className="font-medium text-ink-900/60">Evidence Type</span>
                  <p className="mt-1 text-ink-900">{selectedRecord.expected_evidence_type || '—'}</p>
                </div>
                <div>
                  <span className="font-medium text-ink-900/60">Trigger</span>
                  <div className="mt-1">{triggerBadge(selectedRecord.metadata)}</div>
                </div>
              </div>

              {selectedRecord.params && Object.keys(selectedRecord.params).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Parameters</p>
                  <pre className="mt-1 overflow-x-auto rounded-lg bg-ink-900/5 p-2 text-xs text-ink-900/80">
                    {JSON.stringify(selectedRecord.params, null, 2)}
                  </pre>
                </div>
              )}

              {selectedRecord.output_artifacts?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Output Artifacts</p>
                  <ul className="mt-1 space-y-1">
                    {selectedRecord.output_artifacts.map((a, i) => (
                      <li key={i} className="font-mono text-xs text-ink-900/70">{a}</li>
                    ))}
                  </ul>
                </div>
              )}

              {selectedRecord.detail && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Detail</p>
                  <p className="text-sm text-ink-900">{selectedRecord.detail}</p>
                </div>
              )}

              {/* Show result payload if available */}
              {(() => {
                const resultEntry = getResultForRecord(selectedRecord);
                if (!resultEntry?.result) return null;
                return (
                  <div>
                    <p className="text-xs font-medium text-ink-900/60">Result Payload</p>
                    <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-ink-900/5 p-2 text-xs text-ink-900/80">
                      {JSON.stringify(resultEntry.result, null, 2)}
                    </pre>
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export default InvestigationBoardPage;
