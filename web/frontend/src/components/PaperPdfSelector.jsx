import { useEffect, useState } from 'react';
import { FiFileText, FiX } from 'react-icons/fi';

const SIZE_FORMATTER = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes >= 1024 * 1024) return `${SIZE_FORMATTER.format(bytes / (1024 * 1024))} MB`;
  return `${SIZE_FORMATTER.format(bytes / 1024)} KB`;
}

export default function PaperPdfSelector({ open, candidates, onCancel, onConfirm }) {
  const [selected, setSelected] = useState('');

  useEffect(() => {
    if (open) setSelected('');
  }, [open, candidates]);

  if (!open) return null;

  const pdfs = candidates || [];

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink-900/45 px-4">
      <div className="w-full max-w-xl rounded-sm bg-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="paper-pdf-selector-title">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id="paper-pdf-selector-title" className="font-display text-xl font-semibold text-ink-900">
              检测到多个 PDF 文件
            </h2>
            <p className="mt-1 text-sm text-ink-500">请选择将作为论文正文解析的 PDF。</p>
          </div>
          <button
            type="button"
            className="rounded-sm p-1 text-ink-400 transition hover:bg-ink-50 hover:text-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
            onClick={onCancel}
            aria-label="关闭"
          >
            <FiX aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-2">
          {pdfs.map((candidate) => {
            const path = candidate.path || candidate.relative_path || candidate.name;
            return (
              <label
                key={path}
                className={`flex cursor-pointer items-center gap-3 rounded-sm border p-3 transition ${
                  selected === path
                    ? 'border-accent-500 bg-accent-50'
                    : 'border-ink-900/10 hover:border-ink-900/25'
                }`}
              >
                <input
                  type="radio"
                  name="paper_pdf"
                  className="h-4 w-4 accent-accent-500"
                  value={path}
                  checked={selected === path}
                  onChange={() => setSelected(path)}
                />
                <FiFileText className="h-4 w-4 shrink-0 text-ink-400" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-800">{path}</span>
                <span className="shrink-0 font-mono text-xs text-ink-400">{formatSize(candidate.size_bytes)}</span>
              </label>
            );
          })}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={!selected}
            onClick={() => selected && onConfirm(selected)}
          >
            确认选择
          </button>
        </div>
      </div>
    </div>
  );
}
