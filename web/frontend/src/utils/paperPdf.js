/**
 * PDF 角色选择与识别工具函数。
 */

/** 用户提示消息常量。 */
export const PAPER_PDF_MESSAGES = Object.freeze({
  SELECT_REQUIRED: '请选择论文正文 PDF 后再提交',
});

function isPdfName(name = '') {
  return name.toLowerCase().endsWith('.pdf');
}

export function pdfCandidateFromFile(file) {
  const path = file.webkitRelativePath || file.name;
  return {
    path,
    name: file.name,
    size_bytes: file.size || 0,
  };
}

export function pdfCandidatesFromUploadResults(results = []) {
  return results
    .filter((outcome) => outcome?.file && isPdfName(outcome.file.name))
    .map((outcome) => pdfCandidateFromFile(outcome.file));
}

export function ambiguousPaperPdfCandidates(error) {
  if (error?.code !== 'AMBIGUOUS_PAPER_PDF') return null;
  const pdfs = error?.detail?.pdfs;
  return Array.isArray(pdfs) ? pdfs : [];
}
