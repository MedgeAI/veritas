/**
 * 客户门户 URL workspace 管理
 *
 * 客户页使用独立的 URL 参数体系：
 * - tab: submit | progress | report | issue | reverification | verify
 * - case: case_id
 * - run: run_id
 * - finding: finding_id
 *
 * 与运营后台的 ?page= 体系完全分离
 */

const VALID_TABS = ['submit', 'progress', 'report', 'issue', 'reverification', 'verify'];

/**
 * 解析当前 URL 中的客户 workspace 参数
 * @returns {{ tab: string, case: string, run: string, finding: string }}
 */
export function parseClientWorkspace() {
  const params = new URLSearchParams(window.location.search);

  const tab = params.get('tab') || 'submit';
  const caseId = params.get('case') || '';
  const runId = params.get('run') || '';
  const findingId = params.get('finding') || '';

  return {
    tab: VALID_TABS.includes(tab) ? tab : 'submit',
    case: caseId,
    run: runId,
    finding: findingId,
  };
}

/**
 * 写入客户 workspace 参数到 URL
 * @param {{ tab?: string, case?: string, run?: string, finding?: string }} workspace
 */
export function writeClientWorkspace({ tab, case: caseId, run: runId, finding: findingId }) {
  const params = new URLSearchParams(window.location.search);

  if (tab !== undefined) {
    if (VALID_TABS.includes(tab)) {
      params.set('tab', tab);
    } else {
      params.delete('tab');
    }
  }

  if (caseId !== undefined) {
    if (caseId) {
      params.set('case', caseId);
    } else {
      params.delete('case');
    }
  }

  if (runId !== undefined) {
    if (runId) {
      params.set('run', runId);
    } else {
      params.delete('run');
    }
  }

  if (findingId !== undefined) {
    if (findingId) {
      params.set('finding', findingId);
    } else {
      params.delete('finding');
    }
  }

  const newSearch = params.toString();
  const newUrl = newSearch ? `?${newSearch}` : '';

  window.history.pushState({}, '', `${window.location.pathname}${newUrl}`);
}
