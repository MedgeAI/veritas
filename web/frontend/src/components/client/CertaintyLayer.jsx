/**
 * CertaintyLayer — Three-layer certainty display.
 *
 * Props: { fact: string, inference: string, suggestion: string }
 * Three sections with colored labels:
 * - 事实 Fact (ink-900)
 * - AI推断 Inference (purple #5a4f7c)
 * - 建议 Suggestion (green #5a6b46)
 *
 * Reference: prototype IssuePage layers
 */

export default function CertaintyLayer({ fact, inference, suggestion }) {
  return (
    <div className="space-y-10">
      {/* Fact layer */}
      {fact && (
        <div>
          <div className="mb-4 flex items-baseline gap-2.5 border-b border-paper-200 pb-3">
            <span className="h-2 w-2 rounded-full bg-ink-900" />
            <span className="text-[13px] font-medium text-ink-900">事实</span>
            <span className="font-display text-[11px] italic text-ink-500">
              Fact · what was found
            </span>
          </div>
          <div className="rounded-sm bg-white p-5 text-[13.5px] leading-[1.75] text-ink-900">
            {fact}
          </div>
        </div>
      )}

      {/* Inference layer */}
      {inference && (
        <div>
          <div className="mb-4 flex items-baseline gap-2.5 border-b border-[#e0d8ed] pb-3">
            <span className="h-2 w-2 rounded-full bg-[#5a4f7c]" />
            <span className="text-[13px] font-medium text-[#5a4f7c]">AI 推断</span>
            <span className="font-display text-[11px] italic text-ink-500">
              Inference · interpretation
            </span>
          </div>
          <div className="rounded-sm border border-[#e0d8ed] border-l-2 border-l-[#7a6b9c] bg-[#f6f4fa] p-5 text-[13.5px] leading-[1.75] text-ink-900">
            {inference}
          </div>
        </div>
      )}

      {/* Suggestion layer */}
      {suggestion && (
        <div>
          <div className="mb-4 flex items-baseline gap-2.5 border-b border-[#d8e3c7] pb-3">
            <span className="h-2 w-2 rounded-full bg-[#5a6b46]" />
            <span className="text-[13px] font-medium text-[#5a6b46]">建议</span>
            <span className="font-display text-[11px] italic text-ink-500">
              Suggestion · actionable
            </span>
          </div>
          <div className="rounded-sm border border-[#d8e3c7] border-l-2 border-l-[#5a6b46] bg-[#f3f6ed] p-5 text-[13.5px] leading-[1.75] text-ink-900">
            {suggestion}
          </div>
        </div>
      )}
    </div>
  );
}
