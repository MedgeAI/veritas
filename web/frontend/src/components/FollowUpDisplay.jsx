import { useState } from 'react';
import { FiClipboard, FiCheck } from 'react-icons/fi';

function FollowUpDisplay({ followUps }) {
  const [copiedIdx, setCopiedIdx] = useState(null);

  if (!followUps || followUps.length === 0) {
    return (
      <p className="text-xs text-ink-300 italic">无追问建议</p>
    );
  }

  async function handleCopy(text, idx) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx(null), 2000);
    } catch {
      // Clipboard API may not be available in all contexts
    }
  }

  return (
    <ul className="space-y-1.5">
      {followUps.map((question, idx) => (
        <li key={idx} className="flex items-start gap-2 text-xs leading-5 text-ink-700">
          <span className="mt-0.5 shrink-0 font-mono text-[10px] text-ink-300">Q{idx + 1}.</span>
          <span className="min-w-0 flex-1">{question}</span>
          <button
            type="button"
            className="shrink-0 rounded p-0.5 text-ink-300 transition-colors hover:bg-ink-900/5 hover:text-ink-700"
            title="复制问题"
            aria-label="复制问题"
            onClick={() => handleCopy(question, idx)}
          >
            {copiedIdx === idx
              ? <FiCheck size={12} className="text-signal-500" aria-hidden="true" />
              : <FiClipboard size={12} aria-hidden="true" />}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default FollowUpDisplay;
