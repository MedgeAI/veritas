import { useCallback, useState } from 'react';
import { FiSearch, FiUpload, FiX } from 'react-icons/fi';
import CBIRResults from '../components/CBIRResults.jsx';
import { searchSimilarPanels, searchByImageUpload } from '../services/cbir.js';

/**
 * CBIR Search Page
 * Supports panel ID search and image upload (upload not yet implemented in backend)
 */
function CBIRSearchPage({ selectedCase }) {
  const [searchMode, setSearchMode] = useState('panel'); // 'panel' or 'upload'
  const [panelId, setPanelId] = useState('');
  const [topK, setTopK] = useState(20);
  const [threshold, setThreshold] = useState(0.85);
  const [label, setLabel] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedPanel, setSelectedPanel] = useState(null);
  const [uploadedImage, setUploadedImage] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  const handlePanelSearch = useCallback(async () => {
    if (!panelId.trim()) {
      setError('请输入 Panel ID');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const response = await searchSimilarPanels(panelId.trim(), {
        caseId: selectedCase?.case_id,
        topK,
        threshold,
        label: label.trim() || undefined,
      });
      setResults(response.similar_panels || []);
    } catch (err) {
      setError(err.message || '搜索失败');
      setResults([]);
    } finally {
      setLoading(false);
      setHasSearched(true);
    }
  }, [panelId, selectedCase?.case_id, topK, threshold, label]);

  const handleImageUpload = useCallback(async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadedImage(file);
    setLoading(true);
    setError('');

    try {
      const response = await searchByImageUpload(file, { topK, threshold });
      setResults(response.similar_panels || []);
    } catch (err) {
      setError(err.message || '图片上传搜索失败');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [topK, threshold]);

  const clearUploadedImage = useCallback(() => {
    setUploadedImage(null);
    setResults([]);
  }, []);

  if (!selectedCase) {
    return (
      <section className="dossier-panel rounded-[2rem] p-8 text-center">
        <p className="font-display text-2xl font-semibold">请先选择 Case</p>
        <p className="mt-3 text-sm text-ink-500">
          CBIR Search 支持通过 Panel ID 或图片上传搜索相似 panel。
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      {/* Search Controls */}
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="metric-label">CBIR Search</p>
            <h2 className="mt-2 font-display text-2xl font-semibold">相似 Panel 搜索</h2>
            <p className="mt-2 text-sm text-ink-500">
              使用 SSCD embedding 向量搜索相似 panel，支持跨 case 搜索。
            </p>
          </div>
        </div>

        {/* Search Mode Tabs */}
        <div className="mt-6 flex gap-2 border-b border-ink-900/10">
          <button
            type="button"
            onClick={() => setSearchMode('panel')}
            className={`px-4 py-2 text-sm font-medium transition ${
              searchMode === 'panel'
                ? 'border-b-2 border-ink-900 text-ink-900'
                : 'text-ink-500 hover:text-ink-700'
            }`}
          >
            <FiSearch className="mr-2 inline" />
            Panel ID 搜索
          </button>
          <button
            type="button"
            onClick={() => setSearchMode('upload')}
            className={`px-4 py-2 text-sm font-medium transition ${
              searchMode === 'upload'
                ? 'border-b-2 border-ink-900 text-ink-900'
                : 'text-ink-500 hover:text-ink-700'
            }`}
          >
            <FiUpload className="mr-2 inline" />
            图片上传搜索
          </button>
        </div>

        {/* Panel ID Search */}
        {searchMode === 'panel' && (
          <div className="mt-6 space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-ink-700">
                  Panel ID <span className="text-risk-500">*</span>
                </label>
                <input
                  type="text"
                  value={panelId}
                  onChange={(e) => setPanelId(e.target.value)}
                  placeholder="例如: panel_001"
                  className="input-field mt-1 w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-ink-700">Label 过滤（可选）</label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="例如: Western Blot"
                  className="input-field mt-1 w-full"
                />
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-ink-700">
                  Top K: <span className="font-mono text-ink-500">{topK}</span>
                </label>
                <input
                  type="range"
                  min="5"
                  max="100"
                  step="5"
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="mt-2 w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-ink-700">
                  相似度阈值: <span className="font-mono text-ink-500">{threshold.toFixed(2)}</span>
                </label>
                <input
                  type="range"
                  min="0.5"
                  max="0.99"
                  step="0.01"
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="mt-2 w-full"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={handlePanelSearch}
              disabled={loading || !panelId.trim()}
              className="btn-primary mt-4"
            >
              <FiSearch className="mr-2" />
              {loading ? '搜索中...' : '开始搜索'}
            </button>
          </div>
        )}

        {/* Image Upload Search */}
        {searchMode === 'upload' && (
          <div className="mt-6 space-y-4">
            <div className="rounded-2xl border-2 border-dashed border-ink-900/20 bg-paper-100/50 p-8 text-center">
              <FiUpload className="mx-auto text-4xl text-ink-400" />
              <p className="mt-4 text-sm text-ink-600">
                {uploadedImage ? (
                  <span className="font-medium text-ink-900">{uploadedImage.name}</span>
                ) : (
                  '点击或拖拽图片到此处上传'
                )}
              </p>
              <input
                type="file"
                accept="image/*"
                onChange={handleImageUpload}
                className="mt-4 w-full"
                disabled={loading}
              />
              {uploadedImage && (
                <button
                  type="button"
                  onClick={clearUploadedImage}
                  className="mt-2 text-sm text-ink-500 hover:text-ink-700"
                >
                  <FiX className="mr-1 inline" />
                  清除图片
                </button>
              )}
            </div>

            <div className="rounded-2xl border border-caution-300/50 bg-caution-100/50 p-4">
              <p className="text-sm text-caution-700">
                <strong>注意：</strong>图片上传搜索功能尚未实现。当前后端仅提供 Panel ID 搜索接口。
                如需使用图片上传搜索，请先实现后端接口 <code className="rounded bg-caution-200/50 px-1">/api/cbir/search/upload</code>。
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-ink-700">
                  Top K: <span className="font-mono text-ink-500">{topK}</span>
                </label>
                <input
                  type="range"
                  min="5"
                  max="100"
                  step="5"
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="mt-2 w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-ink-700">
                  相似度阈值: <span className="font-mono text-ink-500">{threshold.toFixed(2)}</span>
                </label>
                <input
                  type="range"
                  min="0.5"
                  max="0.99"
                  step="0.01"
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="mt-2 w-full"
                />
              </div>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="mt-4 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700">
            {error}
          </div>
        )}
      </section>

      {/* Search Results */}
      {hasSearched && (
        <section className="dossier-panel rounded-[2rem] p-6">
          <CBIRResults
            results={results}
            caseId={selectedCase.case_id}
            onSelectPanel={setSelectedPanel}
          />
        </section>
      )}

      {/* Panel Detail Drawer */}
      {selectedPanel && (
        <PanelDetailDrawer
          panel={selectedPanel}
          caseId={selectedCase.case_id}
          onClose={() => setSelectedPanel(null)}
        />
      )}
    </div>
  );
}

function PanelDetailDrawer({ panel, caseId, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-ink-900/50" onClick={onClose} />
      <div className="w-full max-w-2xl overflow-y-auto bg-paper-50 shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-ink-900/10 bg-paper-50 px-6 py-4">
          <h3 className="font-display text-xl font-semibold">Panel 详情</h3>
          <button type="button" onClick={onClose} className="btn-ghost">
            <FiX />
          </button>
        </div>

        <div className="space-y-6 p-6">
          {/* Image Preview */}
          <div className="overflow-hidden rounded-2xl border border-ink-900/10 bg-ink-50">
            <img
              src={`/api/cases/${encodeURIComponent(caseId)}/visual/images/${panel.image_path}`}
              alt={panel.panel_id}
              className="w-full object-contain"
              onError={(e) => {
                e.target.style.display = 'none';
              }}
            />
          </div>

          {/* Metadata */}
          <div className="space-y-3">
            <div>
              <p className="text-xs font-medium text-ink-500">Panel ID</p>
              <p className="mt-1 font-mono text-sm text-ink-900">{panel.panel_id}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-ink-500">Figure ID</p>
              <p className="mt-1 font-mono text-sm text-ink-900">{panel.figure_id || '-'}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-ink-500">Case ID</p>
              <p className="mt-1 font-mono text-sm text-ink-900">{panel.case_id}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-ink-500">相似度</p>
              <p className="mt-1 text-lg font-semibold text-ink-900">
                {(panel.similarity * 100).toFixed(2)}%
              </p>
            </div>
            {panel.label && (
              <div>
                <p className="text-xs font-medium text-ink-500">Label</p>
                <p className="mt-1 text-sm text-ink-900">{panel.label}</p>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <a
              href={`?page=visual&case=${caseId}`}
              className="btn-secondary flex-1 text-center"
            >
              在 Visual Forensics 中查看
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CBIRSearchPage;
