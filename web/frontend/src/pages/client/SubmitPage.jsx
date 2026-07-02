import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FiArrowRight, FiCode, FiDatabase, FiFileText, FiLock, FiPlay, FiShield, FiUpload, FiUploadCloud, FiX } from 'react-icons/fi';
import { createCase, submitAudit, uploadInputsParallel } from '../../services/api.js';
import TierRow from '../../components/client/TierRow.jsx';
import ServiceRow from '../../components/client/ServiceRow.jsx';

const ACCEPTED_EXTENSIONS = '.pdf,.xlsx,.xlsm,.csv,.tsv,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.zip,.tar,.gz,.tgz';
const ACCEPTED_EXT_SET = new Set(['pdf', 'xlsx', 'xlsm', 'csv', 'tsv', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp', 'zip', 'tar', 'gz', 'tgz']);
const MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024;

const DEFAULT_PARAMS = {
  agent_mode: 'full',
  fresh: true,
  force: true,
  agent_timeout_seconds: 600,
  agent_max_retries: 1,
};

const FILE_SIZE_FORMATTER = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

const italicStyle = { fontStyle: 'italic' };
const subtitleStyle = { fontFamily: '"Cormorant Garamond", serif', fontStyle: 'italic' };

const TIERS = [
  { value: 'full', badge: 'A', name: 'Full', desc: '数据 + 代码 + 环境 + 完整 run 历史' },
  { value: 'partial', badge: 'B', name: 'Partial', desc: '数据 + 代码 + 环境，无 run 历史' },
  { value: 'code_only', badge: 'C', name: 'Code-only', desc: '代码 + 数据接口（数据因隐私不公开）' },
  { value: 'static', badge: 'C−', name: 'Static', desc: '仅论文 + 关键结果文件，无法重跑代码' },
];

const SECURITY_TIERS = [
  {
    id: 'standard',
    label: '标准',
    en: 'Standard',
    scenario: '已 preprint · 已投稿',
    features: ['云端 API（零数据保留）', 'TLS 1.3 + AES-256', '24 小时内销毁原始材料'],
  },
  {
    id: 'confidential',
    label: '加密',
    en: 'Confidential',
    scenario: '投稿前未公开',
    features: ['云端 API + 端到端加密', '作者持有解密密钥', '平台无法读取明文'],
  },
  {
    id: 'private',
    label: '私有',
    en: 'Private VPC',
    scenario: '高度敏感 · 专利相关',
    features: ['本地部署开源大模型', '数据完全不出客户网络', '需企业版授权'],
  },
];

const SERVICES = [
  { id: 'basic', name: '基础扫描', price: '免费', features: '静态检查 · 仅显示问题数量摘要，不含证据与建议' },
  { id: 'full', name: '完整认证', price: '¥ 680', est: '约 2–4 小时', features: '完整证据链 · 修改建议 · 正式 PDF 证书 · 期刊可在线验证 · 唯一报告编号' },
  { id: 'full_plus', name: '认证 + 修复', price: '¥ 1,280', est: '承诺 24 小时内', features: '完整认证 · 含 5 次重跑额度 · 代码问题自动修复' },
];

function formatMB(bytes) {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

function fileKeyFor(file) {
  return file.webkitRelativePath || file.name;
}

// Pure function: file → category bucket.  Lifted to module scope so its
// identity is stable across renders — safe to include in useCallback deps.
function categorizeFile(file) {
  const name = file.name.toLowerCase();
  if (name.endsWith('.pdf')) return 'paper';
  if (/\.(py|r|zip|tar\.gz)$/i.test(name)) return 'code';
  if (/\.(xlsx|xls|csv)$/i.test(name)) return 'data';
  return 'other';
}

/**
 * SubmitPage — client-facing submission page.
 *
 * Reuses createCase/uploadInputsParallel/submitAudit from NewAuditPage,
 * but hides operational params (agent_mode, timeout, max_retries).
 * Visual layout matches prototype SubmitPage.
 */
export default function SubmitPage({ caseId: existingCaseId, runId: _existingRunId, onNavigate }) {
  const isExistingCase = Boolean(existingCaseId);
  const [paperTitle, setPaperTitle] = useState('');
  const [tier, setTier] = useState('full');
  const [security, setSecurity] = useState('confidential');
  const [service, setService] = useState('full');
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploadProgress, setUploadProgress] = useState({});
  const [_extractingTitle, setExtractingTitle] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [fileErrors, setFileErrors] = useState(new Map());
  const [hasUnsavedFiles, setHasUnsavedFiles] = useState(false);
  const [fileStatuses, setFileStatuses] = useState(new Map());
  const [overallProgress, setOverallProgress] = useState(-1);
  const [fileCategories, setFileCategories] = useState(new Map());
  const [dragOverSlot, setDragOverSlot] = useState(null);
  const abortRef = useRef(null);
  const uploadCancelledRef = useRef(false);
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

  // addFiles uses functional state updaters so the callback doesn't close
  // over fileErrors / fileCategories — those become stale between renders,
  // which used to cause file categories to be silently overwritten on
  // rapid successive drops.  categorizeFile is pure and stable (module-scope)
  // so including it in deps is free.
  const addFiles = useCallback((newFiles, defaultCategory) => {
    const incoming = Array.from(newFiles);
    if (!incoming.length) return;

    const validFiles = [];
    const newErrors = new Map();

    for (const file of incoming) {
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (!ext || !ACCEPTED_EXT_SET.has(ext)) {
        newErrors.set(file.name, { name: file.name, size: file.size, reason: '不支持的文件类型', detail: '允许的类型：PDF, XLSX, CSV, TSV, 图片(PNG/JPG/TIFF/BMP/WEBP), ZIP/TAR.GZ' });
      } else if (file.size > MAX_FILE_SIZE_BYTES) {
        newErrors.set(file.name, { name: file.name, size: file.size, reason: '文件过大', detail: `最大 200 MB。当前：${formatMB(file.size)}。` });
      } else {
        validFiles.push(file);
        newErrors.delete(file.name);
      }
    }

    if (validFiles.length) {
      // Files + categories MUST be updated from the same `current` snapshot,
      // otherwise a rapid second drop can race with the previous render.
      setFiles((current) => {
        const existingKeys = new Set(current.map(fileKeyFor));
        const unique = validFiles.filter((f) => !existingKeys.has(fileKeyFor(f)));
        if (!unique.length) return current;
        setFileCategories((prevCategories) => {
          const next = new Map(prevCategories);
          unique.forEach((file) => {
            const category = defaultCategory || categorizeFile(file);
            next.set(fileKeyFor(file), category);
          });
          return next;
        });
        return [...current, ...unique];
      });
      setHasUnsavedFiles(true);
    }
    // Merge with latest errors rather than replacing — concurrent file ops
    // (e.g. drop + file-picker) should not clobber each other's validation.
    setFileErrors((prev) => {
      const next = new Map(prev);
      for (const [k, v] of newErrors) next.set(k, v);
      for (const f of validFiles) next.delete(f.name);
      return next;
    });
  }, []);

  function removeFile(index) {
    setFiles((current) => {
      const removed = current[index];
      if (!removed) return current;
      const removedKey = fileKeyFor(removed);
      const nextFiles = current.filter((_, i) => i !== index);
      setFileCategories((currentCategories) => {
        const next = new Map(currentCategories);
        next.delete(removedKey);
        return next;
      });
      setFileStatuses((currentStatuses) => {
        const next = new Map(currentStatuses);
        next.delete(removedKey);
        return next;
      });
      setFileErrors((currentErrors) => {
        const next = new Map(currentErrors);
        next.delete(removedKey);
        next.delete(removed.name);
        return next;
      });
      setUploadProgress((currentProgress) => {
        const { [removedKey]: _removed, ...next } = currentProgress;
        return next;
      });
      setHasUnsavedFiles(nextFiles.length > 0);
      return nextFiles;
    });
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

  function handleCancelUpload() {
    if (abortRef.current) {
      uploadCancelledRef.current = true;
      abortRef.current();
      abortRef.current = null;
    }
  }

  async function handleSubmit() {
    setError('');
    if (!files.length) {
      setError('请至少上传一个 PDF 或材料文件，请添加后重试');
      return;
    }
    if (!pdfCount) {
      setError('输入中必须包含论文 PDF，请添加后重试');
      return;
    }

    setBusy(true);
    uploadCancelledRef.current = false;
    try {
      let cid;
      if (isExistingCase) {
        cid = existingCaseId;
      } else {
        const payload = {
          paper_title: paperTitle || undefined,
          owner: 'operator',
          reproducibility_tier: tier,
        };
        const record = await createCase(payload);
        cid = record.case_id;
      }
      setUploadProgress({});
      setFileStatuses(new Map());
      setOverallProgress(0);

      const { promise, abortAll } = uploadInputsParallel(cid, files, {
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
          if (isPdf && result?.case?.paper_title && !paperTitle) {
            setPaperTitle(result.case.paper_title);
            setExtractingTitle(false);
          }
        },
        onFileError: (file, err) => {
          const fileKey = file.webkitRelativePath || file.name;
          setFileStatuses((prev) => new Map(prev).set(fileKey, `error: ${err.message}`));
        },
      });
      abortRef.current = abortAll;

      const firstPdf = files.find((f) => f.name.toLowerCase().endsWith('.pdf'));
      if (firstPdf && !paperTitle) setExtractingTitle(true);

      const { errors: uploadErrors } = await promise;
      abortRef.current = null;
      setExtractingTitle(false);
      if (uploadCancelledRef.current) {
        throw new Error('上传已取消，请重新提交');
      }
      setOverallProgress(100);

      if (uploadErrors.length === files.length) {
        throw new Error(`所有文件上传失败（${uploadErrors.length} 个文件），请检查网络后重试`);
      }
      if (uploadErrors.length > 0) {
        setError(`${uploadErrors.length} 个文件上传失败，其余文件将继续审查`);
      }

      const job = await submitAudit(cid, { options: DEFAULT_PARAMS }, tier);
      setHasUnsavedFiles(false);
      onNavigate?.('progress', { case: cid, run: job.job_id });
    } catch (nextError) {
      const msg = nextError.message || String(nextError);
      setError(msg.endsWith('重试') ? msg : `${msg}，请稍后重试`);
      setOverallProgress(-1);
      abortRef.current = null;
      uploadCancelledRef.current = false;
    } finally {
      setBusy(false);
    }
  }

  const tierDesc = TIERS.find((t) => t.value === tier)?.name || 'Full';
  const securityLabel = SECURITY_TIERS.find((s) => s.id === security)?.label || '加密';
  const serviceLabel = SERVICES.find((s) => s.id === service)?.name || '完整认证';

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      {/* Hero block */}
      <div className="mb-16">
        <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-ink-500">
          科研复核认证 · Manuscript Verification
        </div>
        <h1 className="font-display text-[56px] font-normal leading-[1.15] tracking-[-0.5px] text-ink-900">
          为您的研究<br />
          <em className="font-normal not-italic text-accent-500" style={italicStyle}>开具一份可信证明</em>
        </h1>
        <p className="mt-6 max-w-[540px] font-display text-[16px] leading-[1.7] text-ink-700" style={subtitleStyle}>
          我们不评价您的研究有多好，<br />
          我们只证明您说的是真的。
        </p>
      </div>

      <div className="my-16 h-px bg-ink-100" />

      {/* Section 01: Reproducibility tier */}
      <section className="mb-16">
        <SectionLabel num="01" title="声明可复现条件等级" sub="Reproducibility tier" />
        <p className="mb-7 max-w-[640px] text-[13.5px] leading-[1.7] text-ink-700">
          您能提供的材料决定本次核查可达到的最高认证等级。我们诚实降级，绝不允许低级冒充高级。
        </p>
        <div className="flex flex-col">
          {TIERS.map((t) => (
            <TierRow
              key={t.value}
              tier={t.name}
              badge={t.badge}
              desc={t.desc}
              selected={tier === t.value}
              onClick={() => setTier(t.value)}
            />
          ))}
        </div>
      </section>

      {/* Section 02: Upload materials */}
      <section className="mb-16">
        <SectionLabel num="02" title="提交材料" sub="Submission" />
        <div
          className={`mt-5 rounded-sm border-2 border-dashed transition-[border-color,background-color,box-shadow,transform] duration-300 ease-out motion-reduce:transform-none motion-reduce:transition-none ${
            isDragging
              ? 'scale-[1.01] border-accent-500 bg-accent-100/40 shadow-lg shadow-accent-500/10 [user-select:none]'
              : 'border-ink-900/15 bg-white/45 hover:border-accent-500/40 hover:bg-accent-50/30 hover:shadow-md'
          }`}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <button
            type="button"
            className="flex w-full cursor-pointer flex-col items-center gap-4 rounded-sm p-8 text-center transition-[background-color] hover:bg-accent-50/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 disabled:cursor-not-allowed disabled:opacity-60"
            onClick={() => { if (!busy) fileInputRef.current?.click(); }}
            disabled={busy}
          >
            <div className={`grid h-14 w-14 place-items-center rounded-sm bg-accent-50 text-accent-500 transition-[background-color,transform] duration-300 motion-reduce:transform-none motion-reduce:transition-none ${
              isDragging ? 'scale-125 rotate-6 bg-accent-100' : ''
            }`}>
              <FiUploadCloud className="text-2xl" aria-hidden="true" />
            </div>
            <div>
              <p className={`font-semibold transition-colors duration-200 ${
                isDragging ? 'text-accent-600' : 'text-ink-900'
              }`}>
                {isDragging ? '松开鼠标上传文件' : '拖放文件到这里，或点击选择'}
              </p>
              <div className="mt-3 inline-flex items-center gap-2 rounded-sm bg-ink-900 px-5 py-2.5 text-sm font-medium text-paper-50">
                <FiUpload className="h-4 w-4" aria-hidden="true" />
                选择文件
              </div>
              <p className="mt-3 text-xs text-ink-400">PDF · XLSX · CSV · 图片 · ZIP · 最大 200 MB</p>
            </div>
          </button>
          <div className="flex justify-center pb-8">
            <button
              type="button"
              className="text-xs text-ink-400 transition hover:text-ink-600 focus-visible:outline-none focus-visible:underline"
              onClick={() => { if (!busy) dirInputRef.current?.click(); }}
              disabled={busy}
            >
              或选择整个目录上传
            </button>
          </div>
          <input ref={fileInputRef} type="file" multiple accept={ACCEPTED_EXTENSIONS} className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} disabled={busy} aria-label="选择文件" />
          <input ref={dirInputRef} type="file" multiple accept={ACCEPTED_EXTENSIONS} className="hidden" {...({ webkitdirectory: '', directory: '' })} onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} disabled={busy} aria-label="选择目录" />

          {/* Category slots — interactive drag targets */}
          {files.length > 0 && (
            <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-3">
              <UploadSlot
                icon={FiFileText}
                title="论文稿件"
                hint="PDF"
                files={files.filter((file) => fileCategories.get(fileKeyFor(file)) === 'paper')}
                category="paper"
                isDragging={dragOverSlot === 'paper'}
                onDragEnter={() => setDragOverSlot('paper')}
                onDragLeave={() => setDragOverSlot(null)}
                onDrop={(droppedFiles) => { addFiles(droppedFiles, 'paper'); }}
              />
              <UploadSlot
                icon={FiCode}
                title="代码仓库"
                hint="PY · R · ZIP"
                files={files.filter((file) => fileCategories.get(fileKeyFor(file)) === 'code')}
                category="code"
                isDragging={dragOverSlot === 'code'}
                onDragEnter={() => setDragOverSlot('code')}
                onDragLeave={() => setDragOverSlot(null)}
                onDrop={(droppedFiles) => { addFiles(droppedFiles, 'code'); }}
              />
              <UploadSlot
                icon={FiDatabase}
                title="数据"
                hint="XLSX · CSV"
                files={files.filter((file) => fileCategories.get(fileKeyFor(file)) === 'data')}
                category="data"
                isDragging={dragOverSlot === 'data'}
                onDragEnter={() => setDragOverSlot('data')}
                onDragLeave={() => setDragOverSlot(null)}
                onDrop={(droppedFiles) => { addFiles(droppedFiles, 'data'); }}
              />
            </div>
          )}

          {files.length > 0 && (
            <div className="mt-5 rounded-sm bg-paper-100/70 p-4">
              {overallProgress >= 0 && overallProgress < 100 && (
                <div className="mb-4">
                  <div className="mb-1 flex items-center justify-between font-mono text-xs">
                    <span className="text-ink-500">总进度</span>
                    <span className="text-accent-500">{overallProgress}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-ink-900/10">
                    <div className="h-full rounded-full bg-accent-500 transition-[width] duration-300" style={{ width: `${overallProgress}%` }} />
                  </div>
                </div>
              )}
              <div className="max-h-40 overflow-auto">
                {files.map((file, index) => {
                  const fileKey = fileKeyFor(file);
                  const status = fileStatuses.get(fileKey);
                  const category = fileCategories.get(fileKey);
                  const CategoryIcon = category === 'paper' ? FiFileText : category === 'code' ? FiCode : category === 'data' ? FiDatabase : FiFileText;
                  return (
                    <div key={`${fileKey}-${file.size}-${file.lastModified}`} className="flex items-center justify-between gap-3 rounded-sm px-2 py-1.5 text-xs transition hover:bg-white/50">
                      <div className="flex min-w-0 items-center gap-2">
                        <CategoryIcon className="h-3.5 w-3.5 shrink-0 text-ink-400" aria-hidden="true" />
                        <span className="min-w-0 truncate text-ink-700">{fileKey}</span>
                      </div>
                      <span className="flex shrink-0 items-center gap-2 tabular-nums">
                        {status === 'done' && <span className="text-green-600">已上传</span>}
                        {typeof status === 'string' && status.startsWith('error:') && <span className="text-risk-500" title={status}>上传失败</span>}
                        {status === 'uploading' && <span className="text-accent-500">{uploadProgress[fileKey] || 0}%</span>}
                        <span className="text-ink-400">{FILE_SIZE_FORMATTER.format(Math.ceil(file.size / 1024))} KB</span>
                        {!busy && (
                          <button type="button" className="rounded p-0.5 text-ink-300 transition hover:bg-risk-50 hover:text-risk-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40" aria-label={`移除 ${fileKey}`} onClick={() => removeFile(index)}>
                            <FiX className="text-sm" aria-hidden="true" />
                          </button>
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {fileErrors.size > 0 && (
            <div className="mt-4 space-y-2">
              {Array.from(fileErrors.entries()).map(([key, err]) => (
                <div key={`err-${key}`} className="rounded-sm bg-risk-50 px-3 py-2 text-xs text-risk-700">
                  <span className="font-semibold">{err.name}</span>：{err.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Section 03: Security level */}
      <section className="mb-16">
        <SectionLabel num="03" title="选择数据安全级别" sub="Data confidentiality" />
        <p className="mb-7 max-w-[640px] text-[13.5px] leading-[1.7] text-ink-700">
          不同级别决定模型在哪里运行、数据如何加密、保留多长时间。我们公开能做什么、不能做什么。
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {SECURITY_TIERS.map((t) => {
            const isSelected = security === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setSecurity(t.id)}
                className={`relative flex flex-col items-start rounded-sm border-2 p-5 text-left transition-[border-color,background-color,box-shadow] ${
                  isSelected ? 'border-ink-900 bg-paper-50 shadow-dossier' : 'border-ink-900/10 bg-white/50 hover:border-ink-900/20 hover:bg-white/70'
                }`}
              >
                {isSelected && (
                  <span className="absolute right-3 top-3 rounded-sm bg-ink-900 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-paper-50">
                    当前选择
                  </span>
                )}
                <div className="font-display text-2xl font-semibold text-ink-900">{t.label}</div>
                <div className="mt-0.5 font-mono text-[11px] text-ink-500 italic">{t.en}</div>
                <div className="mt-3 text-xs text-ink-600">{t.scenario}</div>
                <div className="my-3 h-px w-full bg-ink-900/10" />
                <ul className="space-y-2">
                  {t.features.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-ink-600">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-900/30" />
                      {f}
                    </li>
                  ))}
                </ul>
              </button>
            );
          })}
        </div>
      </section>

      {/* Section 04: Service tier */}
      <section className="mb-16">
        <SectionLabel num="04" title="选择核查服务" sub="Service tier" />
        <div className="flex flex-col">
          {SERVICES.map((s) => (
            <ServiceRow
              key={s.id}
              name={s.name}
              price={s.price}
              est={s.est}
              features={s.features}
              selected={service === s.id}
              onClick={() => setService(s.id)}
            />
          ))}
        </div>
      </section>

      {/* Submit bar */}
      <div className="flex items-center gap-5 rounded-sm bg-ink-900 px-6 py-5">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] uppercase tracking-widest text-paper-300">即将提交</div>
          <div className="mt-0.5 font-display text-base leading-snug text-paper-50">
            {serviceLabel}
            <span className="mx-1.5 text-paper-300">·</span>
            {securityLabel}级
            <span className="mx-1.5 text-paper-300">·</span>
            {tierDesc} 复现等级
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-[11px] text-paper-300">
            {security === 'standard' ? (
              <>
                <FiShield className="h-3 w-3 shrink-0" aria-hidden="true" />
                云端 API 零数据保留 · 24h 自销
              </>
            ) : security === 'confidential' ? (
              <>
                <FiLock className="h-3 w-3 shrink-0" aria-hidden="true" />
                端到端加密 · 作者持有密钥
              </>
            ) : (
              <>
                <FiLock className="h-3 w-3 shrink-0" aria-hidden="true" />
                私有 VPC 部署 · 数据不出网络
              </>
            )}
          </div>
        </div>
        <button
          type="button"
          className="shrink-0 inline-flex items-center gap-2 rounded-full bg-paper-50 px-6 py-3 text-sm font-semibold text-ink-900 transition hover:-translate-y-0.5 hover:shadow-lg active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
          onClick={handleSubmit}
          disabled={busy}
        >
          {busy ? (
            <>
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-ink-900/20 border-t-ink-900" aria-hidden="true" />
              上传中 ({overallProgress >= 0 ? `${overallProgress}%` : '…'})
            </>
          ) : (
            <>
              <FiPlay className="h-4 w-4" aria-hidden="true" />
              开始核查
            </>
          )}
        </button>
      </div>

      {error && (
        <div ref={errorRef} tabIndex={-1} role="alert" className="mt-5 rounded-sm border border-risk-300/45 bg-risk-50/70 p-4 text-sm text-risk-700">
          {error}
        </div>
      )}

      {busy && abortRef.current && (
        <div className="mt-4">
          <button type="button" className="text-sm text-risk-500 hover:underline" onClick={handleCancelUpload}>
            取消上传
          </button>
        </div>
      )}
    </div>
  );
}

function SectionLabel({ num, title, sub }) {
  return (
    <div className="mb-5 flex items-baseline gap-4 border-b border-ink-100 pb-3">
      <span className="font-mono text-[11px] tracking-[2px] text-ink-300">{num}</span>
      <span className="font-display text-[22px] font-normal text-ink-900">{title}</span>
      <span className="ml-auto text-[11px] text-ink-500 italic">{sub}</span>
    </div>
  );
}

function UploadSlot({ icon: Icon, title, hint, files, category, isDragging, onDragEnter, onDragLeave, onDrop }) {
  const hasFiles = files && files.length > 0;

  function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files.length) {
      onDrop(e.dataTransfer.files);
    }
    onDragLeave?.();
  }

  return (
    <div
      data-testid={`upload-slot-${category}`}
      className={`flex flex-col items-start gap-3 rounded-sm border-2 p-5 transition-colors ${
        isDragging
          ? 'border-accent-500 bg-accent-50'
          : hasFiles
            ? 'border-ink-900/20 bg-paper-50'
            : 'border-dashed border-ink-900/10 bg-white/50 hover:border-ink-900/20'
      }`}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <Icon size={18} strokeWidth={1.4} className={hasFiles || isDragging ? 'text-ink-900' : 'text-ink-400'} aria-hidden="true" />
      <div className="w-full">
        <div className="text-sm font-medium text-ink-900">{title}</div>
        <div className="mt-0.5 text-xs text-ink-400">{hint}</div>
        {hasFiles ? (
          <>
            <div className="mt-2 truncate text-xs text-ink-700">{files[0].name}</div>
            <div className="mt-0.5 text-[11px] text-ink-400">{files.length} 个文件</div>
          </>
        ) : (
          <div className="mt-2 text-xs text-ink-300">{isDragging ? '松开以添加' : '拖放文件至此'}</div>
        )}
      </div>
    </div>
  );
}
