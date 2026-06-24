import { useMemo, useState } from 'react';
import { FiPlay, FiUploadCloud } from 'react-icons/fi';
import MaterialChecklist from '../components/MaterialChecklist.jsx';
import { checkMaterials, createCase, submitAudit, uploadInput } from '../services/api.js';

const DEFAULT_PARAMS = {
  agent_mode: 'full',
  fresh: true,
  force: true,
  agent_timeout_seconds: 600,
  agent_max_retries: 1,
};

const LOG_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

const FILE_SIZE_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
});

function NewAuditPage({ onCaseCreated, onRunStarted, onNavigate }) {
  const [form, setForm] = useState({
    case_id: '',
    paper_title: '',
    owner: 'operator',
  });
  const [params, setParams] = useState(DEFAULT_PARAMS);
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState({});
  const [extractingTitle, setExtractingTitle] = useState(false);
  const [materials, setMaterials] = useState(null);
  const [createdCaseId, setCreatedCaseId] = useState('');

  const pdfCount = useMemo(() => files.filter((file) => file.name.toLowerCase().endsWith('.pdf')).length, [files]);

  function appendLog(message) {
    setLog((current) => [`${LOG_TIME_FORMATTER.format(new Date())} ${message}`, ...current].slice(0, 12));
  }

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateParam(key, value) {
    setParams((current) => ({ ...current, [key]: value }));
  }

  async function handleStart() {
    setBusy(true);
    setError('');
    try {
      // 创建 case
      const payload = {
        case_id: form.case_id || undefined,
        paper_title: form.paper_title || undefined,
        owner: form.owner || 'operator',
      };
      const record = await createCase(payload);
      appendLog(`created case ${record.case_id}`);
      setCreatedCaseId(record.case_id);
      onCaseCreated(record);

      // 上传文件
      if (!files.length) {
        throw new Error('请至少上传一个 PDF 或材料文件');
      }
      if (!pdfCount) {
        throw new Error('输入中必须包含论文 PDF');
      }
      setUploadProgress({});
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const fileKey = file.webkitRelativePath || file.name;
        setUploadProgress((prev) => ({ ...prev, [fileKey]: 0 }));

        // 如果是 PDF 且还没有 paper_title，显示"自动提取中..."
        const isPdf = file.name.toLowerCase().endsWith('.pdf');
        if (isPdf && !form.paper_title) {
          setExtractingTitle(true);
        }

        const result = await uploadInput(record.case_id, file, {
          onProgress: (percent) => setUploadProgress((prev) => ({ ...prev, [fileKey]: percent })),
        });

        // 从上传响应中获取更新后的 paper_title
        if (isPdf && result.case?.paper_title && !form.paper_title) {
          setForm((prev) => ({ ...prev, paper_title: result.case.paper_title }));
          setExtractingTitle(false);
          appendLog(`extracted title: ${result.case.paper_title}`);
        }

        setUploadProgress((prev) => ({ ...prev, [fileKey]: 100 }));
        appendLog(`uploaded ${fileKey}`);
      }
      setExtractingTitle(false);

      // 上传完成后获取材料完整性检查结果
      try {
        const materialsResult = await checkMaterials(record.case_id);
        setMaterials(materialsResult);
        appendLog(`materials: score ${materialsResult.completeness_score}`);
      } catch {
        // 材料检查失败不阻塞审查启动
      }

      // 启动审查
      const job = await submitAudit(record.case_id, {
        options: {
          ...params,
          agent_timeout_seconds: Number(params.agent_timeout_seconds || 600),
          agent_max_retries: Number(params.agent_max_retries || 1),
        },
      });
      appendLog('审查已启动');
      onRunStarted(job);
    } catch (nextError) {
      setError(nextError.message || String(nextError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
      <section className="dossier-panel rounded-[2rem] p-6">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="md:col-span-1">
            <span className="metric-label">Case ID (可选)</span>
            <input
              className="input-field mt-2"
              name="case_id"
              autoComplete="off"
              spellCheck={false}
              value={form.case_id}
              onChange={(event) => updateForm('case_id', event.target.value)}
              placeholder="留空自动生成…"
              disabled={busy}
            />
          </label>
          <label className="md:col-span-2">
            <span className="metric-label">Paper Title (可选)</span>
            <input
              className="input-field mt-2"
              name="paper_title"
              autoComplete="off"
              spellCheck={false}
              value={form.paper_title}
              onChange={(event) => updateForm('paper_title', event.target.value)}
              placeholder={extractingTitle ? '自动提取中…' : '留空从 PDF 提取…'}
              disabled={busy || extractingTitle}
            />
          </label>
        </div>

        <label className="mt-5 block">
          <span className="metric-label">Input Materials</span>
          <div className="mt-2 rounded-[2rem] border border-dashed border-ink-900/20 bg-white/45 p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <div className="grid h-12 w-12 place-items-center rounded-2xl bg-signal-100 text-signal-700">
                    <FiUploadCloud aria-hidden="true" />
                  </div>
                  <div>
                    <p className="font-semibold text-ink-900">上传论文 PDF、Source Data、结果文件或说明文件</p>
                    <p className="mt-1 text-sm text-ink-500">文件直接上传到后端，无需 base64 编码。</p>
                  </div>
                </div>
              </div>
              <input
                type="file"
                name="input_materials"
                multiple
                className="max-w-full text-sm"
                onChange={(event) => setFiles(Array.from(event.target.files || []))}
                disabled={busy}
              />
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <span className="mono-chip">files: {files.length}</span>
              <span className="mono-chip">pdf: {pdfCount}</span>
              <span className="mono-chip">mode: real MinerU / LLM</span>
            </div>

            {files.length ? (
              <div className="mt-4 max-h-44 overflow-auto rounded-2xl bg-paper-100/70 p-3">
                {files.map((file) => {
                  const fileKey = file.webkitRelativePath || file.name;
                  const progress = uploadProgress[fileKey];
                  const uploading = progress !== undefined && progress < 100;
                  return (
                    <div key={`${file.name}-${file.size}-${file.lastModified}`} className="flex justify-between gap-4 py-1 font-mono text-xs text-ink-500">
                      <span className="min-w-0 truncate">{fileKey}</span>
                      <span className="flex items-center gap-2 tabular-nums">
                        {uploading ? (
                          <span className="text-signal-600">{progress}%</span>
                        ) : progress === 100 ? (
                          <span className="text-green-600">done</span>
                        ) : null}
                        <span>{FILE_SIZE_FORMATTER.format(Math.ceil(file.size / 1024))} KB</span>
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        </label>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <label>
            <span className="metric-label">审查模式</span>
            <select className="input-field mt-2" name="agent_mode" value={params.agent_mode} onChange={(event) => updateParam('agent_mode', event.target.value)}>
              <option value="full">完整审查</option>
              <option value="review">复核模式</option>
              <option value="off">关闭</option>
            </select>
          </label>
          <label>
            <span className="metric-label">Timeout Seconds</span>
            <input
              className="input-field mt-2"
              name="agent_timeout_seconds"
              type="number"
              min="60"
              inputMode="numeric"
              autoComplete="off"
              value={params.agent_timeout_seconds}
              onChange={(event) => updateParam('agent_timeout_seconds', event.target.value)}
            />
          </label>
          <label>
            <span className="metric-label">Max Retries</span>
            <input
              className="input-field mt-2"
              name="agent_max_retries"
              type="number"
              min="0"
              max="3"
              inputMode="numeric"
              autoComplete="off"
              value={params.agent_max_retries}
              onChange={(event) => updateParam('agent_max_retries', event.target.value)}
            />
          </label>
        </div>

        {error ? (
          <div className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700" role="alert">
            {error}
          </div>
        ) : null}

        <div className="mt-6 flex flex-wrap gap-3">
          <button type="button" className="btn-primary" onClick={handleStart} disabled={busy}>
            <FiPlay aria-hidden="true" />
            上传并启动审查
          </button>
          <button type="button" className="btn-ghost" onClick={() => onNavigate('cases')}>
            返回列表
          </button>
        </div>
      </section>

      <aside className="space-y-6">
        {materials ? (
          <MaterialChecklist caseId={createdCaseId} materials={materials} />
        ) : null}
        {log.length > 0 ? (
          <section className="dossier-panel rounded-[2rem] p-6">
            <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-ink-500">操作日志</h3>
            <div className="mt-3 space-y-2" aria-live="polite">
              {log.map((item, index) => (
                <p key={index} className="rounded-2xl bg-white/50 px-3 py-2 font-mono text-xs text-ink-500">
                  {item}
                </p>
              ))}
            </div>
          </section>
        ) : null}
      </aside>
    </div>
  );
}

export default NewAuditPage;
