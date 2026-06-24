import { FiAlertTriangle, FiX } from 'react-icons/fi';
import { visualImageUrl } from '../services/api.js';

/**
 * Detail drawer for an overlap relationship.
 * Shows score, transform type, area ratios, evidence images, and review checklist.
 *
 * @param {object} props
 * @param {object|null} props.relationship - overlap relationship object
 * @param {string} props.caseId - case ID for image URL resolution
 * @param {Function} props.onClose - close callback
 */
export default function OverlapDetailDrawer({ relationship, caseId, onClose }) {
  if (!relationship) return null;

  const {
    relationship_id = '',
    source_panel_id = '',
    target_panel_id = '',
    score = 0,
    verification_method = '',
    transform_type = '',
    inlier_count = 0,
    overlap_area_ratio_source = 0,
    overlap_area_ratio_target = 0,
    overlay_path = '',
    flip_detected = false,
  } = relationship;

  const riskBadge = score >= 0.7
    ? { label: 'HIGH', color: 'bg-red-100 text-red-800' }
    : score >= 0.4
    ? { label: 'MEDIUM', color: 'bg-amber-100 text-amber-800' }
    : { label: 'LOW', color: 'bg-gray-100 text-gray-800' };

  return (
    <div role="dialog" aria-modal="true" style={{ overscrollBehavior: 'contain' }} className="fixed inset-y-0 right-0 w-96 bg-white shadow-xl border-l border-gray-200 z-50 overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">复用详情</h3>
          {relationship_id && (
            <span className="mt-0.5 block font-mono text-[10px] text-gray-400">{relationship_id}</span>
          )}
          <span className={`inline-block mt-1 text-xs px-2 py-0.5 rounded ${riskBadge.color}`}>
            {riskBadge.label}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          aria-label="Close"
        >
          <FiX className="text-lg" aria-hidden="true" />
        </button>
      </div>

      {/* Details */}
      <div className="px-4 py-3 space-y-4">
        {/* Panel pair */}
        <div className="text-xs space-y-1">
          <div><span className="text-gray-500">Source:</span> <code className="text-blue-700">{source_panel_id}</code></div>
          <div><span className="text-gray-500">Target:</span> <code className="text-blue-700">{target_panel_id}</code></div>
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <MetricCard label="Score" value={score.toFixed(3)} />
          <MetricCard label="Inliers" value={inlier_count} />
          <MetricCard label="Overlap (src)" value={`${(overlap_area_ratio_source * 100).toFixed(1)}%`} />
          <MetricCard label="Overlap (tgt)" value={`${(overlap_area_ratio_target * 100).toFixed(1)}%`} />
          <MetricCard label="Transform" value={transform_type || '—'} />
          <MetricCard label="Method" value={verification_method || '—'} />
        </div>

        {flip_detected && (
          <div className="text-xs bg-purple-50 text-purple-800 px-2 py-1 rounded flex items-center gap-1">
            <FiAlertTriangle className="shrink-0" aria-hidden="true" />
            水平翻转检出
          </div>
        )}

        {/* Evidence image */}
        {overlay_path && caseId && (
          <div>
            <h4 className="text-xs font-medium text-gray-700 mb-1">Overlay Evidence</h4>
            <img
              src={visualImageUrl(caseId, overlay_path)}
              alt="Overlap overlay"
              width="400"
              height="300"
              className="w-full rounded border border-gray-200"
              loading="lazy"
            />
          </div>
        )}

        {/* Review checklist */}
        <div>
          <h4 className="text-xs font-medium text-gray-700 mb-2">Manual Review Checklist</h4>
          <ul className="text-xs space-y-1.5">
            <ReviewItem text="两个 panel 是否声称代表不同实验条件、样本或时间点？" name="manual_review_item_0" />
            <ReviewItem text="图注或方法是否声明 shared control / same field of view？" name="manual_review_item_1" />
            <ReviewItem text="作者能否提供原始显微图、仪器导出文件或未裁剪图？" name="manual_review_item_2" />
            <ReviewItem text="两个 panel 的 figure label 是否暗示它们来自不同的实验？" name="manual_review_item_3" />
          </ul>
        </div>

        {/* Benign explanations */}
        <div>
          <h4 className="text-xs font-medium text-gray-700 mb-2">Benign Explanations</h4>
          <ul className="text-xs text-gray-600 space-y-1 list-disc list-inside">
            <li>可能是同一原始视野的不同通道或合法 shared control</li>
            <li>某些标准化实验流程中同一对照图像重复展示是常见做法</li>
            <li>图像可能在出版组装过程中被意外复用为占位符</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value }) {
  return (
    <div className="bg-gray-50 rounded px-2 py-1.5">
      <div className="text-gray-500">{label}</div>
      <div className="font-mono font-medium text-gray-900">{value}</div>
    </div>
  );
}

function ReviewItem({ text, name }) {
  return (
    <li className="flex items-start gap-1.5">
      <label className="flex items-start gap-1.5 cursor-pointer">
        <input type="checkbox" name={name} defaultChecked={false} onChange={() => {}} className="mt-0.5 h-3 w-3 rounded border-gray-300" />
        <span className="text-gray-700">{text}</span>
      </label>
    </li>
  );
}
