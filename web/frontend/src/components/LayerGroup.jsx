import { useCallback, useState } from 'react';
import { FiChevronDown, FiChevronRight } from 'react-icons/fi';
import { LAYER_METADATA } from '../utils/layers.js';

/**
 * LayerGroup — collapsible section for a report layer.
 *
 * Renders a header with title, count badge, and expand/collapse toggle.
 * Children (finding items) are rendered inside the collapsible body.
 *
 * @param {Object} props
 * @param {'layer_1'|'layer_2'|'layer_3'} props.layer - Layer key
 * @param {Array} props.findings - Findings in this layer
 * @param {React.ReactNode} props.children - Render prop or children; receives `findings` if function
 * @param {string} [props.className] - Extra CSS classes
 */
export default function LayerGroup({ layer, findings, children, className = '' }) {
  const meta = LAYER_METADATA[layer] || LAYER_METADATA.layer_3;
  const [open, setOpen] = useState(meta.defaultOpen);

  const toggle = useCallback(() => setOpen((v) => !v), []);

  const count = Array.isArray(findings) ? findings.length : 0;

  // Accent colors per layer
  const accentClass =
    layer === 'layer_1'
      ? 'border-risk-300/40 bg-risk-50/30'
      : layer === 'layer_2'
        ? 'border-amber-300/40 bg-amber-50/20'
        : 'border-ink-900/10 bg-ink-50/30';

  const headerAccent =
    layer === 'layer_1'
      ? 'text-risk-700'
      : layer === 'layer_2'
        ? 'text-amber-700'
        : 'text-ink-500';

  const badgeAccent =
    layer === 'layer_1'
      ? 'bg-risk-100 text-risk-700'
      : layer === 'layer_2'
        ? 'bg-amber-100 text-amber-700'
        : 'bg-ink-100 text-ink-500';

  return (
    <div className={`rounded-2xl border ${accentClass} ${className}`}>
      {/* Header */}
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left transition hover:bg-white/40"
      >
        <span className={`shrink-0 ${headerAccent}`} aria-hidden="true">
          {open ? <FiChevronDown className="h-4 w-4" /> : <FiChevronRight className="h-4 w-4" />}
        </span>
        <span className="flex min-w-0 flex-1 items-center gap-2">
          <span className={`font-mono text-[10px] font-semibold uppercase ${headerAccent}`}>
            {meta.label}
          </span>
          <span className="font-display text-sm font-semibold text-ink-900">
            {meta.title}
          </span>
          <span className={`rounded-full px-2 py-0.5 font-mono text-[10px] font-medium ${badgeAccent}`}>
            {count}
          </span>
        </span>
      </button>

      {/* Collapsible body */}
      {open && (
        <div className="border-t border-ink-900/5 px-4 pb-4 pt-3">
          {count === 0 ? (
            <p className="py-2 text-sm text-ink-400">暂无发现</p>
          ) : typeof children === 'function' ? (
            children(findings)
          ) : (
            children
          )}
        </div>
      )}
    </div>
  );
}
