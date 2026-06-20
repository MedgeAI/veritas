import { memo } from 'react';
import { visualImageUrl } from '../services/api.js';

/**
 * CBIR search results grid
 * Displays similar panels with similarity scores and detail drawer
 */
function CBIRResults({ results, caseId, onSelectPanel }) {
  if (!results || results.length === 0) {
    return (
      <div className="mt-6 rounded-2xl border border-ink-900/10 bg-paper-100/60 p-8 text-center">
        <p className="text-sm text-ink-500">未找到相似 panel</p>
      </div>
    );
  }

  return (
    <div className="mt-6">
      <h3 className="mb-4 text-lg font-semibold text-ink-900">
        相似 Panel 结果 <span className="text-sm font-normal text-ink-500">({results.length} 个)</span>
      </h3>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
        {results.map((result) => (
          <ResultCard
            key={`${result.case_id}-${result.panel_id}`}
            result={result}
            caseId={caseId}
            onClick={() => onSelectPanel?.(result)}
          />
        ))}
      </div>
    </div>
  );
}

const ResultCard = memo(function ResultCard({ result, caseId, onClick }) {
  const similarityPercent = (result.similarity * 100).toFixed(1);
  const riskTone = result.similarity >= 0.95 ? 'critical' : result.similarity >= 0.85 ? 'warning' : 'neutral';

  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative overflow-hidden rounded-2xl border border-ink-900/10 bg-paper-100/70 p-3 text-left transition hover:border-ink-900/20 hover:shadow-lg"
    >
      <div className="relative aspect-square overflow-hidden rounded-xl bg-ink-50">
        <img
          src={visualImageUrl(caseId, result.image_path)}
          alt={result.panel_id}
          className="h-full w-full object-cover transition group-hover:scale-105"
          loading="lazy"
          onError={(e) => {
            e.target.style.display = 'none';
          }}
        />
        <div className="absolute right-2 top-2">
          <span
            className={`rounded-full px-2 py-1 text-xs font-semibold shadow-sm ${
              riskTone === 'critical'
                ? 'bg-risk-500 text-white'
                : riskTone === 'warning'
                  ? 'bg-caution-500 text-white'
                  : 'bg-paper-50/90 text-ink-900'
            }`}
          >
            {similarityPercent}%
          </span>
        </div>
      </div>
      <div className="mt-3 space-y-1">
        <p className="truncate text-sm font-medium text-ink-900">{result.panel_id}</p>
        <p className="truncate text-xs text-ink-500">
          {result.figure_id && <span>Figure: {result.figure_id} | </span>}
          Case: {result.case_id}
        </p>
        {result.label && (
          <p className="truncate text-xs text-ink-400">{result.label}</p>
        )}
      </div>
    </button>
  );
});

export default CBIRResults;
