import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SubmitPage from '../pages/client/SubmitPage.jsx';
import { createCase, submitAudit, uploadInputsParallel } from '../services/api.js';

vi.mock('../services/api.js', () => ({
  createCase: vi.fn(),
  submitAudit: vi.fn(),
  uploadInputsParallel: vi.fn(),
}));

function makeFile(name, type = 'application/octet-stream') {
  return new File(['test'], name, { type });
}

function mockSuccessfulUpload() {
  uploadInputsParallel.mockImplementation((_caseId, files, handlers = {}) => {
    handlers.onProgress?.(100);
    for (const file of files) {
      handlers.onFileComplete?.(file, { case: { paper_title: 'Uploaded Paper' } });
    }
    return {
      promise: Promise.resolve({
        results: files.map((file) => ({ file, result: {}, error: null })),
        errors: [],
      }),
      abortAll: vi.fn(),
    };
  });
}

describe('SubmitPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createCase.mockResolvedValue({ case_id: 'case-1' });
    submitAudit.mockResolvedValue({ job_id: 'run-1' });
    mockSuccessfulUpload();
  });

  it('validates files before creating a case', async () => {
    const user = userEvent.setup();
    render(<SubmitPage onNavigate={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: '开始核查' }));

    expect(createCase).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('请至少上传一个 PDF 或材料文件');
  });

  it('removes a file without opening the file picker', async () => {
    const user = userEvent.setup();
    render(<SubmitPage onNavigate={vi.fn()} />);

    await user.upload(
      screen.getByLabelText('选择文件'),
      makeFile('paper.pdf', 'application/pdf'),
    );
    const pickerClick = vi.spyOn(HTMLInputElement.prototype, 'click');

    await user.click(screen.getByRole('button', { name: '移除 paper.pdf' }));

    expect(screen.queryByText('paper.pdf')).not.toBeInTheDocument();
    expect(pickerClick).not.toHaveBeenCalled();
    pickerClick.mockRestore();
  });

  it('keeps file categories aligned after deleting a file', async () => {
    const user = userEvent.setup();
    render(<SubmitPage onNavigate={vi.fn()} />);

    await user.upload(screen.getByLabelText('选择文件'), [
      makeFile('paper.pdf', 'application/pdf'),
      makeFile('repo.zip', 'application/zip'),
      makeFile('values.csv', 'text/csv'),
    ]);

    await user.click(screen.getByRole('button', { name: '移除 paper.pdf' }));

    expect(within(screen.getByTestId('upload-slot-code')).getByText('repo.zip')).toBeInTheDocument();
    expect(within(screen.getByTestId('upload-slot-data')).getByText('values.csv')).toBeInTheDocument();
    expect(within(screen.getByTestId('upload-slot-paper')).queryByText('repo.zip')).not.toBeInTheDocument();
  });

  it('re-enables submit after audit submission fails', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    submitAudit
      .mockRejectedValueOnce(new Error('提交失败'))
      .mockResolvedValueOnce({ job_id: 'run-2' });
    render(<SubmitPage onNavigate={onNavigate} />);

    await user.upload(
      screen.getByLabelText('选择文件'),
      makeFile('paper.pdf', 'application/pdf'),
    );
    await user.click(screen.getByRole('button', { name: '开始核查' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('提交失败，请稍后重试');
    expect(screen.getByRole('button', { name: '开始核查' })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: '开始核查' }));

    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalledWith('progress', { case: 'case-1', run: 'run-2' });
    });
  });
});
