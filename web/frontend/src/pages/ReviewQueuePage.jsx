import { useCallback, useEffect, useState } from 'react';
import { FiRefreshCw, FiCheckCircle, FiXCircle, FiMessageSquare } from 'react-icons/fi';
import { fetchReviewItems, saveReviewDecision } from '../services/api.js';

const RISK_COLORS = {
  critical: 'bg-red-600 text-white',
  high: 'bg-red-100 text-red-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-blue-100 text-blue-800',
  info: 'bg-gray-100 text-gray-700',
};

const STATUS_OPTIONS = [
  { value: 'open', label: 'Open', color: 'bg-gray-100 text-gray-700' },
  { value: 'resolved', label: 'Resolved', color: 'bg-emerald-100 text-emerald-800' },
  { value: 'dismissed', label: 'Dismissed', color: 'bg-gray-100 text-gray-500' },
  { value: 'needs_author_response', label: 'Needs Author Response', color: 'bg-orange-100 text-orange-800' },
];

function ReviewQueuePage({ selectedCase, selectedCaseId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedItem, setSelectedItem] = useState(null);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterRisk, setFilterRisk] = useState('all');
  const [noteInput, setNoteInput] = useState('');
  const [saving, setSaving] = useState(false);

  const loadData = useCallback(async () => {
    if (!selectedCaseId) return;
    setLoading(true);
    setError('');
    try {
      const data = await fetchReviewItems(selectedCaseId);
      setItems(data.items || []);
    } catch (err) {
      setError(err.message || 'Failed to load review items');
    } finally {
      setLoading(false);
    }
  }, [selectedCaseId]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleDecision = async (status) => {
    if (!selectedItem || !selectedCaseId) return;
    setSaving(true);
    try {
      await saveReviewDecision(selectedCaseId, selectedItem.source_ref, {
        status,
        note: noteInput,
      });
      setNoteInput('');
      await loadData();
      // Refresh selected item's decision
      const updated = items.find(i => i.source_ref === selectedItem.source_ref);
      if (updated) {
        setSelectedItem({ ...updated, decision: { ...updated.decision, status, note: noteInput } });
      }
    } catch (err) {
      setError(err.message || 'Failed to save decision');
    } finally {
      setSaving(false);
    }
  };

  const filteredItems = items.filter(item => {
    if (filterStatus !== 'all') {
      const itemStatus = item.decision?.status || 'open';
      if (itemStatus !== filterStatus) return false;
    }
    if (filterRisk !== 'all' && item.risk_level !== filterRisk) return false;
    return true;
  });

  if (!selectedCase) {
    return (
      <section className="dossier-panel overflow-hidden rounded-[2rem] p-6">
        <p className="text-sm text-ink-900/50">Select a case to view review items.</p>
      </section>
    );
  }

  const openCount = items.filter(i => !i.decision || i.decision.status === 'open').length;
  const resolvedCount = items.filter(i => i.decision?.status === 'resolved').length;

  return (
    <section className="dossier-panel overflow-hidden rounded-[2rem] p-6">
      {/* Header */}
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold text-ink-900">
            <FiMessageSquare className="text-ink-900/60" />
            Review Queue
          </h2>
          <p className="mt-1 text-sm text-ink-900/50">
            {items.length} item{items.length !== 1 ? 's' : ''} · {openCount} open · {resolvedCount} resolved
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

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          className="rounded-lg border border-ink-900/10 bg-white/60 px-3 py-1.5 text-sm text-ink-900"
        >
          <option value="all">All statuses</option>
          {STATUS_OPTIONS.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
        <select
          value={filterRisk}
          onChange={e => setFilterRisk(e.target.value)}
          className="rounded-lg border border-ink-900/10 bg-white/60 px-3 py-1.5 text-sm text-ink-900"
        >
          <option value="all">All risk levels</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {filteredItems.length === 0 && !loading && (
        <div className="rounded-[2rem] border border-dashed border-ink-900/20 bg-white/40 p-8 text-center">
          <p className="text-sm text-ink-900/50">No review items match the current filters.</p>
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left: Items list */}
        <div className="max-h-[600px] space-y-2 overflow-y-auto">
          {filteredItems.map(item => {
            const isSelected = selectedItem?.source_ref === item.source_ref;
            const status = item.decision?.status || 'open';
            const statusOpt = STATUS_OPTIONS.find(s => s.value === status) || STATUS_OPTIONS[0];
            return (
              <button
                key={item.source_ref}
                onClick={() => { setSelectedItem(item); setNoteInput(item.decision?.note || ''); }}
                className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                  isSelected
                    ? 'border-ink-900/30 bg-ink-900/5 shadow-sm'
                    : 'border-ink-900/10 bg-white/60 hover:bg-white'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-ink-900 line-clamp-1">
                    {item.title || item.source_ref}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${RISK_COLORS[item.risk_level] || RISK_COLORS.info}`}>
                      {item.risk_level}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusOpt.color}`}>
                      {statusOpt.label}
                    </span>
                  </div>
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-ink-900/40">
                  <span className="rounded bg-ink-900/5 px-1.5 py-0.5 font-mono">{item.source}</span>
                  {item.issue_category && <span>{item.issue_category}</span>}
                </div>
              </button>
            );
          })}
        </div>

        {/* Right: Detail + Decision */}
        <div>
          {!selectedItem ? (
            <div className="rounded-[2rem] border border-dashed border-ink-900/20 bg-white/40 p-8 text-center">
              <p className="text-sm text-ink-900/50">Select an item to view details and make a decision.</p>
            </div>
          ) : (
            <div className="space-y-4 rounded-xl border border-ink-900/10 bg-white/60 p-4">
              <div>
                <h4 className="text-sm font-semibold text-ink-900">{selectedItem.title || selectedItem.source_ref}</h4>
                <p className="font-mono text-xs text-ink-900/40">{selectedItem.source_ref}</p>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="font-medium text-ink-900/60">Risk Level</span>
                  <div className="mt-1">
                    <span className={`rounded-full px-2 py-0.5 font-medium ${RISK_COLORS[selectedItem.risk_level] || RISK_COLORS.info}`}>
                      {selectedItem.risk_level}
                    </span>
                  </div>
                </div>
                <div>
                  <span className="font-medium text-ink-900/60">Category</span>
                  <p className="mt-1 text-ink-900">{selectedItem.issue_category || '—'}</p>
                </div>
              </div>

              {selectedItem.recommended_action && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Recommended Action</p>
                  <p className="text-sm text-ink-900">{selectedItem.recommended_action}</p>
                </div>
              )}

              {selectedItem.benign_explanation && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Benign Explanation</p>
                  <p className="text-sm text-ink-900/80">{selectedItem.benign_explanation}</p>
                </div>
              )}

              {selectedItem.evidence_refs?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-ink-900/60">Evidence Refs</p>
                  <ul className="mt-1 space-y-1">
                    {selectedItem.evidence_refs.map((ref, i) => (
                      <li key={i} className="font-mono text-xs text-ink-900/70">
                        {typeof ref === 'string' ? ref : JSON.stringify(ref)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Decision controls */}
              <div className="border-t border-ink-900/10 pt-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-900/40">
                  Decision
                </p>
                <textarea
                  value={noteInput}
                  onChange={e => setNoteInput(e.target.value)}
                  placeholder="Add a note (optional)..."
                  className="mb-3 w-full rounded-lg border border-ink-900/10 bg-white/80 px-3 py-2 text-sm text-ink-900 placeholder:text-ink-900/30"
                  rows={2}
                />
                <div className="flex flex-wrap gap-2">
                  {STATUS_OPTIONS.filter(s => s.value !== 'open').map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => handleDecision(opt.value)}
                      disabled={saving}
                      className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition hover:opacity-80 ${
                        opt.value === 'resolved'
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                          : opt.value === 'dismissed'
                            ? 'border-gray-200 bg-gray-50 text-gray-600'
                            : 'border-orange-200 bg-orange-50 text-orange-800'
                      }`}
                    >
                      {opt.value === 'resolved' && <FiCheckCircle />}
                      {opt.value === 'dismissed' && <FiXCircle />}
                      {opt.label}
                    </button>
                  ))}
                </div>
                {selectedItem.decision?.status && (
                  <p className="mt-2 text-xs text-ink-900/50">
                    Current status: <strong>{selectedItem.decision.status}</strong>
                    {selectedItem.decision.note && <> · Note: {selectedItem.decision.note}</>}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export default ReviewQueuePage;
