import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FiArrowRight, FiLock, FiPlay, FiShield, FiUploadCloud, FiX } from 'react-icons/fi';
import { createCase, submitAudit, uploadInputsParallel } from '../services/api.js';
import ReproducibilityTierPicker from '../components/ReproducibilityTierPicker.jsx';
import SecurityTierPicker from '../components/SecurityTierPicker.jsx';
import ServiceTierPicker from '../components/ServiceTierPicker.jsx';

function FileStatus({ status, progress }) {
  if (status === 'done') return <span className="text-green-600">done</span>;
  if (typeof status === 'string' && status.startsWith('error:')) return <span className="text-red-500" title={status}>failed</span>;
  if (status === 'uploading') {
    return progress != null ? <span className="text-signal-600">{progress}%</span> : <span className="text-signal-400">…</span>;
  }
  return null;
}

const ACCEPTED_EXTENSIONS = '.pdf,.xlsx,.xlsm,.csv,.tsv,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.zip,.tar,.gz,.tgz';
const ACCEPTED_EXT_SET = new Set(['pdf', 'xlsx', 'xlsm', 'csv', 'tsv', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp', 'zip', 'tar', 'gz', 'tgz']);
const MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024;

function formatMB(bytes) {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

const DEFAULT_PARAMS = {
  agent_mode: 'full',
  fresh: true,
  force: true,
  agent_timeout_seconds: 600,
  agent_max_retries: 1,
};

const FILE_SIZE_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
});

function NewAuditPage({ onCaseCreated, onRunStarted, onNavigate, selectedCase, selectedRunId }) {
  const isExistingCase = Boolean(selectedCase);
  const [form, setForm] = useState({
    case_id: '',
    paper_title: '',
    owner: 'operator',
  });
  const [params, setParams] = useState(DEFAULT_PARAMS);
  const [reproducibilityTier, setReproducibilityTier] = useState('full');
  const [securityTier, setSecurityTier] = useState('confidential');
  const [serviceTier, setServiceTier] = useState('full');
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState({});
  const [extractingTitle, setExtractingTitle] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [fileErrors, setFileErrors] = useState(new Map());
  const [hasUnsavedFiles, setHasUnsavedFiles] = useState(false);
  const [navGuardTarget, setNavGuardTarget] = useState(null);
  const [fileStatuses, setFileStatuses] = useState(new Map());
  const [overallProgress, setOverallProgress] = useState(-1);
  const abortRef = useRef(null);
  const fileInputRef = useRef(null);
  const dirInputRef = useRef(null);
  const dragCounter = useRef(0);
  const errorRef = useRef(null);

  useEffect(() => {
    if (error && errorRef.current) {
      errorRef.current.focus({ preventScroll: true });
    }
  }, [error]);

  useEffect(() => {
    if (!hasUnsavedFiles) return;
    function handler(e) {
      e.preventDefault();
      e.returnValue = '';
    }
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasUnsavedFiles]);

  const pdfCount = useMemo(() => files.filter((file) => file.name.toLowerCase().endsWith('.pdf')).length, [files]);

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateParam(key, value) {
    setParams((current) => ({ ...current, [key]: value }));
  }

  // addFiles uses functional state updater for setFileErrors so it doesn't
  // close over fileErrors — rapid successive drops no longer clobber each
  // other's validation state.  No dependency on state means identity is
  // stable across renders, which also satisfies handleDrop's empty deps.
  const addFiles = useCallback((newFiles) => {
    const incoming = Array.from(newFiles);
    if (!incoming.length) return;

    const validFiles = [];
    const newErrors = new Map();

    for (const file of incoming) {
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (!ext || !ACCEPTED_EXT_SET.has(ext)) {
        newErrors.set(file.name, {
          name: file.name,
          size: file.size,
          reason: '不支持的文件类型',
          detail: '允许的类型：PDF, XLSX, CSV, TSV, 图片(PNG/JPG/TIFF/BMP/WEBP), ZIP/TAR.GZ',
        });
      } else if (file.size > MAX_FILE_SIZE_BYTES) {
        newErrors.set(file.name, {
          name: file.name,
          size: file.size,
          reason: '文件过大',
          detail: `最大 200 MB。当前：${formatMB(file.size)}。`,
        });
      } else {
        validFiles.push(file);
        newErrors.delete(file.name);
      }
    }

    if (validFiles.length) {
      setFiles((current) => {
        const existingKeys = new Set(current.map((f) => f.webkitRelativePath || f.name));
        const unique = validFiles.filter((f) => !existingKeys.has(f.webkitRelativePath || f.name));
        return [...current, ...unique];
      });
      setHasUnsavedFiles(true);
    }
    setFileErrors((prev) => {
      const next = new Map(prev);
      for (const [k, v] of newErrors) next.set(k, v);
      for (const f of validFiles) next.delete(f.name);
      return next;
    });
  }, []);

  function removeFile(index) {
    setFiles((current) => current.filter((_, i) => i !== index));
  }

  const handleDragEnter = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.types.includes('Files')) setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  }, [addFiles]);

  function guardedNavigate(page) {
    if (hasUnsavedFiles) {
      setNavGuardTarget(page);
      return;
    }
    onNavigate(page);
  }

  function handleCancelUpload() {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
    }
  }

  async function handleStart() {
    setBusy(true);
    setError('');
    try {
      // 获取或创建 case
      let caseId;
      if (isExistingCase) {
        caseId = selectedCase.case_id;
      } else {
        const payload = {
          case_id: form.case_id || undefined,
          paper_title: form.paper_title || undefined,
          owner: form.owner || 'operator',
          reproducibility_tier: reproducibilityTier,
        };
        const record = await createCase(payload);
        caseId = record.case_id;
        onCaseCreated(record);
      }

      // 上传文件
      if (!files.length) {
        throw new Error('请至少上传一个 PDF 或材料文件');
      }
      if (!pdfCount) {
        throw new Error('输入中必须包含论文 PDF');
      }
      setUploadProgress({});
      setFileStatuses(new Map());
      setOverallProgress(0);

      const { promise, abortAll } = uploadInputsParallel(caseId, files, {
        concurrency: 3,
        onProgress: (pct) => setOverallProgress(pct),
        onFileProgress: (file, pct) => {
          const fileKey = file.webkitRelativePath || file.name;
          setUploadProgress((prev) => ({ ...prev, [fileKey]: pct }));
          setFileStatuses((prev) => new Map(prev).set(fileKey, 'uploading'));
        },
        onFileComplete: (file, result) => {
          const fileKey = file.webkitRelativePath || file.name;
          setUploadProgress((prev) => ({ ...prev, [fileKey]: 100 }));
          setFileStatuses((prev) => new Map(prev).set(fileKey, 'done'));
          const isPdf = file.name.toLowerCase().endsWith('.pdf');
          if (isPdf && result?.case?.paper_title && !form.paper_title) {
            setForm((prev) => ({ ...prev, paper_title: result.case.paper_title }));
            setExtractingTitle(false);
          }
        },
        onFileError: (file, err) => {
          const fileKey = file.webkitRelativePath || file.name;
          setFileStatuses((prev) => new Map(prev).set(fileKey, `error: ${err.message}`));
        },
      });
      abortRef.current = abortAll;

      // Show "extracting title" for first PDF if no title entered
      const firstPdf = files.find((f) => f.name.toLowerCase().endsWith('.pdf'));
      if (firstPdf && !form.paper_title) setExtractingTitle(true);

      const { errors: uploadErrors } = await promise;
      abortRef.current = null;
      setExtractingTitle(false);
      setOverallProgress(100);

      if (uploadErrors.length === files.length) {
        throw new Error(`所有文件上传失败（${uploadErrors.length} 个文件），请检查网络后重试`);
      }
      if (uploadErrors.length > 0) {
        setError(`${uploadErrors.length} 个文件上传失败，其余文件将继续审查`);
      }

      // 启动审查
      const job = await submitAudit(caseId, {
        options: {
          ...params,
          agent_timeout_seconds: Number(params.agent_timeout_seconds || 600),
          agent_max_retries: Number(params.agent_max_retries || 1),
        },
      }, reproducibilityTier);
      setHasUnsavedFiles(false);
      onRunStarted(job);
    } catch (nextError) {
      const msg = nextError.message || String(nextError);
      setError(msg.endsWith('重试') ? msg : `${msg}，请稍后重试`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="font-display text-2xl font-semibold text-ink-900">
          {isExistingCase ? '补充材料并重新审查' : '新建审查'}
        </h1>
        <p className="mt-2 text-sm text-ink-500">
          {isExistingCase
            ? `为 ${selectedCase.paper_title || selectedCase.case_id} 追加材料，启动完整审查流程。`
            : '上传论文 PDF 和补充材料，启动 Agent 自动审查流程。'}
        </p>
      </div>

      <section className="dossier-panel rounded-2xl p-6">
        {/* Existing case info */}
        {isExistingCase && (
          <div className="mb-6 rounded-2xl bg-paper-100/50 p-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="font-semibold text-ink-900">{selectedCase.paper_title || selectedCase.case_id}</p>
                <p className="mt-1 font-mono text-xs text-ink-500">{selectedCase.case_id}</p>
                {selectedRunId && <p className="mt-1 text-xs text-ink-500">最近运行：{selectedRunId}</p>}
              </div>
              <span className="rounded-full bg-ink-900/5 px-3 py-1 text-xs font-medium text-ink-500">
                {selectedCase.status || 'Draft'}
              </span>
            </div>
          </div>
        )}

        {/* Form fields - only for new case */}
        {!isExistingCase && (
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
        )}

        <div className="mt-5">
          <span className="metric-label block">Input Materials</span>
          <div
            className={`mt-2 rounded-2xl border-2 border-dashed p-6 transition-colors ${
              isDragging
                ? 'border-signal-500 bg-signal-100/40 [user-select:none]'
                : 'border-ink-900/15 bg-white/45 hover:border-ink-900/25'
            }`}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            <div className="flex flex-col items-center gap-4 text-center">
              <div className="grid h-14 w-14 place-items-center rounded-2xl bg-signal-100 text-signal-700">
                <FiUploadCloud className="text-2xl" aria-hidden="true" />
              </div>
              <div>
                <p className="font-semibold text-ink-900">
                  {isDragging
                    ? '松开以上传文件'
                    : isExistingCase
                    ? '拖放追加材料'
                    : '拖放文件到这里'}
                </p>
                <p className="mt-1 text-sm text-ink-500">
                  {isExistingCase ? '追加的材料将与已有文件一起用于重新审查。' : null}
                  或{' '}
                  <button
                    type="button"
                    className="font-medium text-signal-600 underline-offset-2 hover:underline"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={busy}
                  >
                    {isExistingCase ? '追加文件' : '选择文件'}
                  </button>
                  {' · '}
                  <button
                    type="button"
                    className="font-medium text-signal-600 underline-offset-2 hover:underline"
                    onClick={() => dirInputRef.current?.click()}
                    disabled={busy}
                  >
                    选择目录
                  </button>
                </p>
                <p className="mt-2 text-xs text-ink-500">PDF、数据文件、图片、压缩包</p>
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_EXTENSIONS}
              aria-label="选择文件上传"
              className="hidden"
              onChange={(event) => { addFiles(event.target.files); event.target.value = ''; }}
              disabled={busy}
            />
            <input
              ref={dirInputRef}
              type="file"
              multiple
              accept={ACCEPTED_EXTENSIONS}
              aria-label="选择目录上传"
              className="hidden"
              {...({ webkitdirectory: '', directory: '' })}
              onChange={(event) => { addFiles(event.target.files); event.target.value = ''; }}
              disabled={busy}
            />

            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <span className="mono-chip">files: {files.length}</span>
              <span className="mono-chip">pdf: {pdfCount}</span>
              {pdfCount === 0 && files.length > 0 && <span className="mono-chip text-red-600">需要至少一个 PDF 文件</span>}
              <span className="mono-chip">mode: real MinerU / LLM</span>
            </div>

            {files.length || fileErrors.size ? (
              <div className="mt-4 rounded-2xl bg-paper-100/70 p-3">
                {overallProgress >= 0 && overallProgress < 100 && (
                  <div className="mb-3">
                    <div className="mb-1 flex items-center justify-between text-xs font-mono">
                      <span className="text-ink-500">总进度</span>
                      <span className="text-signal-600">{overallProgress}%</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-ink-900/10">
                      <div className="h-full rounded-full bg-signal-500 transition-[width] duration-300" style={{ width: `${overallProgress}%` }} />
                    </div>
                  </div>
                )}
                <div className="max-h-52 overflow-auto" role="list" aria-label="已选文件列表">
                {files.map((file, index) => {
                  const fileKey = file.webkitRelativePath || file.name;
                  return (
                    <div key={`${file.name}-${file.size}-${file.lastModified}`} className="group flex items-center justify-between gap-4 rounded-lg px-2 py-1.5 font-mono text-xs transition hover:bg-white/50" role="listitem">
                      <span className="min-w-0 truncate text-ink-500">{fileKey}</span>
                      <span className="flex shrink-0 items-center gap-2 tabular-nums">
                        <FileStatus status={fileStatuses.get(fileKey)} progress={uploadProgress[fileKey]} />
                        <span className="text-ink-500">{FILE_SIZE_FORMATTER.format(Math.ceil(file.size / 1024))} KB</span>
                        {!busy && (
                          <button
                            type="button"
                            className="rounded p-0.5 text-ink-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:text-red-500"
                            onClick={() => removeFile(index)}
                            aria-label={`移除 ${file.name}`}
                          >
                            <FiX className="text-sm" aria-hidden="true" />
                          </button>
                        )}
                      </span>
                    </div>
                  );
                })}
                {Array.from(fileErrors.entries()).map(([key, err]) => (
                  <div key={`err-${key}`} className="rounded-lg bg-red-50 px-3 py-2 font-mono text-xs text-red-600" role="alert">
                    <div className="flex justify-between gap-4">
                      <span className="min-w-0 truncate font-semibold">{err.name}</span>
                      <span className="tabular-nums">{FILE_SIZE_FORMATTER.format(Math.ceil(err.size / 1024))} KB</span>
                    </div>
                    <div className="mt-1">{err.reason}：{err.detail}</div>
                  </div>
                ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <label>
            <span className="metric-label">审查模式</span>
            <select className="input-field mt-2" name="agent_mode" value={params.agent_mode} onChange={(event) => updateParam('agent_mode', event.target.value)}>
              <option value="full">完整审查</option>
              <option value="review">复核模式</option>
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

        <ReproducibilityTierPicker
          value={reproducibilityTier}
          onChange={setReproducibilityTier}
        />

        <div className="mt-8">
          <ServiceTierPicker value={serviceTier} onChange={setServiceTier} />
        </div>

        <div className="mt-8">
          <SecurityTierPicker value={securityTier} onChange={setSecurityTier} />
        </div>

        {error ? (
          <div ref={errorRef} tabIndex={-1} className="mt-5 rounded-2xl border border-risk-300/45 bg-risk-100/70 p-4 text-sm text-risk-700" role="alert" aria-live="polite">
            {error}
          </div>
        ) : null}

        {/* 提交摘要栏 — 原型风格深色条 */}
        <div className="mt-6 flex items-center gap-4 rounded-2xl bg-ink-900 px-5 py-4">
          <div className="flex-1 min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-widest text-paper-300">
              即将提交
            </div>
            <div className="mt-0.5 font-display text-base text-paper-50 leading-snug">
              {serviceTier === 'basic' ? '基础扫描' : serviceTier === 'full' ? '完整认证' : '认证 + 修复'}
              <span className="mx-1.5 text-paper-300">·</span>
              {securityTier === 'standard' ? '标准级' : securityTier === 'confidential' ? '加密级' : '私有级'}
              <span className="mx-1.5 text-paper-300">·</span>
              {reproducibilityTier === 'full' ? 'Full' : reproducibilityTier === 'partial' ? 'Partial' : reproducibilityTier === 'code_only' ? 'Code-only' : 'Static'} 复现等级
            </div>
            <div className="mt-1 flex items-center gap-1.5 text-[11px] text-paper-300">
              {securityTier === 'standard' ? (
                <>
                  <FiShield aria-hidden="true" className="h-3 w-3 shrink-0" />
                  云端 API 零数据保留 · 24h 自销
                </>
              ) : securityTier === 'confidential' ? (
                <>
                  <FiLock aria-hidden="true" className="h-3 w-3 shrink-0" />
                  端到端加密 · 作者持有密钥
                </>
              ) : (
                <>
                  <FiLock aria-hidden="true" className="h-3 w-3 shrink-0" />
                  私有 VPC 部署 · 数据不出网络
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            className="shrink-0 inline-flex items-center gap-2 rounded-full bg-paper-50 px-5 py-2.5 text-sm font-semibold text-ink-900 transition hover:-translate-y-0.5 hover:shadow-lg active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
            onClick={handleStart}
            disabled={busy || overallProgress >= 0}
          >
            <FiPlay aria-hidden="true" />
            {busy ? '上传中…' : serviceTier === 'basic' ? '启动扫描' : serviceTier === 'full_plus' ? '启动完整认证' : '开始核查'}
            <FiArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          {busy && abortRef.current && (
            <button type="button" className="btn-ghost text-red-600" onClick={handleCancelUpload}>
              取消上传
            </button>
          )}
          {isExistingCase && !busy && (
            <button type="button" className="btn-secondary" onClick={() => guardedNavigate('mission')}>
              查看当前结果
            </button>
          )}
          <button type="button" className="btn-ghost" onClick={() => guardedNavigate('cases')} disabled={busy}>
            返回列表
          </button>
        </div>
      </section>

      {navGuardTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="关闭离开确认"
            onClick={() => setNavGuardTarget(null)}
            tabIndex={-1}
          />
          <div className="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="nav-guard-title">
            <h3 id="nav-guard-title" className="mb-3 font-display text-lg font-semibold text-ink-900">离开当前页面？</h3>
            <p className="mb-4 text-sm text-ink-500">有未上传的文件，确定要离开吗？未保存的内容将丢失。</p>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setNavGuardTarget(null)}>取消</button>
              <button
                type="button"
                className="btn-danger"
                onClick={() => { const target = navGuardTarget; setNavGuardTarget(null); onNavigate(target); }}
              >
                确定离开
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default NewAuditPage;
