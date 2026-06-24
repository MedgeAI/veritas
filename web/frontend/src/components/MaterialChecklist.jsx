import { FiAlertTriangle, FiCheckCircle, FiCopy, FiDatabase, FiFile, FiMail, FiSettings } from 'react-icons/fi';
import { useState } from 'react';
import StatusPill from './StatusPill.jsx';

function FiCode(props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="1em"
      height="1em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  );
}

const MATERIAL_CONFIG = [
  {
    key: 'pdf',
    label: '论文 PDF',
    icon: FiFile,
    okStatus: 'ok',
    missingLabel: '缺失',
    missingTone: 'risk',
    okTone: 'ok',
    weight: 30,
  },
  {
    key: 'source_data',
    label: 'Source Data',
    icon: FiDatabase,
    okStatus: 'ok',
    missingLabel: '缺失',
    missingTone: 'risk',
    okTone: 'ok',
    weight: 30,
  },
  {
    key: 'code',
    label: '代码',
    icon: FiCode,
    okStatus: 'provided',
    missingLabel: '未提供',
    missingTone: 'warn',
    okTone: 'ok',
    weight: 20,
  },
  {
    key: 'environment',
    label: '环境文件',
    icon: FiSettings,
    okStatus: 'provided',
    missingLabel: '未提供',
    missingTone: 'warn',
    okTone: 'ok',
    weight: 20,
  },
];

function buildEmailTemplate(caseId, missingItems) {
  const lines = missingItems.map((item) => `- ${item.label}（${item.missingLabel}：${item.detail}）`);
  return `同学你好，

在投稿前自查过程中，发现以下材料尚未提供完整，请尽快补充：

${lines.join('\n')}

请提供上述材料后，我将重新运行审查流程。

谢谢！`;
}

function ScoreRing({ score }) {
  const radius = 32;
  const circumference = 2 * Math.PI * radius;
  const dashoffset = circumference - (score / 100) * circumference;
  const color =
    score >= 80 ? 'text-green-600' : score >= 50 ? 'text-amber-500' : 'text-red-500';
  return (
    <div className="relative grid h-20 w-20 place-items-center">
      <svg className="absolute inset-0 h-full w-full -rotate-90" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r={radius} fill="none" stroke="currentColor" strokeWidth="6" className="text-ink-900/8" />
        <circle
          cx="40"
          cy="40"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={dashoffset}
          strokeLinecap="round"
          className={`transition-[stroke-dashoffset] duration-500 ${color}`}
        />
      </svg>
      <span className={`font-display text-xl font-bold tabular-nums ${color}`}>{score}</span>
    </div>
  );
}

function MaterialRow({ config, data, onCopy }) {
  const isOk = data.status === config.okStatus;
  const Icon = config.icon;
  return (
    <div className="flex items-start gap-4 rounded-2xl bg-white/50 px-4 py-3">
      <div
        className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${
          isOk ? 'bg-signal-100 text-signal-700' : 'bg-risk-100 text-risk-700'
        }`}
      >
        <Icon className="text-lg" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink-900">{config.label}</span>
          <StatusPill tone={isOk ? config.okTone : config.missingTone}>
            {isOk ? (
              <span className="flex items-center gap-1">
                <FiCheckCircle aria-hidden="true" /> 已提供
              </span>
            ) : (
              <span className="flex items-center gap-1">
                <FiAlertTriangle aria-hidden="true" /> {config.missingLabel}
              </span>
            )}
          </StatusPill>
        </div>
        <p className="mt-1 font-mono text-xs text-ink-500 break-words">{data.detail}</p>
      </div>
      {!isOk && onCopy && (
        <button
          type="button"
          className="shrink-0 rounded-lg border border-ink-900/10 p-2 text-ink-500 transition hover:bg-ink-900/5 hover:text-ink-900"
          title="复制补交请求邮件模板"
          aria-label="复制补交请求邮件模板"
          onClick={onCopy}
        >
          <FiMail aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

function MaterialChecklist({ caseId, materials }) {
  const [copiedKey, setCopiedKey] = useState(null);

  if (!materials) return null;

  const missingItems = MATERIAL_CONFIG.filter((config) => {
    const data = materials[config.key];
    return data && data.status !== config.okStatus;
  }).map((config) => ({
    ...config,
    detail: materials[config.key]?.detail || '',
  }));

  async function handleCopy(item) {
    const template = buildEmailTemplate(caseId, [item]);
    try {
      await navigator.clipboard.writeText(template);
      setCopiedKey(item.key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch {
      // Fallback: do nothing if clipboard API unavailable
    }
  }

  return (
    <section className="dossier-panel rounded-[2rem] p-5">
      <div className="flex items-center justify-between border-b border-ink-900/10 pb-4">
        <div>
          <p className="metric-label">材料完整性</p>
          <p className="mt-1 text-xs text-ink-500">
            {missingItems.length === 0
              ? '所有必要材料已提供'
              : `${missingItems.length} 项材料待补充`}
          </p>
        </div>
        <ScoreRing score={materials.completeness_score ?? 0} />
      </div>

      <div className="mt-4 space-y-2">
        {MATERIAL_CONFIG.map((config) => {
          const data = materials[config.key];
          if (!data) return null;
          return (
            <MaterialRow
              key={config.key}
              config={config}
              data={data}
              onCopy={
                data.status !== config.okStatus
                  ? () => handleCopy({ ...config, detail: data.detail })
                  : undefined
              }
            />
          );
        })}
      </div>

      {copiedKey && (
        <div className="mt-3 rounded-xl bg-signal-100 px-3 py-2 text-xs text-signal-700">
          <FiCopy className="mr-1 inline" aria-hidden="true" />
          邮件模板已复制到剪贴板
        </div>
      )}
    </section>
  );
}

export default MaterialChecklist;
