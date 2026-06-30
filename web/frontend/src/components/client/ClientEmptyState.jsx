import { FiArrowRight } from 'react-icons/fi';

/**
 * ClientEmptyState — unified empty-state card for client pages
 * (Progress / Report / Issue / Reverification) when URL has no case/run context.
 *
 * Replaces the old "请选择一个项目以查看 X" text.  The old copy pretended the
 * user was in a "pick a project" flow — they aren't.  They're lost.  Good empty
 * state names the actual situation and hands them one obvious next step.
 *
 * `type` selects copy for the host page.  `caseId` (optional) lets us offer a
 * case-scoped action (e.g. "为这个稿件启动审查") instead of a generic redirect.
 */

const COPY = {
  progress: {
    eyebrow_no_case: '未选择项目',
    eyebrow_no_run: '尚未开始核查',
    title_no_case: '没有可查看的核查进度',
    title_no_run: '该稿件还没有启动审查',
    body_no_case: '请先在提交页上传论文并启动审查，进度会在此处实时更新。',
    body_no_run: '请先提交论文材料，启动一次独立核查。',
    cta_no_case: '前往提交页',
    cta_no_run: '为此稿件启动审查',
  },
  report: {
    eyebrow_no_case: '未选择项目',
    eyebrow_no_run: '尚未生成报告',
    title_no_case: '没有可查看的报告',
    title_no_run: '该稿件还没有生成报告',
    body_no_case: '请先选择一个已完成的稿件，或启动一次新审查。',
    body_no_run: '核查完成后会自动生成报告，请稍候。',
    cta_no_case: '前往提交页',
    cta_no_run: '查看进度',
  },
  issue: {
    eyebrow_no_case: '未选择项目',
    title_no_case: '没有可查看的问题',
    body_no_case: '请先选择一个已生成报告的稿件，此处会列出待复核发现。',
    cta_no_case: '前往提交页',
  },
  reverification: {
    eyebrow_no_case: '未选择项目',
    title_no_case: '没有可查看的重核记录',
    body_no_case: '请先选择一个已完成审查的稿件，此处会展示修订版增量复核。',
    cta_no_case: '前往提交页',
  },
};

function getAction(type, caseId) {
  switch (type) {
    case 'progress':
      return caseId
        ? { tab: 'submit', params: { case: caseId } }
        : { tab: 'submit', params: {} };
    case 'report':
      return caseId
        ? { tab: 'progress', params: { case: caseId } }
        : { tab: 'submit', params: {} };
    case 'issue':
    case 'reverification':
    default:
      return { tab: 'submit', params: {} };
  }
}

export default function ClientEmptyState({ type, caseId, onNavigate }) {
  const copy = COPY[type] || COPY.progress;
  const hasCase = Boolean(caseId);

  // `issue` / `reverification` only have the no-case variant — fall back to it
  // when `type` doesn't define a no-run branch.
  const variant = hasCase && copy.title_no_run ? 'no_run' : 'no_case';
  const eyebrow = copy[`eyebrow_${variant}`] || copy.eyebrow_no_case;
  const title = copy[`title_${variant}`] || copy.title_no_case;
  const body = copy[`body_${variant}`] || copy.body_no_case;
  const cta = copy[`cta_${variant}`] || copy.cta_no_case;

  const action = getAction(type, caseId);

  return (
    <div className="mx-auto max-w-[980px] px-14 py-16 pb-24">
      <div className="rounded-sm border border-paper-200 bg-white p-10 text-center">
        <div className="mb-5 text-[10px] font-medium uppercase tracking-[2.5px] text-ink-500">
          {eyebrow}
        </div>
        <p className="font-display text-2xl text-ink-900">{title}</p>
        <p className="mt-3 text-sm text-ink-500">{body}</p>
        <div className="mt-8 flex justify-center">
          <button
            type="button"
            onClick={() => onNavigate?.(action.tab, action.params)}
            className="inline-flex items-center gap-2 rounded-sm bg-ink-900 px-5 py-2.5 text-sm font-medium text-paper-50 transition hover:bg-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-500/40"
          >
            {cta}
            <FiArrowRight size={14} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
